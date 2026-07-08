"""User and team models."""
from sqlalchemy import Column, Integer, String, ForeignKey, Enum, DateTime, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from .base import Base


class UserRole(enum.Enum):
    REP = "rep"
    MANAGER = "manager"
    ADMIN = "admin"


class UserStatus(enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    INACTIVE = "inactive"
    PENDING = "pending"   # Awaiting admin approval after self-enrollment


class SalesRole(enum.Enum):
    """Sales motion: new-business vs account management."""
    HUNTER = "hunter"   # New business / prospecting
    FARMER = "farmer"   # Account management / upsell


# Canonical product/service tags used in question banks and user profiles.
# Configure these to match your company by setting VALID_SERVICES in your .env
# (comma-separated), e.g. VALID_SERVICES="crm,saas,onboarding,general"
import os as _os_valid_services
_env_services = _os_valid_services.getenv("VALID_SERVICES", "").strip()
if _env_services:
    VALID_SERVICES = {s.strip() for s in _env_services.split(",") if s.strip()}
else:
    VALID_SERVICES = {"product_a", "product_b", "product_c", "general"}


class Team(Base):
    """Team model."""
    __tablename__ = "teams"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    users = relationship("User", back_populates="team", foreign_keys="User.team_id")
    

class User(Base):
    """User model."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True)
    role = Column(Enum(UserRole, native_enum=False), default=UserRole.REP, nullable=False)
    status = Column(Enum(UserStatus, native_enum=False), default=UserStatus.ACTIVE, nullable=False)
    
    # Team relationships
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    
    # Sales profile
    sales_role      = Column(Enum(SalesRole, native_enum=False), nullable=True)   # hunter / farmer
    base_country    = Column(String(50), nullable=True)               # e.g. mexico / colombia / usa / brazil
    specializations = Column(JSON, default=list)                      # product/service tags this rep sells

    # Dashboard auth (for managers/admins)
    password_hash = Column(String(255), nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_active_at = Column(DateTime, nullable=True)

    # Gamification
    points = Column(Integer, default=0, nullable=False)
    streak_current = Column(Integer, default=0, nullable=False)
    streak_best = Column(Integer, default=0, nullable=False)
    streak_last_date = Column(DateTime, nullable=True)  # stored as UTC date at 00:00
    streak_notified_4_at = Column(DateTime, nullable=True)
    streak_notified_5_at = Column(DateTime, nullable=True)
    inactive_2day_notified_at = Column(DateTime, nullable=True)
    redeem_token = Column(String(64), unique=True, nullable=True, index=True)  # for /redeem page

    # Relationships
    team = relationship("Team", back_populates="users", foreign_keys=[team_id])
    manager = relationship("User", remote_side=[id], foreign_keys=[manager_id])
    group = relationship("Group", back_populates="users", foreign_keys=[group_id])
    channel_identities = relationship("ChannelIdentity", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="user", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    redemptions = relationship("Redemption", back_populates="user", cascade="all, delete-orphan")


class ChannelIdentity(Base):
    """Channel identity mapping (Telegram user to internal user)."""
    __tablename__ = "channel_identities"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    channel = Column(String(50), default="telegram", nullable=False)  # telegram, whatsapp (future)
    
    # Telegram-specific
    telegram_user_id = Column(String(255), unique=True, index=True, nullable=True)
    telegram_username = Column(String(255), nullable=True)
    telegram_chat_id = Column(String(255), nullable=True)
    telegram_onboarding_seen_at = Column(DateTime, nullable=True)  # when user saw the welcome onboarding

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="channel_identities")
