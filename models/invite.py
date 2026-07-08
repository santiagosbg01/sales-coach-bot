"""Invite code model for one-time enrollment links."""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from datetime import datetime
from .base import Base


class InviteCode(Base):
    """One-time invite code for Telegram enrollment."""
    __tablename__ = "invite_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, nullable=False, index=True)

    # Legacy: pre-filled (optional; new flow collects via conversation)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    used_at = Column(DateTime, nullable=True)
    used_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
