"""Question and rubric models."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean, JSON, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator, VARCHAR
from datetime import datetime
import enum
from .base import Base


class DifficultyLevel(enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuestionCategory(enum.Enum):
    DISCOVERY = "discovery"
    OBJECTIONS = "objections"
    QUALIFICATION = "qualification"
    CLOSING = "closing"
    VALUE_PROPOSITION = "value_proposition"
    GENERAL = "general"


class QuestionType(enum.Enum):
    OPEN_ENDED = "open_ended"        # Free text → graded by OpenAI
    MULTIPLE_CHOICE = "multiple_choice"  # Options A/B/C/D → exact match
    YES_NO = "yes_no"                # Sí / No → exact match


class QuestionTypeColumn(TypeDecorator):
    """Stores QuestionType by enum name (OPEN_ENDED) for PG enum compatibility; accepts both name and value on load."""
    impl = VARCHAR(20)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, QuestionType):
            return value.name
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        s = (value or "").strip().upper()
        for member in QuestionType:
            if member.name == s or member.value.upper() == s:
                return member
        return QuestionType.OPEN_ENDED


class Question(Base):
    """Question model."""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    prompt = Column(Text, nullable=False)
    category = Column(Enum(QuestionCategory, native_enum=False), nullable=False, index=True)
    difficulty = Column(Enum(DifficultyLevel, native_enum=False), default=DifficultyLevel.MEDIUM, nullable=False)
    tags = Column(JSON, default=list)

    # Explicit classification fields
    product = Column(String(50), nullable=True, index=True)   # product/service tag matching VALID_SERVICES (see models/user.py)
    country = Column(String(50), nullable=True, index=True)   # "mexico", "colombia", "chile", "peru", "all"

    question_type = Column(
        QuestionTypeColumn(),
        default=QuestionType.OPEN_ENDED,
        nullable=False,
    )
    # For multiple_choice: [{"key": "A", "text": "..."}, {"key": "B", "text": "..."}, ...]
    choices = Column(JSON, nullable=True)
    # For multiple_choice: "A" / "B" / ... ; for yes_no: "si" / "no" ; can be longer (e.g. guide text)
    correct_answer = Column(String(200), nullable=True)

    # Status
    active = Column(Boolean, default=True, nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, nullable=True)

    # Relationships
    rubric = relationship("Rubric", back_populates="question", uselist=False, cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="question")


class Rubric(Base):
    """Rubric model for question grading criteria."""
    __tablename__ = "rubrics"
    
    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), unique=True, nullable=False)
    
    # Core grading criteria
    must_have_concepts = Column(JSON, default=list)  # [{"concept": "budget", "synonyms": ["cost", "price"]}, ...]
    good_to_have_concepts = Column(JSON, default=list)  # Same structure as must_have
    
    # Scoring weights (optional customization)
    must_have_weight = Column(Integer, default=70)  # % of total score
    good_to_have_weight = Column(Integer, default=20)
    llm_adjustment_weight = Column(Integer, default=10)
    
    # Reference materials
    reference_url = Column(String(512), nullable=True)
    reference_snippet = Column(Text, nullable=True)
    ideal_answer = Column(Text, nullable=True)
    
    # Follow-up templates for probing
    followup_templates = Column(JSON, default=list)  # ["Can you elaborate on {concept}?", ...]
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    question = relationship("Question", back_populates="rubric")
