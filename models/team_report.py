"""Persisted weekly team performance reports (dashboard + scheduled job)."""
from sqlalchemy import Column, Integer, DateTime, JSON
from datetime import datetime

from .base import Base


class TeamReportSnapshot(Base):
    """
    One row per generated report window (typically Mon–Sun CST, saved Friday).
    `payload` holds the full structured JSON for the UI.
    """

    __tablename__ = "team_report_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    period_start_utc = Column(DateTime, nullable=False, index=True)
    period_end_utc = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    payload = Column(JSON, nullable=False)
