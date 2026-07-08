"""Streaks & gamification service."""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import User


def _utc_day_start(dt: datetime) -> datetime:
    """Normalize datetime to UTC day start (naive UTC)."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


class GamificationService:
    """
    Awards points and maintains daily streaks.

    Rules:
    - A "day" counts if the user answers at least one non-skipped question that day.
    - First qualifying answer of the day updates streak.
    - Points: 1 per answered question, +5 if correct (score_0_5 >= 3).
    """

    def __init__(self, db: Session):
        self.db = db

    def record_answer(self, user_id: int, answered_at: datetime, score_0_5: int) -> dict:
        user = self.db.query(User).get(user_id)
        if not user:
            return {"updated": False}

        today = _utc_day_start(answered_at or datetime.utcnow())
        yesterday = today - timedelta(days=1)

        streak_updated = False
        if not user.streak_last_date or _utc_day_start(user.streak_last_date) != today:
            # New streak day
            if user.streak_last_date and _utc_day_start(user.streak_last_date) == yesterday:
                user.streak_current = int(user.streak_current or 0) + 1
            else:
                user.streak_current = 1
            user.streak_best = max(int(user.streak_best or 0), int(user.streak_current or 0))
            user.streak_last_date = today
            streak_updated = True

        is_correct = (score_0_5 or 0) >= 3
        awarded = 1 + (5 if is_correct else 0)

        user.points = int(user.points or 0) + awarded
        user.last_active_at = answered_at or datetime.utcnow()

        # Check streak milestones for notifications (4-day, 5-day)
        notify_streak = None
        if streak_updated and user.streak_current == 4 and not getattr(user, "streak_notified_4_at", None):
            user.streak_notified_4_at = datetime.utcnow()
            notify_streak = 4
        elif streak_updated and user.streak_current == 5 and not getattr(user, "streak_notified_5_at", None):
            user.streak_notified_5_at = datetime.utcnow()
            notify_streak = 5

        self.db.commit()

        return {
            "updated": True,
            "streak_updated": streak_updated,
            "points_awarded": awarded,
            "points_total": user.points,
            "streak_current": user.streak_current,
            "streak_best": user.streak_best,
            "notify_streak": notify_streak,
        }

