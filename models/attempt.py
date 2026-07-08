"""Attempt, grade, and framework score models."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, JSON, Enum, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from .base import Base


class PassState(enum.Enum):
    """Pass state enumeration."""
    PASS = "pass"
    BORDERLINE = "borderline"
    FAIL = "fail"


class AttemptType(enum.Enum):
    """Attempt type enumeration."""
    INITIAL = "initial"
    PROBE = "probe"


class Attempt(Base):
    """Question attempt model."""
    __tablename__ = "attempts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
    
    # Attempt details
    attempt_type = Column(Enum(AttemptType, native_enum=False), default=AttemptType.INITIAL, nullable=False)
    parent_attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=True)  # For probes
    probe_number = Column(Integer, nullable=True)  # 1, 2, 3 for probes
    probing_concepts = Column(JSON, default=list)  # Concepts being probed
    
    # Response
    response_text = Column(Text, nullable=False)
    
    # Timing
    asked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    answered_at = Column(DateTime, nullable=True)
    
    # Skipped flag
    is_skipped = Column(Boolean, default=False, nullable=False)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="attempts")
    question = relationship("Question", back_populates="attempts")
    session = relationship("Session", back_populates="attempts")
    grade = relationship("Grade", back_populates="attempt", uselist=False, cascade="all, delete-orphan")
    framework_score = relationship("FrameworkScore", back_populates="attempt", uselist=False, cascade="all, delete-orphan")
    parent_attempt = relationship("Attempt", remote_side=[id], foreign_keys=[parent_attempt_id])


class Grade(Base):
    """Grade model for attempt evaluation."""
    __tablename__ = "grades"
    
    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), unique=True, nullable=False)
    
    # Scores
    score_0_5 = Column(Integer, nullable=False)  # 0-5 score (stored as 0-50 for precision if needed)
    pass_state = Column(Enum(PassState, native_enum=False), nullable=False)
    
    # Rubric evaluation
    rubric_hits = Column(JSON, default=dict)  # {"must_have": ["budget", "timeline"], "good_to_have": ["roi"]}
    missed_concepts = Column(JSON, default=list)  # ["decision_maker", "pain_points"]
    
    # Feedback
    feedback = Column(Text, nullable=True)  # Concise 1-3 bullet feedback
    
    # Grader trace (for debugging/audit)
    grader_trace = Column(JSON, nullable=True)  # Full evaluation trace from LLM
    
    # Grading method
    grading_method = Column(String(50), default="hybrid")  # "keyword_only", "llm_only", "hybrid"
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    attempt = relationship("Attempt", back_populates="grade")


class FrameworkScore(Base):
    """Framework evaluation scores (SPIN + Challenger)."""
    __tablename__ = "framework_scores"
    
    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), unique=True, nullable=False)
    
    # SPIN evaluation (0-4, one point per component)
    spin_score = Column(Integer, nullable=True)
    spin_breakdown = Column(JSON, nullable=True)  # {"situation": 1, "problem": 1, "implication": 0, "need_payoff": 1}
    spin_tips = Column(Text, nullable=True)  # Coaching tips for SPIN
    
    # Challenger evaluation (0-3)
    challenger_score = Column(Integer, nullable=True)
    challenger_breakdown = Column(JSON, nullable=True)  # {"teach": 1, "tailor": 1, "take_control": 0}
    challenger_tips = Column(Text, nullable=True)  # Coaching tips for Challenger
    
    # Total bonus score (optional combined)
    bonus_score = Column(Integer, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    attempt = relationship("Attempt", back_populates="framework_score")
