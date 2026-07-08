"""Conversation handlers for quiz flow — all messages in Spanish."""
import io
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters
from sqlalchemy.orm import Session as DBSession
from datetime import datetime, timedelta
from typing import Optional
from openai import OpenAI
from models import (
    SessionLocal, ChannelIdentity, User, Session as SessionModel, Question,
    Attempt, Grade, AttemptType, SessionStatus, QuestionType, PassState,
    Prize,
)
from services import SessionEngine, HybridGrader
from config import Config
from handlers.commands import CATEGORY_ES

logger = logging.getLogger(__name__)

# ── Natural-language intent detection ─────────────────────────────────────────

# Single words that unambiguously mean "send me the next question"
_QUESTION_SINGLE_WORDS = frozenset([
    "otra", "siguiente", "continuar", "continue", "dale", "listo",
    "vamos", "empezar", "comenzar", "empieza", "start", "go", "next",
    "ready", "pregunta", "preguntas",
    # restart synonyms (safe: maps to /preguntas, not /resetme)
    "reiniciar", "reinicia", "restart", "reanudar",
])

# Phrases (substring match, lowercased)
_QUESTION_PHRASES = [
    "otra pregunta", "siguiente pregunta", "dame una", "dame otra",
    "quiero una pregunta", "quiero otra pregunta", "más preguntas",
    "mas preguntas", "quiero más", "quiero mas", "another question",
    "give me", "manda pregunta", "envía pregunta", "enviame una",
    "envíame una", "siguiente por favor", "otra por favor",
    "nueva pregunta", "nueva preg",
    # restart phrases
    "empieza de nuevo", "empezar de nuevo", "comenzar de nuevo",
    "comenzar desde", "empezar desde", "volver a empezar",
    "otra vez", "de nuevo", "reset", "reiniciar el bot",
    "quiero empezar", "quiero comenzar", "me puedes dar",
]

# Compact regex for short messages (≤4 words) containing these root words
_QUESTION_ROOT_RE = re.compile(
    r"\b(otr[ao]|siguiente|continu[ae]r?|dale|listo|vamos|empez[ae]r?|"
    r"comenzar|empiece|start|go|next|ready|preguntas?|"
    r"reinici[ao]r?|restart|reanudar)\b",
    re.IGNORECASE | re.UNICODE,
)


def _wants_question(text: str) -> bool:
    """Return True when the user's message is a request for the next question or a restart."""
    if not text:
        return False
    t = text.strip().lower()
    clean = re.sub(r"[^\w\s]", " ", t).strip()
    words = clean.split()

    # Entire message is one recognised trigger word
    if len(words) == 1 and words[0] in _QUESTION_SINGLE_WORDS:
        return True

    # Short messages (≤5 words) that contain at least one trigger word
    if len(words) <= 5 and _QUESTION_ROOT_RE.search(t):
        return True

    # Longer messages that contain a specific multi-word trigger phrase
    for phrase in _QUESTION_PHRASES:
        if phrase in t:
            return True

    return False


async def transcribe_voice(update: Update) -> Optional[str]:
    """Download a Telegram voice note and transcribe it with OpenAI Whisper."""
    try:
        voice = update.message.voice or update.message.audio
        if not voice:
            return None

        file = await voice.get_file()
        file_bytes = await file.download_as_bytearray()

        client = OpenAI(api_key=Config.OPENAI_API_KEY)
        audio_file = io.BytesIO(bytes(file_bytes))
        audio_file.name = "voice.ogg"

        transcript = client.audio.transcriptions.create(
            model=Config.OPENAI_WHISPER_MODEL,
            file=audio_file,
            language="es",
        )
        return transcript.text.strip()
    except Exception as e:
        logger.error(f"[Whisper] Transcription failed: {e}")
        return None


