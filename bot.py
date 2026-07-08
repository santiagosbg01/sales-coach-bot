"""Main Telegram bot entry point."""
import logging
import os
import threading
import time

# Configure logging FIRST before any other imports that might trigger SQL
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config import Config
from models import init_db, migrate_db
from handlers import (
    start_command,
    help_command,
    score_command,
    mas_command,
    redeem_command,
    setup_conversation_handler,
    setup_voice_handler,
    setup_question_callbacks,
    report_command,
    feedback_command,
    resetme_command,
    continuar_command,
    resumen_command,
    yesterday_command,
    testreview_command,
    testquestion_command,
    start_questions_command,
    start_questions_callback,
    handle_feedback_button,
    handle_redeem_callback,
)
from services.proactive_sender import setup_scheduler
from startup_enroll import seed_questions, seed_enrolled_users
from dashboard_app.bot_bridge import set_application as _set_bridge_app


def _start_dashboard():
    """Run the Flask dashboard in a background daemon thread."""
    try:
        from dashboard import app
        # Railway sets PORT automatically; fall back to DASHBOARD_PORT then 5000
        port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "5000")))
        host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
        logger.info(f"🌐 Dashboard starting on {host}:{port}")
        # use_reloader=False is required when running inside a thread
        app.run(host=host, port=port, use_reloader=False, threaded=True)
    except Exception as exc:
        logger.error(f"Dashboard failed to start: {exc}")


def main():
    """Start the bot."""
    logger.info("Initializing database...")
    init_db()
    migrate_db()

    # Ensure default groups exist: 4 country groups + 8 sub-groups (Farmers/Hunters × country)
    try:
        from models import SessionLocal, Group
        db = SessionLocal()
        countries = [("Mexico", "mexico"), ("Chile", "chile"), ("Colombia", "colombia"), ("Peru", "peru")]
        for name, code in countries:
            g = db.query(Group).filter(Group.name == name).first()
            if not g:
                db.add(Group(name=name, country=code, parent_group_id=None))
        db.flush()
        for role, (cname, code) in [("Farmers", x) for x in countries] + [("Hunters", x) for x in countries]:
            sub_name = f"{role} {cname}"
            parent = db.query(Group).filter(Group.name == cname).first()
            g = db.query(Group).filter(Group.name == sub_name).first()
            if g:
                g.parent_group_id = parent.id if parent else None
                g.country = code
            else:
                db.add(Group(name=sub_name, country=code, parent_group_id=parent.id if parent else None))
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"Could not seed default groups: {e}")

    logger.info("Seeding question banks...")
    seed_questions()

    logger.info("Seeding enrolled users...")
    seed_enrolled_users()

    Config.validate()
    logger.info("Configuration validated")

    # Start web dashboard in a background thread (daemon so it dies with the bot)
    dash_thread = threading.Thread(target=_start_dashboard, daemon=True, name="dashboard")
    dash_thread.start()

    # Brief pause to let any previous instance fully release the Telegram connection
    time.sleep(3)

    application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
    _set_bridge_app(application)   # expose to Flask dashboard thread

    # ── Command handlers ──────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("empezar",   start_command))   # Spanish: begin training (same as /start)
    application.add_handler(CommandHandler("preguntas", start_questions_command))
    application.add_handler(CommandHandler("help",     help_command))
    application.add_handler(CommandHandler("score",    score_command))
    application.add_handler(CommandHandler("mas",      mas_command))
    application.add_handler(CommandHandler("redeem",    redeem_command))
    application.add_handler(CommandHandler("report",   report_command))
    application.add_handler(CommandHandler("feedback",  feedback_command))
    application.add_handler(CommandHandler("resetme",   resetme_command))
    application.add_handler(CommandHandler("continuar",   continuar_command))
    application.add_handler(CommandHandler("resumen",     resumen_command))
    application.add_handler(CommandHandler("yesterday",   yesterday_command))
    application.add_handler(CommandHandler("testreview",  testreview_command))
    application.add_handler(CommandHandler("testquestion", testquestion_command))

    # ── Answer handlers (text + voice) ───────────────────────────────────
    application.add_handler(setup_voice_handler())
    application.add_handler(setup_conversation_handler())
    application.add_handler(CallbackQueryHandler(start_questions_callback, pattern="^start_questions$"))
    application.add_handler(CallbackQueryHandler(handle_feedback_button, pattern="^fb_"))
    application.add_handler(CallbackQueryHandler(handle_redeem_callback, pattern="^redeem_"))
    application.add_handler(setup_question_callbacks())


    # ── Proactive scheduler (Mon–Fri, 8am–6pm CST) ───────────────────────
    scheduler = setup_scheduler(application)
    scheduler.start()
    logger.info("📅 Proactive scheduler started")

    logger.info(f"🚀 {Config.APP_NAME} bot starting...")
    application.run_polling(
        allowed_updates=["message", "voice", "callback_query"],
        drop_pending_updates=True,
    )

    # Clean shutdown
    scheduler.shutdown()


if __name__ == "__main__":
    main()
