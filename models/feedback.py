"""User feedback on questions (reported mistakes/corrections)."""
from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from .base import Base


class QuestionFeedback(Base):
    """Free-text feedback from reps about specific questions/answers."""

    __tablename__ = "question_feedback"

    id = Column(Integer, primary_key=True, index=True)

    # Who sent the feedback
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # What it refers to
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=True, index=True)

    # Content
    comment = Column(Text, nullable=False)

    # Status
    handled = Column(Boolean, default=False, nullable=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User")
    question = relationship("Question")
    attempt = relationship("Attempt")

