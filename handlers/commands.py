"""Telegram bot command handlers — all messages in Spanish."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime, timedelta
from models import (
    SessionLocal, User, ChannelIdentity, UserStatus, UserRole,
    Session as SessionModel, SessionStatus, Grade, Attempt
)
from services import SessionEngine
from config import Config

logger = logging.getLogger(__name__)

CATEGORY_ES = {
    "discovery": "Descubrimiento",
    "objections": "Manejo de objeciones",
    "qualification": "Calificación",
    "closing": "Cierre",
    "value_proposition": "Propuesta de valor",
    "general": "General",
}


def _onboarding_message(name: str) -> str:
    """Welcome onboarding shown once when user first starts. Explains daily flow, points, and commands."""
    return (
        f"👋 ¡Hola, {name}! Bienvenido a *{Config.APP_NAME}*\n\n"
        "📅 *Qué recibirás cada día*\n"
        "• *5 preguntas* de entrenamiento (lun–vie)\n"
        "• Después de cada respuesta verás si fue CORRECTO o INCORRECTO\n"
        "• Puedes pedir la siguiente pregunta *ahora* o *esperar ~1 hora* (checkpoint)\n"
        "• Hasta *10 preguntas* al día: las 5 primeras son tu rutina; las 5 extra dan *puntos adicionales*\n\n"
        "✅ *Qué hacer*\n"
        "• Responde con *texto* o *nota de voz* 🎙️\n"
        "• La calificación usa la base de conocimiento configurada por tu equipo\n\n"
        "⭐ *Puntos*\n"
        "• Ganas puntos por respuestas correctas y rachas de días consecutivos\n"
        "• Canjea puntos por premios con /redeem\n\n"
        "📌 *Comandos*\n"
        "/preguntas — Comenzar o continuar tus preguntas del día\n"
        "/continuar — Retomar si el bot no responde\n"
        "/score — Ver marcador y racha\n"
        "/redeem — Canjear puntos por premios\n"
        "/feedback [comentario] — Reportar pregunta confusa o incorrecta\n"
        "/help — Ver esta guía\n\n"
        "Cuando estés listo, usa *Comenzar preguntas* abajo o escribe /preguntas 👇"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command. Shows enrollment page URL and Telegram ID if not enrolled."""
    user = update.effective_user
    db = SessionLocal()

    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()

        if not identity:
            enroll_url = (Config.BASE_URL or "").rstrip("/") + "/enroll"
            await update.message.reply_text(
                f"👋 ¡Bienvenido a {Config.APP_NAME}!\n\n"
                "Para inscribirte, usa la página web (un administrador también puede darte de alta desde el dashboard).\n\n"
                f"📎 Página de inscripción: {enroll_url}\n\n"
                f"Tu ID de Telegram (necesario en el formulario): `{user.id}`",
                parse_mode="Markdown"
            )
            return

        internal_user = db.query(User).get(identity.user_id)

        # Always update chat_id/username (e.g. when they enrolled from web with only telegram_user_id)
        identity.telegram_username = user.username
        identity.telegram_chat_id = str(update.effective_chat.id)
        db.commit()

        if internal_user.status == UserStatus.PENDING:
            await update.message.reply_text(
                "⏳ Tu solicitud está pendiente de aprobación.\n\n"
                "Un administrador debe aprobarte antes de que puedas comenzar. Te avisaremos cuando estés listo."
            )
            return
        if internal_user.status != UserStatus.ACTIVE:
            await update.message.reply_text(
                "Tu cuenta está pausada. Usa /resume para continuar."
            )
            return

        engine = SessionEngine(db)
        session = engine.get_active_session(internal_user.id)

        if not session:
            session = engine.create_daily_session(internal_user.id)

        if session.status == SessionStatus.PENDING:
            engine.start_session(session.id)

        question = engine.get_current_question(session)

        if not question:
            await update.message.reply_text(
                "✅ ¡Ya completaste el entrenamiento de hoy!\n\n"
                "Vuelve mañana para más preguntas. ¡Excelente trabajo! 🎉"
            )
            return

        # First-time onboarding: show welcome only; do NOT send first question yet
        if identity.telegram_onboarding_seen_at is None:
            await update.message.reply_text(
                _onboarding_message(internal_user.name or "Usuario"),
                parse_mode="Markdown"
            )
            identity.telegram_onboarding_seen_at = datetime.utcnow()
            db.commit()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Comenzar preguntas", callback_data="start_questions")]
            ])
            await update.message.reply_text(
                "Pulsa el botón para recibir tu primera pregunta del día:",
                reply_markup=keyboard,
            )
            return

        # Already onboarded: send current question (retake / continuar flow)
        context.user_data['session_id'] = session.id
        context.user_data['user_id'] = internal_user.id
        context.user_data['awaiting_answer'] = True

        question_num = session.current_question_index + 1
        total = len(session.question_ids)

        from handlers.conversations import _format_question
        await update.message.reply_text(
            _format_question(question, question_num, total),
            parse_mode="HTML"
        )

    finally:
        db.close()


