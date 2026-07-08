"""Session model."""
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from .base import Base


class SessionStatus(enum.Enum):
    """Session status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PAUSED = "paused"
    ABANDONED = "abandoned"


class Session(Base):
    """Daily training session model."""
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    status = Column(Enum(SessionStatus, native_enum=False), default=SessionStatus.PENDING, nullable=False)
    
    # Session questions
    question_ids = Column(JSON, default=list)  # List of question IDs for this session
    current_question_index = Column(Integer, default=0)
    
    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    # When to send next question (user chose "wait ~1h"); scheduler sends and clears
    next_question_send_at = Column(DateTime, nullable=True)
    
    # Summary stats (computed after completion)
    total_questions = Column(Integer, default=0)
    answered_questions = Column(Integer, default=0)
    skipped_questions = Column(Integer, default=0)
    avg_score = Column(Integer, nullable=True)  # Average score * 100 (e.g., 350 = 3.5)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="sessions")
    attempts = relationship("Attempt", back_populates="session", cascade="all, delete-orphan")