async def handle_voice_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice note answers — transcribe with Whisper then grade."""
    await update.message.reply_text("🎙️ Transcribiendo tu nota de voz...")
    text = await transcribe_voice(update)
    if not text:
        await update.message.reply_text(
            "❌ No pude transcribir el audio. Intenta de nuevo o responde con texto."
        )
        return
    await update.message.reply_text(f"📝 *Transcripción:* _{text}_", parse_mode="Markdown")
    # Pass transcribed text directly — Message objects are frozen and cannot be mutated
    await handle_answer(update, context, answer_override=text)


async def handle_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    answer_override: Optional[str] = None,
):
    """
    Handle user's free-text answer (or pre-transcribed voice text).
    Works for both user-initiated (/start) and bot-initiated (scheduled) sessions.
    If context has no active session, falls back to a DB lookup.

    Guards:
    - 'grading_in_progress' lock: drops duplicate/stray messages while grading
    - 'awaiting_answer' flag: only True while waiting for the user's answer;
      set to False the moment we start processing, True again after next question is sent
    """
    # Inline feedback flow: if user just clicked "esta pregunta tiene un error"
    # we capture their free-text correction here instead of treating it as an answer.
    if context.user_data.get("awaiting_feedback_correction"):
        await _handle_inline_feedback_comment(update, context)
        return

    # Drop silently if we are already grading (prevents double-processing)
    if context.user_data.get('grading_in_progress'):
        return

    # --- Resolve session and awaiting_answer state ---
    session_id = context.user_data.get('session_id')
    raw_text = answer_override or (update.message.text if update.message else "") or ""

    if not session_id or not context.user_data.get('awaiting_answer'):
        db = SessionLocal()
        try:
            identity = db.query(ChannelIdentity).filter(
                ChannelIdentity.telegram_user_id == str(update.effective_user.id)
            ).first()
            if not identity:
                # Not enrolled — if they're asking for a question, let them know
                if _wants_question(raw_text):
                    await update.message.reply_text(
                        f"No estás inscrito en {Config.APP_NAME} aún.\n"
                        "Pide a tu manager el enlace de inscripción o visita la página del programa."
                    )
                return

            engine  = SessionEngine(db)
            session = engine.get_active_session(identity.user_id)

            if not session or session.status != SessionStatus.IN_PROGRESS:
                if _wants_question(raw_text):
                    # User is asking for a question — trigger the /preguntas flow
                    from handlers.commands import start_questions_command
                    await start_questions_command(update, context)
                    return
                # Enrolled user with no active session — give a helpful nudge
                await update.message.reply_text(
                    "No hay una pregunta activa en este momento.\n\n"
                    "• Escribe <b>otra</b>, <b>siguiente</b> o <b>reinicia</b> para recibir tu próxima pregunta\n"
                    "• Para ver tu marcador: /score\n"
                    "• Si el bot se quedó trabado: /continuar",
                    parse_mode="HTML",
                )
                return

            # Session is active (IN_PROGRESS) but awaiting_answer is False
            # (user is between questions, e.g. after clicking Esperar).
            if _wants_question(raw_text):
                # Redirect to /preguntas instead of grading the intent phrase
                from handlers.commands import start_questions_command
                await start_questions_command(update, context)
                return

            # Restore context from DB and treat the text as an answer
            context.user_data['session_id']      = session.id
            context.user_data['user_id']         = identity.user_id
            context.user_data['awaiting_answer'] = True
            session_id = session.id
        finally:
            db.close()

    # If still no session (e.g. user not enrolled) or not awaiting — ignore
    if not session_id or not context.user_data.get('awaiting_answer'):
        return

    # Acquire processing lock — released in _handle_initial_answer after next q is sent
    context.user_data['grading_in_progress'] = True
    context.user_data['awaiting_answer']     = False

    answer_text = answer_override or update.message.text
    db = SessionLocal()

    try:
        engine   = SessionEngine(db)
        session  = db.query(SessionModel).get(context.user_data['session_id'])
        question = engine.get_current_question(session)

        if not question:
            await update.message.reply_text("❌ Error: pregunta no encontrada.")
            context.user_data['grading_in_progress'] = False
            return

        qtype = question.question_type or QuestionType.OPEN_ENDED
        if qtype == QuestionType.OPEN_ENDED and not question.rubric:
            await update.message.reply_text("❌ Error: rubric no encontrado para esta pregunta.")
            context.user_data['grading_in_progress'] = False
            return

        await _handle_initial_answer(update, context, db, session, question, answer_text)

    except Exception as e:
        logger.error(f"[handle_answer] Unexpected error: {e}")
        context.user_data['grading_in_progress'] = False
        context.user_data['awaiting_answer']     = True  # Restore so user can retry
        await update.message.reply_text("⚠️ Hubo un error procesando tu respuesta. Intenta de nuevo.")
    finally:
        db.close()


def _normalise_yesno(text: str) -> str:
    """Collapse all yes/no variants (with/without accent) to 'si' or 'no'."""
    t = text.strip().lower()
    if t in ("sí", "si", "s", "yes", "y"):
        return "si"
    if t in ("no", "n"):
        return "no"
    return t


def _grade_exact(answer_text: str, correct_answer: str, qtype: QuestionType) -> dict:
    """Grade a multiple-choice or yes/no answer by exact match."""
    norm     = answer_text.strip().lower()
    expected = correct_answer.strip().lower()

    if qtype == QuestionType.YES_NO:
        norm     = _normalise_yesno(norm)
        expected = _normalise_yesno(expected)  # handles "Sí" → "si" on both sides

    is_correct = norm == expected

    score = 5 if is_correct else 0
    return {
        "score_0_5": score,
        "pass_state": PassState.PASS if is_correct else PassState.FAIL,
        "result": "GOOD" if is_correct else "BAD",
        "rubric_hits": {},
        "missed_concepts": [],
        "feedback": None,
        "grader_trace": {"method": "exact_match", "expected": expected, "received": norm},
        "grading_method": "exact_match",
    }


async def _handle_initial_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: DBSession,
    session: SessionModel,
    question: Question,
    answer_text: str,
):
    qtype = question.question_type or QuestionType.OPEN_ENDED

    # Track for /feedback context
    context.user_data['last_question_id'] = question.id

    # Validate MC answer before grading — restore gates on rejection so user can retry.
    # IMPORTANT: if the question is malformed (MC with no choices or no correct_answer),
    # don't trap the user. Degrade to open-ended grading so they can always advance.
    if qtype == QuestionType.MULTIPLE_CHOICE:
        valid_keys = {
            c["key"].lower()
            for c in (question.choices or [])
            if isinstance(c, dict) and c.get("key")
        }
        if not valid_keys or not (question.correct_answer or "").strip():
            logger.warning(
                "[handle_answer] Q%s is MULTIPLE_CHOICE but has no choices/correct_answer — "
                "grading as open_ended to avoid trapping user.",
                question.id,
            )
            qtype = QuestionType.OPEN_ENDED
        elif answer_text.strip().lower() not in valid_keys:
            keys_str = " / ".join(c["key"] for c in (question.choices or []) if isinstance(c, dict) and c.get("key"))
            await update.message.reply_text(
                f"Por favor responde solo con la letra de tu opción: {keys_str}"
            )
            context.user_data['awaiting_answer']     = True
            context.user_data['grading_in_progress'] = False
            return

    attempt = Attempt(
        user_id=context.user_data['user_id'],
        question_id=question.id,
        session_id=session.id,
        attempt_type=AttemptType.INITIAL,
        response_text=answer_text,
        asked_at=datetime.utcnow(),
        answered_at=datetime.utcnow(),
        is_skipped=False
    )
    db.add(attempt)
    db.flush()

    # Track attempt for inline feedback button
    context.user_data["last_attempt_id"] = attempt.id

    rubric = question.rubric
    grader = HybridGrader()

    if qtype == QuestionType.OPEN_ENDED:
        result = grader.grade_answer(
            question_prompt=question.prompt,
            answer_text=answer_text,
            must_have_concepts=rubric.must_have_concepts if rubric else [],
            good_to_have_concepts=rubric.good_to_have_concepts if rubric else [],
            ideal_answer=rubric.ideal_answer if rubric else None,
            reference_snippet=rubric.reference_snippet if rubric else None,
            tags=question.tags or [],
        )
    else:
        result = grader.grade_closed_answer(
            question_prompt=question.prompt,
            answer_text=answer_text,
            correct_answer=question.correct_answer or "",
            choices=question.choices or [],
            question_type=qtype.value,
            tags=question.tags or [],
        )

    grade = Grade(
        attempt_id=attempt.id,
        score_0_5=result['score_0_5'],
        pass_state=result['pass_state'],
        rubric_hits=result['rubric_hits'],
        missed_concepts=result['missed_concepts'],
        feedback=result['feedback'],
        grader_trace=result['grader_trace'],
        grading_method=result['grading_method'],
    )
    db.add(grade)
    db.commit()
    db.refresh(grade)

    # ── Gamification: streaks + points ──────────────────────────────────
    try:
        from services.gamification import GamificationService
        gf = GamificationService(db)
        gf_state = gf.record_answer(
            user_id=context.user_data['user_id'],
            answered_at=attempt.answered_at,
            score_0_5=result['score_0_5'],
        )
    except Exception:
        gf_state = None

    # ── Spaced repetition: record result and schedule/advance review ──
    from services.spaced_repetition import SpacedRepetitionService
    sr = SpacedRepetitionService(db)
    sr.record_result(
        user_id=context.user_data['user_id'],
        question_id=question.id,
        is_correct=(result.get('result') == 'GOOD'),
        attempt_id=attempt.id,
    )

    # This session's score (so "Marcador hoy" matches "Promedio hoy" at completion)
    session_attempts = db.query(Attempt).filter(
        Attempt.session_id == session.id,
        Attempt.is_skipped == False,
    ).count()
    session_correct = db.query(Grade).join(Attempt).filter(
        Attempt.session_id == session.id,
        Grade.score_0_5 >= 3,
    ).count()

    is_good = result.get('result', 'BAD') == 'GOOD'
    result_label = "✅ CORRECTO" if is_good else "❌ INCORRECTO"
    score_emoji  = _score_emoji(result['score_0_5'])

    msg = f"{score_emoji} *{result_label}*\n\n"

    if not is_good:
        if qtype == QuestionType.MULTIPLE_CHOICE:
            expected_key = question.correct_answer or ""
            match = next(
                (c for c in (question.choices or []) if c["key"].lower() == expected_key.lower()),
                None,
            )
            expected_label = f"{match['key']}) {match['text']}" if match else expected_key
            msg += f"✔️ Respuesta correcta: *{expected_label}*\n\n"

        elif qtype == QuestionType.YES_NO:
            msg += f"✔️ Respuesta correcta: *{question.correct_answer}*\n\n"

        else:  # open_ended — show ideal answer from rubric
            rubric = question.rubric
            ideal = (rubric.ideal_answer if rubric else None) or question.correct_answer
            if ideal:
                msg += f"✔️ Respuesta sugerida:\n_{ideal}_\n\n"

    if result['feedback']:
        if not is_good:
            msg += f"💡 *Por qué importa:*\n{result['feedback']}\n\n"
        else:
            msg += f"{result['feedback']}\n\n"

    # ── Progreso personal (precisión esta semana vs la anterior) ──
    try:
        now = datetime.utcnow()
        week_start = now - timedelta(days=now.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        prev_week_start = week_start - timedelta(days=7)

        user_id_for_stats = context.user_data.get("user_id")
        if user_id_for_stats:
            def _week_acc(since, until):
                answered = db.query(Grade).join(Attempt).filter(
                    Attempt.user_id == user_id_for_stats,
                    Attempt.answered_at >= since,
                    Attempt.answered_at < until,
                    Attempt.is_skipped == False,
                ).count()
                correct = db.query(Grade).join(Attempt).filter(
                    Attempt.user_id == user_id_for_stats,
                    Attempt.answered_at >= since,
                    Attempt.answered_at < until,
                    Attempt.is_skipped == False,
                    Grade.score_0_5 >= 3,
                ).count()
                return (round(correct / answered * 100), answered) if answered else (None, 0)

            cur_pct, cur_n   = _week_acc(week_start, now)
            prev_pct, prev_n = _week_acc(prev_week_start, week_start)

            if cur_pct is not None and cur_n >= 3:
                if prev_pct is not None and prev_n >= 3:
                    delta = cur_pct - prev_pct
                    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
                    trend = f" ({arrow}{abs(delta):+.0f}pp vs sem. ant.)" if delta != 0 else " (igual que sem. ant.)"
                else:
                    trend = ""
                msg += f"📈 _Tu precisión esta semana: {cur_pct}%{trend}_\n"
    except Exception:
        pass

    msg += f"📊 _Hoy: {session_correct}/{session_attempts} correctas_"

    if gf_state and gf_state.get("updated"):
        pts = gf_state.get("points_awarded", 0)
        streak = gf_state.get("streak_current", 0)
        msg += f"\n🔥 _Racha: {streak} día(s) · +{pts} pts_"

    # Send feedback as its own message, then ask "next now or wait?" or "extra?" or end
    await update.message.reply_text(msg, parse_mode="Markdown")

    # Streak milestone notifications (4-day, 5-day) → rep + manager
    if gf_state and gf_state.get("notify_streak") in (4, 5):
        n = gf_state["notify_streak"]
        rep = db.query(User).get(context.user_data["user_id"])
        rep_name = rep.name if rep else "Rep"
        milestone_msg = (
            f"🔥 *¡{n} días seguidos!*\n\n"
            f"_{rep_name}_ lleva {n} días consecutivos practicando. ¡Sigue así! 💪"
        )
        try:
            await update.message.reply_text(milestone_msg, parse_mode="Markdown")
            # Notify manager (group manager or direct manager)
            manager_id = None
            if rep and rep.group_id:
                from models import Group
                g = db.query(Group).get(rep.group_id)
                if g and g.manager_id:
                    manager_id = g.manager_id
            if not manager_id and rep and rep.manager_id:
                manager_id = rep.manager_id
            if manager_id:
                mgr_ident = db.query(ChannelIdentity).filter(
                    ChannelIdentity.user_id == manager_id,
                    ChannelIdentity.telegram_chat_id.isnot(None),
                ).first()
                if mgr_ident and mgr_ident.telegram_chat_id:
                    await context.bot.send_message(
                        chat_id=mgr_ident.telegram_chat_id,
                        text=milestone_msg,
                        parse_mode="Markdown",
                    )
        except Exception:
            pass

    await _after_answer_next_or_wait(update, context, db, session, attempt)


async def _after_answer_next_or_wait(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: DBSession,
    session: SessionModel,
    attempt: Attempt,
):
    """
    After grading: advance to next question, then either show "now or wait?" buttons,
    "extra points?" after 5, or session end message.
    """
    engine = SessionEngine(db)
    engine.advance_to_next_question(session.id)
    db.refresh(session)

    next_q = engine.get_current_question(session)
    user_id = context.user_data["user_id"]
    count_today = engine.count_today_attempts(user_id)

    if next_q:
        # There is a next question — ask "now or wait?" or report mistake
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Otra ahora", callback_data=f"next_now_{session.id}"),
                InlineKeyboardButton("Esperar ~1h", callback_data=f"wait_1h_{session.id}"),
            ],
            [
                InlineKeyboardButton(
                    "Esta pregunta/respuesta tiene un error",
                    callback_data=f"fb_{attempt.id}",
                )
            ],
        ])
        await update.message.reply_text(
            "¿Quieres otra pregunta ahora o esperar hasta el siguiente checkpoint (~1 hora)?",
            reply_markup=keyboard,
        )
        context.user_data["grading_in_progress"] = False
        # Don't set awaiting_answer — we're waiting for button click
        return

    # No next question in current list
    if count_today >= Config.DAILY_QUESTIONS_COUNT and count_today < Config.DAILY_QUESTIONS_MAX:
        # Just finished 5 (or 6–9); offer extra if at 5
        if count_today == Config.DAILY_QUESTIONS_COUNT:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Sí, continuar", callback_data=f"extra_yes_{session.id}"),
                    InlineKeyboardButton("No", callback_data=f"extra_no_{session.id}"),
                ]
            ])
            await update.message.reply_text(
                "✨ Completaste tus 5 preguntas del día.\n\n"
                "Puedes ganar *puntos extra* con hasta 5 preguntas más (10 en total). ¿Continuar?",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            context.user_data["grading_in_progress"] = False
            return
    # Really done — show end message
    await _send_session_end_message(update, context, db, session)


async def _send_session_end_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: DBSession,
    session: SessionModel,
):
    """Send completion message and clear state."""
    session_attempt_list = db.query(Attempt).filter(
        Attempt.session_id == session.id,
        Attempt.is_skipped == False,
    ).all()
    session_scores = []
    session_points = 0
    session_correct = 0
    for a in session_attempt_list:
        g = db.query(Grade).filter(Grade.attempt_id == a.id).first()
        if g is not None:
            session_scores.append(g.score_0_5)
            is_correct = g.score_0_5 >= 3
            session_points += 1 + (5 if is_correct else 0)
            if is_correct:
                session_correct += 1

    avg = (
        sum(session_scores) / len(session_scores)
        if session_scores
        else (session.avg_score / 100 if session.avg_score else 0)
    )

    user = db.query(User).get(session.user_id)
    total_points = int(getattr(user, "points", 0) or 0) if user else 0

    end_msg = (
        "✨ *¡Entrenamiento de hoy completado!*\n\n"
        f"📊 Promedio hoy: {avg:.1f}/5\n"
        f"⭐ Puntos de hoy: {session_points}  ·  Correctas hoy: {session_correct}/{len(session_attempt_list) or 0}\n"
        f"💰 Puntos acumulados: {total_points}\n\n"
    )

    # Prize suggestions based on current points
    keyboard = None
    if user:
        affordable = (
            db.query(Prize)
            .filter(Prize.active == True, Prize.points_cost <= total_points)  # noqa: E712
            .order_by(Prize.points_cost.asc())
            .all()
        )
        if affordable:
            # Pick up to 3 cheapest prizes
            top = affordable[:3]
            end_msg += "🎁 *Premios que ya puedes canjear:*\n"
            for p in top:
                end_msg += f"- {p.name} ({p.points_cost} pts)\n"
            end_msg += (
                "\nPulsa un premio para canjearlo ahora desde Telegram.\n"
                "Recibirás un comprobante de tu canje aquí mismo."
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"{p.name} ({p.points_cost} pts)",
                            callback_data=f"redeem_{p.id}",
                        )
                    ]
                    for p in top
                ]
            )
        else:
            end_msg += (
                "🎁 Aún no alcanzas un premio, pero cada respuesta suma.\n"
                "Cuando tengas suficientes puntos, podrás canjearlos por premios desde aquí."
            )

    end_msg += "\n\n¡Vuelve mañana para seguir practicando! 🚀"
    context.user_data["awaiting_answer"] = False
    context.user_data["grading_in_progress"] = False
    # Use message.reply_text if we have a message (from answer flow); callback uses query.message
    msg = getattr(update, "message", None) or (
        getattr(update, "callback_query", None) and update.callback_query.message
    )
    if msg:
        await msg.reply_text(end_msg, parse_mode="Markdown", reply_markup=keyboard)


async def _next_question(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: DBSession,
    session: SessionModel,
):
    engine = SessionEngine(db)
    engine.advance_to_next_question(session.id)
    db.refresh(session)

    next_q = engine.get_current_question(session)

    if not next_q:
        end_msg = "✨ *¡Entrenamiento de hoy completado!*\n\n"
        # Compute session average from this session's grades (ensures we include the last answer and match "Marcador hoy")
        session_attempt_list = db.query(Attempt).filter(
            Attempt.session_id == session.id,
            Attempt.is_skipped == False,
        ).all()
        session_scores = []
        for a in session_attempt_list:
            g = db.query(Grade).filter(Grade.attempt_id == a.id).first()
            if g is not None:
                session_scores.append(g.score_0_5)
        if session_scores:
            avg = sum(session_scores) / len(session_scores)
            end_msg += f"📊 Promedio hoy: {avg:.1f}/5\n"
        elif session.avg_score is not None:
            end_msg += f"📊 Promedio hoy: {session.avg_score / 100:.1f}/5\n"
        end_msg += "\n¡Vuelve mañana para seguir practicando! 🚀"
        context.user_data['awaiting_answer']     = False
        context.user_data['grading_in_progress'] = False
        await update.message.reply_text(end_msg, parse_mode="Markdown")
    else:
        question_num = session.current_question_index + 1
        total = len(session.question_ids)
        context.user_data['last_question_id'] = next_q.id

        # Check if this is a spaced-repetition review question
        from services.spaced_repetition import SpacedRepetitionService
        sr = SpacedRepetitionService(db)
        review_stage = sr.get_review_stage(context.user_data.get('user_id', 0), next_q.id)

        await update.message.reply_text(
            _format_question(next_q, question_num, total, review_stage=review_stage),
            parse_mode="HTML",
        )
        context.user_data['awaiting_answer']     = True
        context.user_data['grading_in_progress'] = False


_COUNTRY_FLAG = {
    "mexico": "🇲🇽", "colombia": "🇨🇴", "chile": "🇨🇱", "peru": "🇵🇪", "all": "🌎",
}
_DIFF_ES = {"easy": "Fácil", "medium": "Medio", "hard": "Difícil"}
_TYPE_HINT = {
    "multiple_choice": "Responde con la letra (A, B, C…)",
    "yes_no":          "Responde <b>Sí</b> o <b>No</b>",
    "open_ended":      "Responde con texto o nota de voz 🎙️",
}

# Uses HTML tags — safe for any question text (no Markdown parsing issues)
_FEEDBACK_NOTE = (
    "\n\n<i>¿La pregunta no es clara, no aplica a tu país, o crees que "
    "la respuesta correcta está mal? Escríbenos: /feedback [tu comentario]</i>"
)


def _escape_html(text: str) -> str:
    """Escape HTML special characters in user-supplied text."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_question(q, question_num: int, total: int, review_stage: Optional[int] = None) -> str:
    """Build a complete question message using HTML formatting (safe for any text content)."""
    product = (q.product or "general").capitalize()
    country = q.country or "all"
    flag    = _COUNTRY_FLAG.get(country, "🌎")
    country_label = country.capitalize() if country != "all" else "Todos los países"
    diff_val = q.difficulty.value if q.difficulty else "medium"
    diff     = _DIFF_ES.get(diff_val, diff_val)
    qtype   = (q.question_type.value if q.question_type else "open_ended")
    hint    = _TYPE_HINT.get(qtype, _TYPE_HINT["open_ended"])

    meta = f"📦 {product}  {flag} {country_label}  🎯 {diff}"

    # Review badge if this is a spaced-repetition repeat
    review_note = ""
    if review_stage:
        review_note = f"\n\n🔁 <i>Repaso — respondiste esta incorrectamente. Intento {review_stage}/3.</i>"

    prompt_safe = _escape_html(q.prompt)

    if qtype == "multiple_choice" and q.choices:
        choices_text = "\n".join(
            f"  <b>{_escape_html(c['key'])})</b> {_escape_html(c['text'])}" for c in q.choices
        )
        body = (
            f"📚 <b>Pregunta {question_num}/{total}</b>\n<i>{_escape_html(meta)}</i>\n\n"
            f"{prompt_safe}\n\n{choices_text}\n\n{hint}"
        )
    else:
        body = (
            f"📚 <b>Pregunta {question_num}/{total}</b>\n<i>{_escape_html(meta)}</i>\n\n"
            f"{prompt_safe}\n\n{hint}"
        )

    return body + review_note + _FEEDBACK_NOTE


