"""Spaced repetition queue model."""
from sqlalchemy import Column, Integer, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base

# Days between review stages: wrong → 3 days → 7 days → 14 days → done
REVIEW_INTERVALS = {1: 3, 2: 7, 3: 14}
MAX_STAGE = 3


class SpacedRepetitionQueue(Base):
    """
    Tracks questions that need to be re-sent to a user after a wrong answer.

    Lifecycle:
      - Created (is_active=True, completed_at=None) when a question is answered wrong.
      - stage=1 → due_date = today + 3 days
      - Answered correctly at stage N → stage advances, new due_date set.
      - Answered correctly at stage 3 → completed_at filled, is_active=False.
      - Answered wrong at any review stage → reset to stage=1, new due_date.
    """
    __tablename__ = "spaced_repetition_queue"

    id                  = Column(Integer, primary_key=True, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question_id         = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    stage               = Column(Integer, default=1, nullable=False)   # 1, 2, or 3
    due_date            = Column(DateTime, nullable=False, index=True)  # UTC date to re-send
    is_active           = Column(Boolean, default=True, nullable=False, index=True)
    original_attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    completed_at        = Column(DateTime, nullable=True)

    # Relationships
    user     = relationship("User")
    question = relationship("Question")