async def start_questions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /preguntas — Start or continue today's questions.
    Creates session with 5 questions if needed; sends first or next question.
    """
    user = update.effective_user
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()
        if not identity:
            await update.message.reply_text("No estás inscrito. Usa la página de inscripción o contacta a tu manager.")
            return

        internal_user = db.query(User).get(identity.user_id)
        if internal_user.status != UserStatus.ACTIVE:
            await update.message.reply_text("Tu cuenta no está activa. Contacta a tu manager.")
            return

        identity.telegram_chat_id = str(update.effective_chat.id)
        identity.telegram_username = user.username
        db.commit()

        engine = SessionEngine(db)

        # ── Hard daily cap check ──────────────────────────────────────────────
        count_today = engine.count_today_attempts(internal_user.id)
        if count_today >= Config.DAILY_QUESTIONS_MAX:
            await update.message.reply_text(
                "✅ ¡Ya completaste las 10 preguntas de hoy!\n\n"
                "Vuelve mañana para seguir practicando. 🚀"
            )
            return

        session = engine.get_active_session(internal_user.id)

        if not session:
            session = engine.create_daily_session(internal_user.id)

        # create_daily_session returns None when already at the daily cap
        if session is None:
            await update.message.reply_text(
                "✅ ¡Ya completaste las 10 preguntas de hoy!\n\n"
                "Vuelve mañana para seguir practicando. 🚀"
            )
            return

        if session.status == SessionStatus.PENDING:
            engine.start_session(session.id)
            db.refresh(session)

        question = engine.get_current_question(session)

        if not question:
            # Re-count in case the session was just completed
            count_today = engine.count_today_attempts(internal_user.id)
            if count_today >= Config.DAILY_QUESTIONS_MAX:
                await update.message.reply_text(
                    "✅ ¡Ya completaste las 10 preguntas de hoy!\n\n"
                    "Vuelve mañana para seguir practicando. 🚀"
                )
                return
            if count_today >= Config.DAILY_QUESTIONS_COUNT:
                await update.message.reply_text(
                    "✅ Completaste tus 5 preguntas del día.\n\n"
                    "Puedes ganar <b>puntos extra</b> con hasta 5 preguntas más (10 en total). "
                    "Cuando respondas la siguiente, te preguntaremos si quieres continuar.",
                    parse_mode="HTML",
                )
                return
            await update.message.reply_text(
                "✅ No tienes más preguntas pendientes hoy.\n\n"
                "¡Vuelve mañana! 🎉"
            )
            return

        context.user_data['session_id'] = session.id
        context.user_data['user_id'] = internal_user.id
        context.user_data['awaiting_answer'] = True

        question_num = session.current_question_index + 1
        total = len(session.question_ids)

        from handlers.conversations import _format_question
        from services.spaced_repetition import SpacedRepetitionService
        sr = SpacedRepetitionService(db)
        review_stage = sr.get_review_stage(internal_user.id, question.id)

        await update.message.reply_text(
            _format_question(question, question_num, total, review_stage=review_stage),
            parse_mode="HTML",
        )
    finally:
        db.close()


async def start_questions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Comenzar preguntas' button after onboarding. Same as /preguntas but from callback."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    msg = query.message
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()
        if not identity:
            await msg.reply_text("No estás inscrito. Usa la página de inscripción o contacta a tu manager.")
            return

        internal_user = db.query(User).get(identity.user_id)
        if internal_user.status != UserStatus.ACTIVE:
            await msg.reply_text("Tu cuenta no está activa. Contacta a tu manager.")
            return

        identity.telegram_chat_id = str(query.message.chat.id)
        identity.telegram_username = user.username
        db.commit()

        engine = SessionEngine(db)

        count_today = engine.count_today_attempts(internal_user.id)
        if count_today >= Config.DAILY_QUESTIONS_MAX:
            await msg.reply_text("✅ ¡Ya completaste las 10 preguntas de hoy! Vuelve mañana. 🚀")
            return

        session = engine.get_active_session(internal_user.id)
        if not session:
            session = engine.create_daily_session(internal_user.id)
        if session is None:
            await msg.reply_text("✅ ¡Ya completaste las 10 preguntas de hoy! Vuelve mañana. 🚀")
            return
        if session.status == SessionStatus.PENDING:
            engine.start_session(session.id)
            db.refresh(session)

        question = engine.get_current_question(session)
        if not question:
            count_today = engine.count_today_attempts(internal_user.id)
            if count_today >= Config.DAILY_QUESTIONS_MAX:
                await msg.reply_text("✅ ¡Ya completaste las 10 preguntas de hoy! Vuelve mañana. 🚀")
                return
            await msg.reply_text("✅ No tienes más preguntas pendientes hoy. ¡Vuelve mañana! 🎉")
            return

        context.user_data['session_id'] = session.id
        context.user_data['user_id'] = internal_user.id
        context.user_data['awaiting_answer'] = True

        question_num = session.current_question_index + 1
        total = len(session.question_ids)
        from handlers.conversations import _format_question
        from services.spaced_repetition import SpacedRepetitionService
        sr = SpacedRepetitionService(db)
        review_stage = sr.get_review_stage(internal_user.id, question.id)
        await msg.reply_text(
            _format_question(question, question_num, total, review_stage=review_stage),
            parse_mode="HTML",
        )
    finally:
        db.close()


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await update.message.reply_text(
        f"🎯 *{Config.APP_NAME} — Cómo funciona*\n\n"
        "📱 *Entrenamiento diario*\n"
        "• Recibes preguntas automáticas en horario laboral\n"
        "• Responde con texto o nota de voz 🎙️\n"
        "• Obtienes retroalimentación inmediata de IA\n"
        "• Tienes 8 horas hábiles para responder cada pregunta\n"
        "• Las preguntas no respondidas cuentan como incorrectas\n\n"
        "✅ *Calificación*\n"
        "• CORRECTO o INCORRECTO basado en la base de conocimiento oficial\n"
        "• La IA valida contra la base de conocimiento configurada\n\n"
        "📊 *Comandos*\n"
        "/preguntas — Comenzar o continuar tus preguntas del día\n"
        "/start — Ver esta bienvenida o retomar\n"
        "/empezar — Igual que /start\n"
        "/continuar — Retomar si el bot no responde o se quedó trabado\n"
        "/score — Ver tu marcador\n"
        "/redeem — Obtener enlace para canjear puntos por premios\n"
        "/feedback [comentario] — Reportar una pregunta confusa o incorrecta\n"
        "/help — Mostrar esta ayuda\n\n"
        "👤 *Admins:* /testquestion — enviar una pregunta aleatoria de prueba\n\n"
        "⚠️ *Importante*\n"
        "• No hay opción de saltar preguntas\n"
        "• Responde siempre — cada pregunta cuenta para tu score\n\n"
        "¿El bot no responde? Escribe /continuar para retomarlo.",
        parse_mode="Markdown"
    )


async def continuar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /continuar — Recovery command.
    Clears any stuck state and re-sends the current question so the user
    is never left in a broken flow.
    """
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(update.effective_user.id)
        ).first()

        if not identity:
            await update.message.reply_text(
                f"No estás inscrito en {Config.APP_NAME}. Contacta a tu manager para que te agreguen."
            )
            return

        engine  = SessionEngine(db)
        session = engine.get_active_session(identity.user_id)

        # Always clear stuck state first
        context.user_data['grading_in_progress'] = False
        context.user_data['awaiting_answer']     = False

        if not session:
            await update.message.reply_text(
                "No tienes preguntas pendientes en este momento.\n\n"
                "Las preguntas llegan automáticamente en horario laboral. "
                "También puedes usar /start o /empezar para comenzar una sesión ahora."
            )
            return

        if session.status not in (SessionStatus.PENDING, SessionStatus.IN_PROGRESS):
            await update.message.reply_text(
                "✅ Ya completaste el entrenamiento de hoy.\n\n"
                "¡Vuelve mañana para más preguntas! 🚀"
            )
            return

        # Start the session if it's still pending
        if session.status == SessionStatus.PENDING:
            engine.start_session(session.id)
            db.refresh(session)

        question = engine.get_current_question(session)
        if not question:
            await update.message.reply_text(
                "✅ Ya completaste el entrenamiento de hoy.\n\n"
                "¡Vuelve mañana para más preguntas! 🚀"
            )
            return

        # Restore context and re-send current question
        context.user_data['session_id']       = session.id
        context.user_data['user_id']          = identity.user_id
        context.user_data['last_question_id'] = question.id
        context.user_data['awaiting_answer']  = True

        question_num = session.current_question_index + 1
        total        = len(session.question_ids)

        from handlers.conversations import _format_question
        await update.message.reply_text(
            "🔄 <b>Retomando donde lo dejaste...</b>\n\n"
            + _format_question(question, question_num, total),
            parse_mode="HTML",
        )

    finally:
        db.close()