def _score_emoji(score: int) -> str:
    return {5: "🌟", 4: "⭐", 3: "👍", 2: "📝"}.get(score, "💭")


async def handle_no_session_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fallback for text messages when there is no active session.
    Gives the user a clear nudge instead of silent nothing.
    """
    await update.message.reply_text(
        "No hay una pregunta activa en este momento.\n\n"
        "• Escribe <b>otra</b>, <b>siguiente</b> o <b>reinicia</b> para recibir tu próxima pregunta\n"
        "• Para ver tu marcador: /score\n"
        "• Si el bot se quedó trabado: /continuar",
        parse_mode="HTML",
    )


def setup_conversation_handler():
    return MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)


def setup_voice_handler():
    return MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_answer)


async def handle_question_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline buttons: next_now, wait_1h, extra_yes, extra_no."""
    query = update.callback_query
    await query.answer()
    data = (query.data or "").strip()
    if not data:
        return

    db = SessionLocal()
    try:
        # Pattern: next_now_<session_id>, wait_1h_<session_id>, extra_yes_<session_id>, extra_no_<session_id>
        parts = data.split("_", 2)
        if len(parts) < 3:
            return
        action = f"{parts[0]}_{parts[1]}"
        try:
            session_id = int(parts[2])
        except ValueError:
            return

        session = db.query(SessionModel).get(session_id)
        if not session:
            await query.message.reply_text("Sesión no encontrada.")
            return

        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(query.from_user.id)
        ).first()
        if not identity or identity.user_id != session.user_id:
            await query.message.reply_text("No puedes usar este botón.")
            return

        engine = SessionEngine(db)
        context.user_data["session_id"] = session.id
        context.user_data["user_id"] = session.user_id

        if action == "next_now":
            next_q = engine.get_current_question(session)
            if not next_q:
                await query.message.reply_text("No hay más preguntas. Usa /preguntas para empezar.")
                return
            context.user_data["awaiting_answer"] = True
            context.user_data["last_question_id"] = next_q.id
            question_num = session.current_question_index + 1
            total = len(session.question_ids)
            from services.spaced_repetition import SpacedRepetitionService
            sr = SpacedRepetitionService(db)
            review_stage = sr.get_review_stage(session.user_id, next_q.id)
            await query.message.reply_text(
                _format_question(next_q, question_num, total, review_stage=review_stage),
                parse_mode="HTML",
            )

        elif action == "wait_1h":
            next_q = engine.get_current_question(session)
            if not next_q:
                await query.message.reply_text("No hay más preguntas.")
                return
            session.next_question_send_at = datetime.utcnow() + timedelta(hours=1)
            db.commit()
            await query.message.reply_text(
                "⏰ Te enviaremos la siguiente pregunta en aproximadamente 1 hora.\n\n"
                "También puedes escribir /preguntas en cualquier momento para recibirla antes."
            )
            context.application.job_queue.run_once(
                _send_next_question_job,
                when=3600,
                data={"session_id": session.id, "chat_id": identity.telegram_chat_id, "user_id": session.user_id},
                name=f"next_q_{session.id}",
            )

        elif action == "extra_yes":
            session, num_added = engine.add_extra_questions(session.user_id)
            if not session or num_added == 0:
                await query.message.reply_text("No se pudieron agregar más preguntas. ¡Hasta mañana!")
                return
            db.refresh(session)
            next_q = engine.get_current_question(session)
            if not next_q:
                await query.message.reply_text("Error al cargar la siguiente pregunta.")
                return
            context.user_data["awaiting_answer"] = True
            context.user_data["last_question_id"] = next_q.id
            question_num = session.current_question_index + 1
            total = len(session.question_ids)
            from services.spaced_repetition import SpacedRepetitionService
            sr = SpacedRepetitionService(db)
            review_stage = sr.get_review_stage(session.user_id, next_q.id)
            await query.message.reply_text(
                "⭐ <b>Puntos extra</b> — aquí va la siguiente:\n\n"
                + _format_question(next_q, question_num, total, review_stage=review_stage),
                parse_mode="HTML",
            )

        elif action == "extra_no":
            engine.complete_session(session.id)
            await _send_session_end_message_callback(query, context, db, session)
    except Exception as e:
        logger.exception("question callback error: %s", e)
        await query.message.reply_text("Hubo un error. Intenta /preguntas.")
    finally:
        db.close()


