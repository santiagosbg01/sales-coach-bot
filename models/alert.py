"""Alert model for manager notifications."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, JSON, Enum, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from .base import Base


class AlertType(enum.Enum):
    """Alert type enumeration."""
    LOW_ENGAGEMENT = "low_engagement"
    LOW_ACCURACY = "low_accuracy"
    MISSED_DAYS = "missed_days"
    KNOWLEDGE_GAP = "knowledge_gap"


class AlertSeverity(enum.Enum):
    """Alert severity enumeration."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert(Base):
    """Alert model for tracking user issues."""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(Enum(AlertType), nullable=False, index=True)
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.WARNING, nullable=False)
    
    # Alert details
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    context = Column(JSON, nullable=True)  # Additional context data
    
    # Status
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, nullable=True)  # user_id of resolver
    
    # Timestamps
    triggered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="alerts")