async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pause command."""
    user = update.effective_user
    db = SessionLocal()

    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()

        if not identity:
            await update.message.reply_text("No estás inscrito. Usa /start o /empezar para comenzar.")
            return

        internal_user = db.query(User).get(identity.user_id)
        engine = SessionEngine(db)
        session = engine.get_active_session(internal_user.id)

        if not session:
            await update.message.reply_text("No hay sesión activa para pausar.")
            return

        engine.pause_session(session.id)
        context.user_data['awaiting_answer'] = False

        await update.message.reply_text(
            "⏸️ Entrenamiento pausado.\n\n"
            "Usa /resume cuando estés listo para continuar."
        )

    finally:
        db.close()


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume command."""
    user = update.effective_user
    db = SessionLocal()

    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()

        if not identity:
            await update.message.reply_text("No estás inscrito. Contacta al admin.")
            return

        internal_user = db.query(User).get(identity.user_id)
        engine = SessionEngine(db)
        session = engine.get_active_session(internal_user.id)

        if not session or session.status != SessionStatus.PAUSED:
            await update.message.reply_text(
                "No hay sesión pausada. Usa /start o /empezar para comenzar."
            )
            return

        engine.resume_session(session.id)
        question = engine.get_current_question(session)

        if not question:
            await update.message.reply_text("¡Sesión completada!")
            return

        context.user_data['session_id'] = session.id
        context.user_data['user_id'] = internal_user.id
        context.user_data['awaiting_answer'] = True

        question_num = session.current_question_index + 1
        total = len(session.question_ids)
        category = CATEGORY_ES.get(question.category.value, question.category.value)

        await update.message.reply_text(
            f"▶️ Reanudando...\n\n"
            f"📚 *Pregunta {question_num}/{total}*\n"
            f"_{category}_\n\n"
            f"{question.prompt}",
            parse_mode="Markdown"
        )

    finally:
        db.close()


