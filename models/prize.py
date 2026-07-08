"""Prize and Redemption models for point redemption."""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from .base import Base


class Prize(Base):
    """Prize that can be redeemed for points."""
    __tablename__ = "prizes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    points_cost = Column(Integer, nullable=False)
    quantity_available = Column(Integer, nullable=True)  # None = unlimited
    active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    redemptions = relationship("Redemption", back_populates="prize")

    @property
    def is_available(self) -> bool:
        """True if prize can still be redeemed."""
        if not self.active:
            return False
        if self.quantity_available is None:
            return True
        return self.quantity_available > 0


class Redemption(Base):
    """Record of a user redeeming points for a prize."""
    __tablename__ = "redemptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    prize_id = Column(Integer, ForeignKey("prizes.id"), nullable=False)
    points_spent = Column(Integer, nullable=False)
    redeemed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="redemptions")
    prize = relationship("Prize", back_populates="redemptions")
