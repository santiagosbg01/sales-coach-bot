"""
Proactive question sender — sends 5 daily questions at random times
during work hours (Mon–Fri, 8am–6pm) in each user's local timezone.
Timezones: Bogotá (Colombia), Santiago (Chile), Mexico City (Mexico), Lima (Peru).
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from models import SessionLocal, User, ChannelIdentity, UserStatus, UserRole, SessionStatus
from models import Session as SessionModel
from services.session_engine import SessionEngine
from config import Config

logger = logging.getLogger(__name__)

# Country → timezone for 8am–6pm local work hours
COUNTRY_TZ = {
    "colombia": "America/Bogota",
    "chile": "America/Santiago",
    "mexico": "America/Mexico_City",
    "peru": "America/Lima",
}
DEFAULT_TZ = pytz.timezone("America/Mexico_City")

# How many questions per day (weekdays only)
WORK_START_HOUR = 8   # 8:00 AM local
WORK_END_HOUR = 18    # 6:00 PM local
NUM_QUESTIONS = getattr(Config, "DAILY_QUESTIONS_COUNT", 5)

CST = pytz.timezone("America/Mexico_City")

# -------------------------------------------------------------------------
# Scheduler setup
# -------------------------------------------------------------------------

ADMIN_CHAT_ID = ""   # Configure via ADMIN_CHAT_ID or MANAGER_ALERT_CHAT_IDS env var

# Days without any answer before inactivity Telegram alerts (rep + their manager)
INACTIVITY_ALERT_DAYS = Config.INACTIVITY_ALERT_DAYS


def _admin_chat_ids(db=None) -> list:
    """
    Return Telegram chat IDs for Admin (feedback, redemption notes, weekly admin digest).
    Includes: MANAGER_ALERT_CHAT_IDS (config) + enrolled admins (role=ADMIN only, not MANAGER).
    """
    ids = set()
    raw = getattr(Config, "MANAGER_ALERT_CHAT_IDS", "") or ""
    for x in str(raw).split(","):
        if x.strip():
            ids.add(x.strip())
    # Add enrolled admins only (managers get alerts only for their group)
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        admins = db.query(ChannelIdentity).join(User).filter(
            User.role == UserRole.ADMIN,
            User.status == UserStatus.ACTIVE,
            ChannelIdentity.telegram_chat_id.isnot(None),
        ).all()
        for a in admins:
            if a.telegram_chat_id:
                ids.add(str(a.telegram_chat_id))
    finally:
        if close_db:
            db.close()
    if not ids:
        ids.add(ADMIN_CHAT_ID)
    return list(ids)


def setup_scheduler(application) -> AsyncIOScheduler:
    """
    Create and start an AsyncIOScheduler.
    - Plans 5 daily questions at 8:00 AM local time for each country (Bogotá, Santiago, Mexico City, Lima).
    - Expires unanswered questions at 6:30 PM local time per country.
    - Weekly summaries Mon 8:30 AM CST (reps, managers, admins); inactivity alerts 9 AM CST.
    """
    scheduler = AsyncIOScheduler(timezone=CST)

    # Plan daily questions at 8am in each country's timezone (5 questions, 8am–6pm local)
    for country_key, tz_name in COUNTRY_TZ.items():
        tz = pytz.timezone(tz_name)
        scheduler.add_job(
            plan_daily_questions,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=WORK_START_HOUR,
                minute=0,
                timezone=tz,
            ),
            args=[application, tz, [country_key]],
            id=f"plan_daily_questions_{country_key}",
            replace_existing=True,
            name=f"Plan daily questions ({country_key})",
        )

    # Expire unanswered at 6:30pm local per country
    for country_key, tz_name in COUNTRY_TZ.items():
        tz = pytz.timezone(tz_name)
        scheduler.add_job(
            expire_unanswered_questions,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=WORK_END_HOUR,
                minute=30,
                timezone=tz,
            ),
            args=[tz, [country_key]],
            id=f"expire_questions_{country_key}",
            replace_existing=True,
            name=f"Expire unanswered ({country_key})",
        )

    # Users with no base_country (or unknown): plan at 8am Mexico City
    scheduler.add_job(
        plan_daily_questions,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=WORK_START_HOUR,
            minute=0,
            timezone=DEFAULT_TZ,
        ),
        args=[application, DEFAULT_TZ, []],  # [] = only users with base_country null or not in COUNTRY_TZ
        id="plan_daily_questions_default",
        replace_existing=True,
        name="Plan daily questions (no country)",
    )
    scheduler.add_job(
        expire_unanswered_questions,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=WORK_END_HOUR,
            minute=30,
            timezone=DEFAULT_TZ,
        ),
        args=[DEFAULT_TZ, []],
        id="expire_questions_default",
        replace_existing=True,
        name="Expire unanswered (no country)",
    )

    scheduler.add_job(
        send_weekly_summary,
        trigger=CronTrigger(
            day_of_week="mon",
            hour=8,
            minute=30,
            timezone=CST,
        ),
        args=[application],
        id="send_weekly_summary",
        replace_existing=True,
        name="Send weekly team summary to admin",
    )

    scheduler.add_job(
        send_daily_admin_digest,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=8,
            minute=10,
            timezone=CST,
        ),
        args=[application],
        id="send_daily_admin_digest",
        replace_existing=True,
        name="Send daily admin digest (yesterday)",
    )

    scheduler.add_job(
        check_and_send_inactivity_alerts,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=0,
            timezone=CST,
        ),
        args=[application],
        id="inactivity_alerts",
        replace_existing=True,
        name="Rep + manager: 3+ days no activity",
    )

    scheduler.add_job(
        generate_friday_dashboard_report,
        trigger=CronTrigger(
            day_of_week="fri",
            hour=10,
            minute=0,
            timezone=CST,
        ),
        args=[application],
        id="generate_friday_dashboard_report",
        replace_existing=True,
        name="Reporte semanal dashboard (viernes 10am CST)",
    )

    scheduler.add_job(
        send_friday_report_email,
        trigger=CronTrigger(
            day_of_week="fri",
            hour=11,
            minute=0,
            timezone=CST,
        ),
        args=[application],
        id="send_friday_report_email",
        replace_existing=True,
        name="Email reporte semanal a todos (viernes 11am CST)",
    )

    logger.info(
        "📅 Scheduler: 5 questions/weekday at 8am local (Bogotá, Santiago, Mexico, Lima, default); "
        "expiry 6:30pm local; daily admin digest 8:10am CST; weekly summaries Mon 8:30am CST; inactivity 9am CST; "
        "reporte equipo viernes 10am CST; email a todos viernes 11am CST"
    )
    return scheduler


# -------------------------------------------------------------------------
# Daily planning job
# -------------------------------------------------------------------------

async def plan_daily_questions(application, tz, countries) -> None:
    """
    Runs at 8:00 AM local time (tz) on weekdays.
    countries: list of base_country values (e.g. ["mexico"]) or [] for users with no base_country.
    For each matching active enrolled user:
      1. Create (or reuse) today's session (5 questions).
      2. Pick N random send times between 8am–6pm in tz.
      3. Schedule individual send-question jobs (in UTC).
    """
    now_local = datetime.now(tz)
    logger.info(f"📋 Planning daily questions for {now_local.strftime('%A %Y-%m-%d')} tz={tz.zone} countries={countries}")

    db = SessionLocal()
    try:
        q = (
            db.query(ChannelIdentity)
            .join(User)
            .filter(
                User.status == UserStatus.ACTIVE,
                ChannelIdentity.telegram_chat_id.isnot(None),
            )
        )
        if countries is not None and len(countries) > 0:
            q = q.filter(User.base_country.in_([c.lower() for c in countries]))
        else:
            # Only users with no base_country or base_country not in COUNTRY_TZ
            from sqlalchemy import or_
            q = q.filter(
                or_(
                    User.base_country.is_(None),
                    User.base_country == "",
                    ~User.base_country.in_(list(COUNTRY_TZ.keys())),
                )
            )
        identities = q.all()

        logger.info(f"  Found {len(identities)} enrolled user(s) for this run")

        for identity in identities:
            user = identity.user
            chat_id = identity.telegram_chat_id

            engine = SessionEngine(db)

            session = engine.get_active_session(user.id)
            if not session:
                today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                today_utc = today_local.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                session = engine.create_daily_session(user.id, date=today_utc.replace(tzinfo=None))
                logger.info(f"  Created session {session.id} for {user.name}")
            else:
                logger.info(f"  Reusing session {session.id} for {user.name}")

            n_questions = len(session.question_ids or [])
            if n_questions == 0:
                logger.warning(f"  No questions in session for {user.name}, skipping")
                continue

            # Questions are sent only when user runs /preguntas or after "wait ~1h"; no proactive scheduled sends
            logger.info(f"  Session {session.id} ready for {user.name} ({n_questions} questions) — user starts via /preguntas")

    except Exception as e:
        logger.exception(f"Error in plan_daily_questions: {e}")
    finally:
        db.close()


# -------------------------------------------------------------------------
# Per-question send job (called by PTB job queue)
# -------------------------------------------------------------------------

async def _send_question_job(context) -> None:
    """PTB JobQueue callback — sends one question to the user."""
    data       = context.job.data
    chat_id    = data["chat_id"]
    user_id    = data["user_id"]
    session_id = data["session_id"]
    q_index    = data["question_index"]

    db = SessionLocal()
    try:
        session = db.query(SessionModel).get(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found, skipping")
            return

        # Skip if already completed or paused
        if session.status in (SessionStatus.COMPLETED, SessionStatus.PAUSED):
            logger.info(f"Session {session_id} is {session.status.value}, skipping Q{q_index}")
            return

        # Only send if this is the next expected question index
        if session.current_question_index != q_index:
            logger.info(
                f"Session {session_id} at index {session.current_question_index}, "
                f"skipping scheduled Q{q_index}"
            )
            return

        engine = SessionEngine(db)

        # Start session on first question
        if session.status == SessionStatus.PENDING:
            engine.start_session(session_id)

        question = engine.get_current_question(session)
        if not question:
            logger.info(f"No question at index {q_index} for session {session_id}")
            return

        total    = len(session.question_ids)

        from handlers.conversations import _format_question
        text = _format_question(question, q_index + 1, total)

        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
        )

        # Store question ID in bot_data keyed by chat_id so /feedback
        # can reference it even if context.user_data isn't populated yet
        context.application.bot_data.setdefault("last_question_id", {})[chat_id] = question.id
        logger.info(f"✅ Sent Q{q_index + 1}/{total} to user {user_id} (session {session_id})")

    except Exception as e:
        logger.exception(f"Error sending question to user {user_id}: {e}")
    finally:
        db.close()


# -------------------------------------------------------------------------
# Weekly summary job
# -------------------------------------------------------------------------

async def send_weekly_summary(application) -> None:
    """
    Runs every Monday at 8:30 AM CST.
    - Each rep: personal week + accumulated stats.
    - Each group with a manager: team week + accumulated + per-rep lines.
    - Admins: digest by root group and by executive (may be multiple messages).
    """
    from datetime import timezone as tz
    from services.stats import format_rep_weekly_summary, weekly_manager_team_summary, weekly_admin_digest_chunks
    from models import Group, ChannelIdentity

    now_cst = datetime.now(CST)
    until_cst = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
    since_cst = until_cst - timedelta(days=7)

    since_utc = since_cst.astimezone(tz.utc)
    until_utc = until_cst.astimezone(tz.utc)

    logger.info(
        f"📊 Building weekly summary {since_cst.strftime('%d/%m')}–{until_cst.strftime('%d/%m/%Y')}"
    )

    db = SessionLocal()
    try:
        # ── Reps (ejecutivos) ──────────────────────────────────────────
        rep_identities = (
            db.query(ChannelIdentity)
            .join(User)
            .filter(
                User.status == UserStatus.ACTIVE,
                User.role == UserRole.REP,
                ChannelIdentity.telegram_chat_id.isnot(None),
            )
            .all()
        )
        for ident in rep_identities:
            u = ident.user
            try:
                msg = format_rep_weekly_summary(u, since_utc, until_utc, db)
                await application.bot.send_message(
                    chat_id=ident.telegram_chat_id,
                    text=msg,
                    parse_mode="Markdown",
                )
                logger.info(f"✅ Weekly rep summary → {u.name}")
            except Exception as e:
                logger.warning(f"   Failed weekly summary to rep {u.name}: {e}")

        # ── Managers (por grupo con manager asignado) ──────────────────
        groups = db.query(Group).filter(Group.manager_id.isnot(None)).all()
        for g in groups:
            mgr_ident = db.query(ChannelIdentity).filter(
                ChannelIdentity.user_id == g.manager_id,
                ChannelIdentity.telegram_chat_id.isnot(None),
            ).first()
            if not mgr_ident or not mgr_ident.telegram_chat_id:
                continue
            group_msg = weekly_manager_team_summary(g.id, since_utc, until_utc, db=db)
            if not group_msg:
                continue
            try:
                await application.bot.send_message(
                    chat_id=mgr_ident.telegram_chat_id,
                    text=group_msg,
                    parse_mode="Markdown",
                )
                logger.info(f"   ✅ Weekly manager summary → {g.name}")
            except Exception as e:
                logger.warning(f"   Failed weekly summary to manager of {g.name}: {e}")

        # ── Admins ───────────────────────────────────────────────────────
        admin_ids = _admin_chat_ids(db)
        digest_chunks = weekly_admin_digest_chunks(since_utc, until_utc, db=db)
        if not digest_chunks:
            digest_chunks = [
                "📊 *RESUMEN ADMIN —  {Config.APP_NAME}*\n_No hay ejecutivos activos para reportar._"
            ]
        for chat_id in admin_ids:
            for i, chunk in enumerate(digest_chunks):
                try:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode="Markdown",
                    )
                    logger.info(f"✅ Admin digest part {i + 1}/{len(digest_chunks)} → {chat_id}")
                except Exception as e:
                    logger.warning(f"   Failed admin digest to {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Error sending weekly summary: {e}")
    finally:
        db.close()


async def generate_friday_dashboard_report(application) -> None:
    """
    Every Friday 10:00 CST: build WoW team report for the last closed Mon–Sun week,
    persist JSON snapshot, notify admins with dashboard link.
    """
    from config import Config
    from models import SessionLocal
    from services.team_performance_report import (
        last_completed_week_bounds_cst,
        bounds_to_naive_utc,
        build_team_performance_report,
        persist_report,
        get_report_payload_for_period,
    )

    p_start_cst, p_end_cst = last_completed_week_bounds_cst()
    period_start, period_end = bounds_to_naive_utc(p_start_cst, p_end_cst)
    prev_start_cst = p_start_cst - timedelta(days=7)
    prev_end_cst = p_start_cst
    prev_start, prev_end = bounds_to_naive_utc(prev_start_cst, prev_end_cst)

    db = SessionLocal()
    try:
        prev_payload = get_report_payload_for_period(db, prev_start, prev_end)
        payload = build_team_performance_report(
            db, period_start, period_end, prev_start, prev_end, prev_payload
        )
        snap, created = persist_report(db, period_start, period_end, payload)
        base = (getattr(Config, "BASE_URL", "") or "").rstrip("/")
        link = f"{base}/reportes/{snap.id}" if base else "/reportes"
        label = (payload.get("meta") or {}).get("period_label_es", "semana")
        msg = (
            f"📑 *Reporte semanal (dashboard)*\n"
            f"_{label}_\n"
            f"{'✅ Generado y guardado.' if created else 'ℹ️ Ya existía para esta semana; mismo enlace.'}\n"
            f"[Ver reporte]({link})"
        )
        admin_ids = _admin_chat_ids(db)
        for chat_id in admin_ids:
            try:
                await application.bot.send_message(
                    chat_id=chat_id,
                    text=msg,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
                logger.info(f"✅ Friday team report → {chat_id} ({label})")
            except Exception as e:
                logger.warning(f"   Failed Friday report Telegram to {chat_id}: {e}")

    except Exception as e:
        logger.exception(f"Error generating Friday dashboard report: {e}")
    finally:
        db.close()


async def send_friday_report_email(application) -> None:
    """
    Every Friday 11:00 CST: find the most recent saved report snapshot and
    email it to all recipients (WEEKLY_REPORT_RECIPIENTS_DEFAULT + overrides).
    Runs one hour after generate_friday_dashboard_report so the report is ready.
    """
    from config import Config
    from models import SessionLocal
    from models.team_report import TeamReportSnapshot
    from services.report_email import try_send_weekly_report_email

    db = SessionLocal()
    try:
        snap = (
            db.query(TeamReportSnapshot)
            .order_by(TeamReportSnapshot.created_at.desc())
            .first()
        )
        if not snap:
            logger.warning("send_friday_report_email: no report snapshot found — skipping email")
            return

        base = (getattr(Config, "BASE_URL", "") or "").rstrip("/")
        link = f"{base}/reportes/{snap.id}" if base else "/reportes"
        payload = snap.payload or {}
    finally:
        db.close()

    email_err = await asyncio.to_thread(try_send_weekly_report_email, payload, snap.id, link)
    if email_err:
        logger.warning("Friday report email error: %s", email_err)
    else:
        label = (payload.get("meta") or {}).get("period_label_es", "semana")
        logger.info("✅ Friday report email sent (%s, snap #%s)", label, snap.id)


async def send_daily_admin_digest(application) -> None:
    """
    Runs Mon–Fri at 8:10 AM CST.
    Sends admins a digest for the previous day:
      - questions sent (and to whom)
      - answered
      - correct vs incorrect
    """
    from datetime import timezone as tz
    from services.stats import daily_admin_activity_chunks

    now_cst = datetime.now(CST)
    today_cst = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
    yday_cst = today_cst - timedelta(days=1)

    since_utc = yday_cst.astimezone(tz.utc)
    until_utc = today_cst.astimezone(tz.utc)

    db = SessionLocal()
    try:
        admin_ids = _admin_chat_ids(db)
        chunks = daily_admin_activity_chunks(since_utc, until_utc, db=db)
        if not chunks:
            logger.info("📬 Daily admin digest: nothing to report for %s, skipping.", yday_cst.strftime("%d/%m/%Y"))
            return
        for chat_id in admin_ids:
            for chunk in chunks:
                try:
                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.warning(f"   Failed daily admin digest to {chat_id}: {e}")
    except Exception as e:
        logger.exception(f"Error sending daily admin digest: {e}")
    finally:
        db.close()


def _manager_telegram_chats_for_rep(db, rep: User) -> list:
    """Telegram chat IDs for managers responsible for this rep (group hierarchy + direct manager)."""
    from models import Group

    manager_id = None
    if rep.group_id:
        g = db.query(Group).get(rep.group_id)
        if g:
            manager_id = g.manager_id
            if not manager_id and g.parent_group_id:
                parent = db.query(Group).get(g.parent_group_id)
                if parent:
                    manager_id = parent.manager_id
    if not manager_id and rep.manager_id:
        manager_id = rep.manager_id
    if not manager_id:
        return []
    ident = db.query(ChannelIdentity).filter(
        ChannelIdentity.user_id == manager_id,
        ChannelIdentity.telegram_chat_id.isnot(None),
    ).first()
    if ident and ident.telegram_chat_id:
        return [ident.telegram_chat_id]
    return []


# -------------------------------------------------------------------------
# Inactivity: 3+ days without answering (rep + their manager only)
# -------------------------------------------------------------------------

async def check_and_send_inactivity_alerts(application) -> None:
    """
    Mon–Fri 9:00 AM CST.
    Rep: alert if no activity for INACTIVITY_ALERT_DAYS (default 3).
    Manager: one batched message listing team members in that state.
    Uses last_active_at, or created_at if never answered. Dedup via inactive_2day_notified_at.
    """
    from models import UserRole, UserStatus
    from collections import defaultdict

    logger.info("🔔 Checking %s-day inactivity alerts...", INACTIVITY_ALERT_DAYS)
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        min_secs = INACTIVITY_ALERT_DAYS * 86400

        reps = db.query(User).filter(
            User.status == UserStatus.ACTIVE,
            User.role == UserRole.REP,
        ).all()

        manager_lines = defaultdict(list)  # chat_id -> [lines]

        for rep in reps:
            ref = rep.last_active_at or rep.created_at
            if not ref:
                continue
            if (now - ref).total_seconds() < min_secs:
                continue
            if rep.inactive_2day_notified_at and rep.inactive_2day_notified_at > ref:
                continue

            days_inactive = (now - ref).days
            msg_rep = (
                f"⚠️ *{Config.APP_NAME} — Sin actividad*\n\n"
                f"Llevas *{days_inactive}* día(s) sin responder en {Config.APP_NAME}.\n\n"
                f"Usa /preguntas para retomar el entrenamiento. 💪"
            )

            rep_ident = db.query(ChannelIdentity).filter(
                ChannelIdentity.user_id == rep.id,
                ChannelIdentity.telegram_chat_id.isnot(None),
            ).first()
            if rep_ident and rep_ident.telegram_chat_id:
                try:
                    await application.bot.send_message(
                        chat_id=rep_ident.telegram_chat_id,
                        text=msg_rep,
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.warning(f"   Failed inactivity alert to rep {rep.name}: {e}")

            for mgr_chat in _manager_telegram_chats_for_rep(db, rep):
                manager_lines[mgr_chat].append(f"• *{rep.name}* — {days_inactive} día(s) sin actividad")

            rep.inactive_2day_notified_at = now

        db.commit()

        for mgr_chat, lines in manager_lines.items():
            body = "\n".join(lines)
            msg_mgr = (
                f"⚠️ *{Config.APP_NAME} — Equipo sin actividad*\n\n"
                f"Ejecutivos con *{INACTIVITY_ALERT_DAYS}+* días sin responder:\n\n"
                f"{body}\n\n"
                f"_Ver detalles en el dashboard_"
            )
            try:
                await application.bot.send_message(
                    chat_id=mgr_chat,
                    text=msg_mgr,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"   Failed inactivity batch to manager {mgr_chat}: {e}")

        if manager_lines:
            logger.info(f"✅ Inactivity alerts: {len(manager_lines)} manager message(s)")
    except Exception as e:
        logger.exception(f"Error in check_and_send_inactivity_alerts: {e}")
    finally:
        db.close()


# -------------------------------------------------------------------------
# End-of-day expiry job
# -------------------------------------------------------------------------

async def expire_unanswered_questions(tz, countries) -> None:
    """
    Runs at 6:30 PM local time (tz) on weekdays.
    countries: list of base_country values (e.g. ["mexico"]) or [] for users with no base_country.
    For every active session still IN_PROGRESS belonging to matching users, marks unattempted
    questions as expired (is_skipped=True, response_text='[EXPIRADA]').
    """
    from models import Attempt, AttemptType

    now_local = datetime.now(tz)
    logger.info(f"⏰ Expiring unanswered questions for {now_local.strftime('%Y-%m-%d')} tz={tz.zone} countries={countries}")

    db = SessionLocal()
    try:
        from models import Session as SessionModel, SessionStatus, Question
        from sqlalchemy import or_

        q = db.query(SessionModel).filter(SessionModel.status == SessionStatus.IN_PROGRESS).join(User)
        if countries is not None and len(countries) > 0:
            q = q.filter(User.base_country.in_([c.lower() for c in countries]))
        else:
            q = q.filter(
                or_(
                    User.base_country.is_(None),
                    User.base_country == "",
                    ~User.base_country.in_(list(COUNTRY_TZ.keys())),
                )
            )
        active_sessions = q.all()

        expired_total = 0
        for session in active_sessions:
            question_ids = session.question_ids or []

            for q_id in question_ids:
                already_attempted = db.query(Attempt).filter(
                    Attempt.session_id == session.id,
                    Attempt.question_id == q_id,
                ).first()

                if not already_attempted:
                    now_utc = now_local.astimezone(timezone.utc).replace(tzinfo=None)
                    expired = Attempt(
                        user_id=session.user_id,
                        question_id=q_id,
                        session_id=session.id,
                        attempt_type=AttemptType.INITIAL,
                        response_text="[EXPIRADA — No respondida en 8 horas hábiles]",
                        asked_at=now_utc,
                        answered_at=now_utc,
                        is_skipped=True,
                    )
                    db.add(expired)
                    expired_total += 1
                    from services.spaced_repetition import SpacedRepetitionService
                    sr = SpacedRepetitionService(db)
                    sr.record_skip_on_review(session.user_id, q_id)

            session.status = SessionStatus.COMPLETED

        db.commit()
        logger.info(f"✅ Expired {expired_total} unanswered question(s) across {len(active_sessions)} session(s)")

    except Exception as e:
        logger.exception(f"Error in expire_unanswered_questions: {e}")
    finally:
        db.close()


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _random_times_today_local(n: int, now_local: datetime, tz) -> list:
    """
    Generate `n` sorted random datetimes between 8am and 6pm local time today in `tz`,
    all in the future relative to `now_local`. Returns list of naive UTC datetimes for job_queue.
    """
    today = now_local.date()
    start = tz.localize(datetime(today.year, today.month, today.day, WORK_START_HOUR, 0))
    end = tz.localize(datetime(today.year, today.month, today.day, WORK_END_HOUR, 0))

    window_start = max(start, now_local + timedelta(minutes=5))

    total_seconds = int((end - window_start).total_seconds())
    if total_seconds <= 0:
        return []

    offsets = sorted(random.sample(range(0, total_seconds, 60), min(n, total_seconds // 60)))
    times_local = [window_start + timedelta(seconds=s) for s in offsets]
    return [t.astimezone(timezone.utc).replace(tzinfo=None) for t in times_local]


def _random_times_today(n: int, now_cst: datetime) -> list:
    """
    Generate `n` sorted random datetimes between WORK_START and WORK_END
    today (CST), all in the future relative to `now_cst`.
    """
    today = now_cst.date()
    start = CST.localize(datetime(today.year, today.month, today.day, WORK_START_HOUR, 0))
    end   = CST.localize(datetime(today.year, today.month, today.day, WORK_END_HOUR, 0))

    # Clamp start to now if we're already past 8am
    window_start = max(start, now_cst + timedelta(minutes=5))

    total_seconds = int((end - window_start).total_seconds())
    if total_seconds <= 0:
        # Outside window, schedule for start of next workday
        return []

    offsets = sorted(random.sample(range(0, total_seconds, 60), min(n, total_seconds // 60)))
    return [window_start + timedelta(seconds=s) for s in offsets]