async def skip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /skip command."""
    if not context.user_data.get('awaiting_answer'):
        await update.message.reply_text(
            "No hay pregunta activa para saltar. Usa /start o /empezar."
        )
        return

    db = SessionLocal()

    try:
        session_id = context.user_data.get('session_id')
        user_id = context.user_data.get('user_id')

        engine = SessionEngine(db)
        session = db.query(SessionModel).get(session_id)
        question = engine.get_current_question(session)

        attempt = Attempt(
            user_id=user_id,
            question_id=question.id,
            session_id=session_id,
            response_text="[OMITIDA]",
            asked_at=datetime.utcnow(),
            answered_at=datetime.utcnow(),
            is_skipped=True
        )
        db.add(attempt)
        db.commit()

        # If skipped question was a review, postpone it so they don't see it every session
        from services.spaced_repetition import SpacedRepetitionService
        sr = SpacedRepetitionService(db)
        sr.record_skip_on_review(user_id, question.id)

        engine.advance_to_next_question(session_id)
        db.refresh(session)

        next_question = engine.get_current_question(session)

        if not next_question:
            await update.message.reply_text(
                "⏭️ Pregunta omitida.\n\n"
                "✅ ¡Eso es todo por hoy! Vuelve mañana."
            )
            context.user_data['awaiting_answer'] = False
            return

        question_num = session.current_question_index + 1
        total = len(session.question_ids)
        category = CATEGORY_ES.get(next_question.category.value, next_question.category.value)

        await update.message.reply_text(
            f"⏭️ Omitida.\n\n"
            f"📚 *Pregunta {question_num}/{total}*\n"
            f"_{category}_\n\n"
            f"{next_question.prompt}",
            parse_mode="Markdown"
        )

    finally:
        db.close()


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /score command — shows Current Month, Last Month, Total."""
    user = update.effective_user
    db = SessionLocal()

    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()

        if not identity:
            await update.message.reply_text("Aún no estás inscrito.")
            return

        internal_user = db.query(User).get(identity.user_id)

        from services.stats import user_stats, tag_breakdown, format_tag_breakdown
        stats = user_stats(internal_user.id, db)
        breakdown = tag_breakdown(internal_user.id, db)

        def pct(a, b): return f"{round(a/b*100)}%" if b else "—"

        def period_block(label, s):
            ans = pct(s["answered"], s["sent"])
            cor = pct(s["correct"], s["answered"])
            return (
                f"*{label}*\n"
                f"  📤 Enviadas: {s['sent']}\n"
                f"  💬 Respondidas: {s['answered']} ({ans})\n"
                f"  ✅ Correctas: {s['correct']} ({cor})\n"
                f"  ⏰ Expiradas: {s['expired']}"
            )

        # Profile badge + gamification
        profile_parts = []
        if internal_user.sales_role:
            role_label = {"hunter": "🎯 Hunter", "farmer": "🌱 Farmer"}.get(
                internal_user.sales_role.value, internal_user.sales_role.value
            )
            profile_parts.append(role_label)
        if internal_user.base_country:
            _flag = {"mexico": "🇲🇽", "colombia": "🇨🇴", "chile": "🇨🇱", "peru": "🇵🇪"}
            flag = _flag.get(internal_user.base_country, "🌎")
            profile_parts.append(f"{flag} {internal_user.base_country.capitalize()}")
        # Streak / points
        try:
            streak = int(internal_user.streak_current or 0)
            best = int(internal_user.streak_best or 0)
            pts = int(internal_user.points or 0)
            profile_parts.append(f"🔥 Racha {streak} (mejor {best})")
            profile_parts.append(f"⭐ {pts} pts")
        except Exception:
            pass
        if internal_user.specializations:
            profile_parts.append("📦 " + " · ".join(
                s.capitalize() for s in internal_user.specializations
            ))
        profile_line = "  ".join(profile_parts) if profile_parts else None

        if stats["total"]["sent"] == 0:
            msg = f"📊 *Tu marcador — {internal_user.name}*\n"
            if profile_line:
                msg += f"_{profile_line}_\n"
            msg += "\nAún no tienes preguntas registradas.\n¡Sigue practicando! 💪"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        tag_section = "\n\n━━━━━━━━━━━━━━━━━━\n" + format_tag_breakdown(breakdown)

        header = f"📊 *Tu marcador — {internal_user.name}*\n"
        if profile_line:
            header += f"_{profile_line}_\n"
        header += "━━━━━━━━━━━━━━━━━━\n\n"

        msg = (
            header
            + period_block("Mes actual", stats["current_month"]) + "\n\n"
            + period_block("Mes pasado", stats["last_month"]) + "\n\n"
            + period_block("Total histórico", stats["total"])
            + tag_section
            + "\n\n¡Sigue así! 💪"
        )

        await update.message.reply_text(msg, parse_mode="Markdown")

    finally:
        db.close()


