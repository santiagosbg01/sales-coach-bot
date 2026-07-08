"""Database base configuration — supports SQLite (local) and PostgreSQL (Railway)."""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import Config

_db_url = Config.DATABASE_URL

# ── SQLite: ensure parent directory exists ────────────────────────────────────
if _db_url.startswith("sqlite:///"):
    _db_path = _db_url.replace("sqlite:///", "")
    _db_dir  = os.path.dirname(_db_path)
    if _db_dir:
        os.makedirs(_db_dir, exist_ok=True)

# ── PostgreSQL on Railway: URL starts with postgres:// but SQLAlchemy needs
#    postgresql://  (Railway injects the old-style prefix)
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

# ── Engine ───────────────────────────────────────────────────────────────────
_is_sqlite   = "sqlite" in _db_url
_is_postgres = "postgresql" in _db_url

engine = create_engine(
    _db_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,          # detect stale connections (important for Postgres)
    pool_recycle=300 if _is_postgres else -1,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create all tables (safe to call repeatedly — skips existing tables)."""
    from models import (
        Group, User, ChannelIdentity, Team, Question, Rubric,
        Session, Attempt, Grade, FrameworkScore, Alert,
        Prize, Redemption, InviteCode, TeamReportSnapshot,
    )
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI-style dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