async def _send_session_end_message_callback(query, context: ContextTypes.DEFAULT_TYPE, db: DBSession, session: SessionModel):
    session_attempt_list = db.query(Attempt).filter(
        Attempt.session_id == session.id,
        Attempt.is_skipped == False,
    ).all()
    session_scores = []
    for a in session_attempt_list:
        g = db.query(Grade).filter(Grade.attempt_id == a.id).first()
        if g is not None:
            session_scores.append(g.score_0_5)
    avg = sum(session_scores) / len(session_scores) if session_scores else (session.avg_score / 100 if session.avg_score else 0)
    end_msg = (
        "✨ *¡Entrenamiento de hoy completado!*\n\n"
        f"📊 Promedio hoy: {avg:.1f}/5\n\n"
        "¡Vuelve mañana para seguir practicando! 🚀"
    )
    context.user_data["awaiting_answer"] = False
    context.user_data["grading_in_progress"] = False
    await query.message.reply_text(end_msg, parse_mode="Markdown")


async def _send_next_question_job(context) -> None:
    from models import Session as SessionModel, SessionStatus
    data = context.job.data
    session_id = data["session_id"]
    chat_id = data["chat_id"]
    user_id = data["user_id"]
    db = SessionLocal()
    try:
        session = db.query(SessionModel).get(session_id)
        if not session or session.status not in (SessionStatus.IN_PROGRESS, SessionStatus.PENDING):
            return
        if not session.next_question_send_at:
            return
        engine = SessionEngine(db)
        next_q = engine.get_current_question(session)
        if not next_q:
            session.next_question_send_at = None
            db.commit()
            return
        question_num = session.current_question_index + 1
        total = len(session.question_ids)
        from services.spaced_repetition import SpacedRepetitionService
        sr = SpacedRepetitionService(db)
        review_stage = sr.get_review_stage(user_id, next_q.id)
        text = _format_question(next_q, question_num, total, review_stage=review_stage)
        session.next_question_send_at = None
        db.commit()
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    finally:
        db.close()