async def mas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mas — Informational: users get 5 questions daily in work hours (no extra questions).
    """
    await update.message.reply_text(
        "Recibes *5 preguntas* cada día laboral (lun–vie, 8h–18h en tu zona).\n\n"
        "Si eres admin y quieres probar una pregunta aleatoria: /testquestion",
        parse_mode="Markdown",
    )


async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /redeem — sends the rep their personal redemption link."""
    user = update.effective_user
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()
        if not identity:
            await update.message.reply_text("Aún no estás inscrito.")
            return
        internal_user = db.query(User).get(identity.user_id)
        if not internal_user:
            await update.message.reply_text("No encontré tu cuenta. Contacta a tu manager.")
            return
        if internal_user.status != UserStatus.ACTIVE:
            await update.message.reply_text("Tu cuenta está pausada.")
            return

        from services.redemption import ensure_redeem_token
        from config import Config

        token = ensure_redeem_token(db, internal_user.id)
        base = Config.BASE_URL.rstrip("/")
        url = f"{base}/redeem?token={token}"
        pts = int(internal_user.points or 0)
        await update.message.reply_text(
            f"⭐ <b>Canjear puntos</b>\n\n"
            f"Tienes <b>{pts}</b> puntos.\n\n"
            f"Usa este enlace para canjear por premios:\n{url}\n\n"
            f"<i>Guárdalo para usarlo cuando quieras.</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("redeem_command error: %s", e)
        await update.message.reply_text(
            "❌ Hubo un error generando tu enlace de canje. Intenta de nuevo en un momento."
        )
    finally:
        db.close()


async def resumen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /resumen — Send the weekly team summary right now (admin only).
    Accepts an optional argument: /resumen 14  → last 14 days instead of 7.
    """
    import os
    from datetime import timezone as tz
    ADMIN_CHAT_ID_ENV = os.getenv("ADMIN_CHAT_ID", "")
    if not ADMIN_CHAT_ID_ENV or str(update.effective_chat.id) != ADMIN_CHAT_ID_ENV:
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return

    args = context.args or []
    try:
        days = max(1, min(int(args[0]), 90)) if args else 7
    except ValueError:
        days = 7

    from services.stats import weekly_admin_digest_chunks

    now_utc = datetime.now(tz.utc)
    until_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = until_utc - timedelta(days=days)

    await update.message.reply_text("⏳ Generando resumen...")
    try:
        chunks = weekly_admin_digest_chunks(since_utc, now_utc)
        if not chunks:
            await update.message.reply_text("_Sin ejecutivos activos._", parse_mode="Markdown")
            return
        for i, chunk in enumerate(chunks):
            footer = f"\n_Parte {i + 1}/{len(chunks)} · últimos {days} días · /report para historial_"
            await update.message.reply_text(chunk + footer, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error generando resumen: {e}")


async def yesterday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /yesterday — Admin only.
    Sends the daily admin digest for the previous day (questions sent / answered / correct / incorrect).
    """
    import os
    from datetime import timezone as tz

    ADMIN_CHAT_ID_ENV = os.getenv("ADMIN_CHAT_ID", "")
    if not ADMIN_CHAT_ID_ENV or str(update.effective_chat.id) != ADMIN_CHAT_ID_ENV:
        await update.message.reply_text("⛔ Solo el administrador puede usar este comando.")
        return

    from services.stats import daily_admin_activity_chunks

    now_utc = datetime.now(tz.utc)
    today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    yday_utc = today_utc - timedelta(days=1)

    await update.message.reply_text("⏳ Generando resumen de ayer...")
    try:
        chunks = daily_admin_activity_chunks(yday_utc, today_utc)
        if not chunks:
            await update.message.reply_text("_Sin ejecutivos activos._", parse_mode="Markdown")
            return
        for i, chunk in enumerate(chunks):
            footer = f"\n_Parte {i + 1}/{len(chunks)} · Ayer_"
            await update.message.reply_text(chunk + footer, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error generando resumen: {e}")


async def resetme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /resetme — Clear the current active session so the user can start fresh today.
    Preserves all points, streak, grades and historical attempts.
    Only marks any in-progress/pending session as COMPLETED so /preguntas
    creates a clean new one respecting the daily cap.
    """
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(update.effective_user.id)
        ).first()
        if not identity:
            await update.message.reply_text("No estás inscrito.")
            return

        user_id = identity.user_id
        engine = SessionEngine(db)

        # Close any active session (PENDING / IN_PROGRESS) — keeps all attempts and grades
        active = engine.get_active_session(user_id)
        if active:
            engine.complete_session(active.id)

        # Clear bot context so the next message starts fresh
        context.user_data.pop("session_id", None)
        context.user_data.pop("awaiting_answer", None)
        context.user_data.pop("grading_in_progress", None)
        context.user_data.pop("last_question_id", None)

        # Check remaining capacity for today
        count_today = engine.count_today_attempts(user_id)
        remaining = Config.DAILY_QUESTIONS_MAX - count_today

        if remaining <= 0:
            await update.message.reply_text(
                "✅ Ya completaste las 10 preguntas de hoy.\n\n"
                "Vuelve mañana para seguir practicando. 🚀"
            )
            return

        await update.message.reply_text(
            f"🔄 <b>Sesión reiniciada.</b>\n\n"
            f"Tus puntos y progreso están intactos.\n"
            f"Tienes <b>{remaining}</b> pregunta(s) disponibles hoy.\n\n"
            f"Escribe <b>otra</b> o usa /preguntas para continuar.",
            parse_mode="HTML",
        )

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("resetme_command error: %s", e)
        await update.message.reply_text("❌ Error al reiniciar la sesión. Intenta de nuevo.")
    finally:
        db.close()


async def testreview_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /testreview — Admin test helper.
    Forces all active spaced-repetition entries for the caller to be due NOW,
    then immediately starts a session with those review questions.
    Use to verify spaced repetition works without waiting days.
    """
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(update.effective_user.id)
        ).first()
        if not identity:
            await update.message.reply_text("No estás inscrito.")
            return

        user_id = identity.user_id

        from models import SpacedRepetitionQueue
        entries = db.query(SpacedRepetitionQueue).filter(
            SpacedRepetitionQueue.user_id   == user_id,
            SpacedRepetitionQueue.is_active == True,
        ).all()

        if not entries:
            await update.message.reply_text(
                "📭 No tienes preguntas en cola de repaso.\n\n"
                "Responde una pregunta *incorrectamente* primero y luego usa /testreview."
            )
            return

        # Force all due dates to right now so they appear in next session
        now = datetime.utcnow()
        for e in entries:
            e.due_date = now - timedelta(minutes=1)
        db.commit()

        # Close any existing active session so a fresh one picks up the reviews
        existing = db.query(SessionModel).filter(
            SessionModel.user_id == user_id,
            SessionModel.status.in_([SessionStatus.PENDING, SessionStatus.IN_PROGRESS]),
        ).all()
        for s in existing:
            s.status = SessionStatus.COMPLETED
        db.commit()

        # Build new session — SR entries are now due, engine will inject them
        engine = SessionEngine(db)
        question_ids = engine._select_questions_for_session(user_id, num_questions=len(entries))

        session = SessionModel(
            user_id=user_id,
            date=now.replace(hour=0, minute=0, second=0, microsecond=0),
            status=SessionStatus.IN_PROGRESS,
            question_ids=question_ids,
            total_questions=len(question_ids),
            current_question_index=0,
            started_at=now,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        question = engine.get_current_question(session)
        if not question:
            await update.message.reply_text("❌ No hay preguntas de repaso disponibles.")
            return

        context.user_data['session_id']       = session.id
        context.user_data['user_id']          = user_id
        context.user_data['awaiting_answer']  = True
        context.user_data['last_question_id'] = question.id

        from services.spaced_repetition import SpacedRepetitionService
        sr = SpacedRepetitionService(db)
        review_stage = sr.get_review_stage(user_id, question.id)

        from handlers.conversations import _format_question
        await update.message.reply_text(
            f"🔁 <b>Iniciando sesión de repaso — {len(question_ids)} pregunta(s)</b>\n\n"
            + _format_question(question, 1, len(question_ids), review_stage=review_stage),
            parse_mode="HTML",
        )

    finally:
        db.close()


async def testquestion_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /testquestion — Admin only. Sends one random active question for testing (no session, no grading).
    """
    db = SessionLocal()
    try:
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(update.effective_user.id),
        ).first()
        if not identity:
            await update.message.reply_text("No estás inscrito.")
            return

        user = db.query(User).get(identity.user_id)
        if not user or user.role != UserRole.ADMIN:
            await update.message.reply_text("⛔ Solo administradores pueden usar este comando.")
            return

        from models import Question
        from sqlalchemy import func

        question = (
            db.query(Question)
            .filter(Question.active == True)
            .order_by(func.random())
            .first()
        )
        if not question:
            await update.message.reply_text("❌ No hay preguntas activas en el banco.")
            return

        from handlers.conversations import _format_question
        await update.message.reply_text(
            "📋 <b>Pregunta aleatoria (prueba)</b> — no se guarda respuesta ni puntuación.\n\n"
            + _format_question(question, 1, 1),
            parse_mode="HTML",
        )
    finally:
        db.close()
