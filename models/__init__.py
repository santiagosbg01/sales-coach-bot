"""Database models."""
from .base import Base, engine, SessionLocal, init_db
from .group import Group
from .user import User, ChannelIdentity, Team, UserRole, UserStatus, SalesRole, VALID_SERVICES
from .prize import Prize, Redemption
from .invite import InviteCode
from .question import Question, Rubric, QuestionCategory, DifficultyLevel, QuestionType
from .session import Session, SessionStatus
from .attempt import Attempt, Grade, FrameworkScore, PassState, AttemptType
from .alert import Alert, AlertType, AlertSeverity
from .spaced_repetition import SpacedRepetitionQueue, REVIEW_INTERVALS, MAX_STAGE
from .feedback import QuestionFeedback
from .team_report import TeamReportSnapshot


def migrate_db():
    """
    Apply lightweight column additions for databases that pre-date certain fields.
    Safe to run on every startup — each statement is wrapped in its own try/except
    so an already-existing column never aborts the rest.
    Works on both SQLite and PostgreSQL.
    """
    from sqlalchemy import text, inspect as sa_inspect

    # On a fresh DB init_db() already created all columns — skip migrations entirely
    insp = sa_inspect(engine)
    if not insp.has_table("questions"):
        return  # tables not created yet; init_db() will handle it

    migrations = [
        "ALTER TABLE questions ADD COLUMN question_type VARCHAR DEFAULT 'open_ended'",
        "ALTER TABLE questions ADD COLUMN choices JSON",
        "ALTER TABLE questions ADD COLUMN correct_answer VARCHAR(10)",
        "ALTER TABLE questions ADD COLUMN product VARCHAR(50)",
        "ALTER TABLE questions ADD COLUMN country VARCHAR(50)",
        "ALTER TABLE users ADD COLUMN sales_role VARCHAR(20)",
        "ALTER TABLE users ADD COLUMN base_country VARCHAR(50)",
        "ALTER TABLE users ADD COLUMN specializations JSON",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                # Column already exists or not applicable — safe to ignore
                conn.rollback()

    # Widen correct_answer for PostgreSQL (seed data can be >10 chars, e.g. "[Guía] ...")
    if "postgresql" in str(engine.url):
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE questions ALTER COLUMN correct_answer TYPE VARCHAR(200)"))
                conn.commit()
            except Exception:
                conn.rollback()

    # Ensure spaced_repetition_queue exists (for DBs created before SR was added)
    if not insp.has_table("spaced_repetition_queue"):
        from .spaced_repetition import SpacedRepetitionQueue
        SpacedRepetitionQueue.__table__.create(engine, checkfirst=True)

    # Ensure groups table exists (for manager groups feature)
    if not insp.has_table("groups"):
        from .group import Group
        Group.__table__.create(engine, checkfirst=True)

    # Add group_id to users if missing
    if insp.has_table("users") and "group_id" not in [c["name"] for c in insp.get_columns("users")]:
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE users ADD COLUMN group_id INTEGER REFERENCES groups(id)"))
                conn.commit()
            except Exception:
                conn.rollback()

    # Add country and parent_group_id to groups if missing
    if insp.has_table("groups"):
        cols = [c["name"] for c in insp.get_columns("groups")]
        with engine.connect() as conn:
            if "country" not in cols:
                try:
                    conn.execute(text("ALTER TABLE groups ADD COLUMN country VARCHAR(50)"))
                    conn.commit()
                except Exception:
                    conn.rollback()
            if "parent_group_id" not in cols:
                try:
                    conn.execute(text("ALTER TABLE groups ADD COLUMN parent_group_id INTEGER REFERENCES groups(id)"))
                    conn.commit()
                except Exception:
                    conn.rollback()

    # Add gamification fields to users if missing
    if insp.has_table("users"):
        ucols = [c["name"] for c in insp.get_columns("users")]
        with engine.connect() as conn:
            if "points" not in ucols:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN points INTEGER DEFAULT 0"))
                    conn.commit()
                except Exception:
                    conn.rollback()
            if "streak_current" not in ucols:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN streak_current INTEGER DEFAULT 0"))
                    conn.commit()
                except Exception:
                    conn.rollback()
            if "streak_best" not in ucols:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN streak_best INTEGER DEFAULT 0"))
                    conn.commit()
                except Exception:
                    conn.rollback()
            if "streak_last_date" not in ucols:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN streak_last_date TIMESTAMP"))
                    conn.commit()
                except Exception:
                    conn.rollback()
            for col in ("streak_notified_4_at", "streak_notified_5_at", "inactive_2day_notified_at"):
                if col not in ucols:
                    try:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} TIMESTAMP"))
                        conn.commit()
                    except Exception:
                        conn.rollback()
            if "redeem_token" not in ucols:
                try:
                    conn.execute(text("ALTER TABLE users ADD COLUMN redeem_token VARCHAR(64)"))
                    conn.commit()
                except Exception:
                    conn.rollback()

    # Ensure prizes and redemptions tables exist
    if not insp.has_table("prizes"):
        from .prize import Prize
        Prize.__table__.create(engine, checkfirst=True)
    if not insp.has_table("redemptions"):
        from .prize import Redemption
        Redemption.__table__.create(engine, checkfirst=True)

    if not insp.has_table("invite_codes"):
        from .invite import InviteCode
        InviteCode.__table__.create(engine, checkfirst=True)
    elif insp.has_table("invite_codes"):
        # Migrate invite_codes: make name/email nullable (PostgreSQL; SQLite doesn't support ALTER COLUMN)
        try:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE invite_codes ALTER COLUMN name DROP NOT NULL"))
                conn.execute(text("ALTER TABLE invite_codes ALTER COLUMN email DROP NOT NULL"))
                conn.commit()
        except Exception:
            pass

    # Telegram onboarding: show welcome once per user
    if insp.has_table("channel_identities"):
        ccols = [c["name"] for c in insp.get_columns("channel_identities")]
        if "telegram_onboarding_seen_at" not in ccols:
            with engine.connect() as conn:
                try:
                    conn.execute(text("ALTER TABLE channel_identities ADD COLUMN telegram_onboarding_seen_at TIMESTAMP"))
                    conn.commit()
                except Exception:
                    conn.rollback()

    # Session: next question send time (user chose "wait ~1h")
    if insp.has_table("sessions"):
        scols = [c["name"] for c in insp.get_columns("sessions")]
        if "next_question_send_at" not in scols:
            with engine.connect() as conn:
                try:
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN next_question_send_at TIMESTAMP"))
                    conn.commit()
                except Exception:
                    conn.rollback()

    # Question feedback table (reported mistakes)
    if not insp.has_table("question_feedback"):
        from .feedback import QuestionFeedback  # noqa: WPS433
        QuestionFeedback.__table__.create(engine, checkfirst=True)
    elif insp.has_table("question_feedback"):
        fbcols = [c["name"] for c in insp.get_columns("question_feedback")]
        if "handled" not in fbcols:
            with engine.connect() as conn:
                try:
                    if "postgresql" in str(engine.url):
                        conn.execute(
                            text(
                                "ALTER TABLE question_feedback ADD COLUMN handled BOOLEAN DEFAULT false NOT NULL"
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                "ALTER TABLE question_feedback ADD COLUMN handled INTEGER NOT NULL DEFAULT 0"
                            )
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()

    if not insp.has_table("team_report_snapshots"):
        TeamReportSnapshot.__table__.create(engine, checkfirst=True)


__all__ = [
    "Base",
    "engine",
    "SessionLocal",
    "init_db",
    "migrate_db",
    "Group",
    "User",
    "ChannelIdentity",
    "Team",
    "UserRole",
    "UserStatus",
    "SalesRole",
    "VALID_SERVICES",
    "Question",
    "Rubric",
    "QuestionCategory",
    "DifficultyLevel",
    "QuestionType",
    "Session",
    "SessionStatus",
    "Attempt",
    "Grade",
    "FrameworkScore",
    "PassState",
    "AttemptType",
    "Alert",
    "AlertType",
    "AlertSeverity",
    "SpacedRepetitionQueue",
    "REVIEW_INTERVALS",
    "MAX_STAGE",
    "Prize",
    "Redemption",
    "InviteCode",
    "QuestionFeedback",
    "TeamReportSnapshot",
]