def setup_question_callbacks():
    return CallbackQueryHandler(handle_question_callback, pattern="^(next_now|wait_1h|extra_yes|extra_no)_")


async def handle_redeem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline callback: redeem_<prize_id> — redeem prize and send receipt."""
    from services.redemption import redeem_prize

    query = update.callback_query
    await query.answer()
    data = (query.data or "").strip()
    if not data or not data.startswith("redeem_"):
        return
    try:
        prize_id = int(data.split("_", 1)[1])
    except ValueError:
        return

    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(query.from_user.id)
        ).first()
        if not identity:
            await query.message.reply_text(
                f"No estás inscrito en {Config.APP_NAME}. Contacta a tu manager para que te agreguen."
            )
            return

        ok, msg = redeem_prize(db, identity.user_id, prize_id)
        if ok:
            await query.message.reply_text(
                msg
                + "\n\nEste mensaje es tu comprobante de canje. 🎟️\n"
                + "Enseña este mensaje al administrador para que te ayude con tu canje.",
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text(msg)
    finally:
        db.close()


async def handle_feedback_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline button: user reports that the question/answer has a mistake."""
    query = update.callback_query
    await query.answer()
    data = (query.data or "").strip()
    if not data.startswith("fb_"):
        return
    try:
        attempt_id = int(data.split("_", 1)[1])
    except ValueError:
        return

    context.user_data["awaiting_feedback_correction"] = True
    context.user_data["feedback_attempt_id"] = attempt_id
    await query.message.reply_text(
        "✍️ Gracias por avisar.\n\n"
        "Escribe en un solo mensaje qué está mal en *esta pregunta o en la respuesta correcta* "
        "(por ejemplo, país incorrecto, regla desactualizada, redacción confusa, etc.).\n\n"
        "No necesitas usar /feedback, solo manda el texto.",
        parse_mode="Markdown",
    )


async def _handle_inline_feedback_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store inline feedback, remove the attempt from scoring, and send next question."""
    comment = (update.message.text or "").strip()
    context.user_data["awaiting_feedback_correction"] = False
    attempt_id = context.user_data.get("feedback_attempt_id")
    context.user_data.pop("feedback_attempt_id", None)

    if not attempt_id or not comment:
        await update.message.reply_text(
            "No se pudo registrar el comentario. Intenta de nuevo o usa /feedback.",
        )
        return

    db = SessionLocal()
    try:
        attempt = db.query(Attempt).get(attempt_id)
        if not attempt:
            await update.message.reply_text(
                "No encontré la pregunta asociada. Puedes usar /feedback con tu comentario.",
            )
            return

        from models import QuestionFeedback, Question, User

        # Resolve context before deleting attempt
        q = db.query(Question).get(attempt.question_id)
        user = db.query(User).get(attempt.user_id)
        session = db.query(SessionModel).get(attempt.session_id)

        # Save feedback — use attempt_id=None because we delete the attempt below.
        # Keeping question_id is enough for the dashboard to link back to the question.
        fb = QuestionFeedback(
            user_id=attempt.user_id,
            question_id=attempt.question_id,
            attempt_id=None,
            comment=comment,
        )
        db.add(fb)

        # Remove this attempt + grade from scoring so it doesn't count as incorrect.
        # Must nullify ALL FK references to this attempt before deleting it,
        # otherwise PostgreSQL throws a FK constraint error and rolls back everything.
        from models import SpacedRepetitionQueue, FrameworkScore
        db.query(SpacedRepetitionQueue).filter(
            SpacedRepetitionQueue.original_attempt_id == attempt.id
        ).update({"original_attempt_id": None})
        db.query(FrameworkScore).filter(
            FrameworkScore.attempt_id == attempt.id
        ).delete()
        # Attempt.parent_attempt_id self-reference
        db.query(Attempt).filter(
            Attempt.parent_attempt_id == attempt.id
        ).update({"parent_attempt_id": None})
        if attempt.grade:
            db.delete(attempt.grade)
        db.delete(attempt)
        db.commit()

        # Forward to admin via Telegram with rich context
        from datetime import timezone as tz
        from services.proactive_sender import _admin_chat_ids

        ts = datetime.now(tz.utc).strftime("%d/%m/%Y %H:%M UTC")
        rep_name = user.name if user else f"user_id={fb.user_id}"
        question_text = f'"{q.prompt}"' if q else f"question_id={fb.question_id}"
        product_info = ""
        if q:
            product_info = f"📦 {q.product or 'general'}  🌎 {q.country or 'all'}"

        admin_msg = (
            f"⚠️ *Feedback de pregunta (bot inline)*\n"
            f"_{ts}_\n\n"
            f"👤 *Rep:* {rep_name}\n"
            f"❓ *Pregunta:* {question_text}\n"
        )
        if product_info:
            admin_msg += f"{product_info}\n"
        admin_msg += f"\n💬 *Comentario:*\n{comment}"

        chat_ids = _admin_chat_ids(db)
        for chat_id in chat_ids:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=admin_msg,
                    parse_mode="Markdown",
                )
            except Exception:
                logger.exception("Failed to forward inline feedback to %s", chat_id)

        await update.message.reply_text(
            "✅ Gracias, registré tu corrección.\n\n"
            "Esta pregunta no contará en tu marcador y te enviaré otra en su lugar.",
            parse_mode="Markdown",
        )

        # Send next question immediately (like 'Otra ahora')
        if not session:
            return
        engine = SessionEngine(db)
        next_q = engine.get_current_question(session)
        if not next_q:
            await _send_session_end_message(update, context, db, session)
            return

        context.user_data["session_id"] = session.id
        context.user_data["user_id"] = session.user_id
        context.user_data["awaiting_answer"] = True

        question_num = session.current_question_index + 1
        total = len(session.question_ids)
        from services.spaced_repetition import SpacedRepetitionService

        sr = SpacedRepetitionService(db)
        review_stage = sr.get_review_stage(session.user_id, next_q.id)
        await update.message.reply_text(
            _format_question(next_q, question_num, total, review_stage=review_stage),
            parse_mode="HTML",
        )
    finally:
        db.close()
