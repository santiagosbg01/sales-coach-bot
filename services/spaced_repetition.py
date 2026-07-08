"""
Spaced Repetition Service.

When a rep answers a question incorrectly:
  - Schedule it for review (stage 1, days from Config.SR_REVIEW_INTERVALS).

When the review question is answered:
  - Correct at stage N → advance to next stage or graduate
  - Wrong at any stage → reset to stage 1

Intervals and max reviews per day are configurable via .env:
  SR_REVIEW_INTERVALS=3,7,14  (days for stage 1, 2, 3)
  SR_MAX_REVIEWS_PER_DAY=2
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session as DBSession

from config import Config
from models import SpacedRepetitionQueue, MAX_STAGE

logger = logging.getLogger(__name__)


class SpacedRepetitionService:

    def __init__(self, db: DBSession):
        self.db = db

    # ------------------------------------------------------------------ #
    # Called after grading                                                 #
    # ------------------------------------------------------------------ #

    def record_result(
        self,
        user_id: int,
        question_id: int,
        is_correct: bool,
        attempt_id: Optional[int] = None,
    ) -> None:
        """
        Call this after every graded answer.
        - Wrong answer on a *regular* question → create stage-1 review entry.
        - Any answer on a *review* question → advance or reset the entry.
        """
        existing = self._get_active_entry(user_id, question_id)

        if existing:
            self._update_review(existing, is_correct)
        elif not is_correct:
            self._create_entry(user_id, question_id, stage=1, attempt_id=attempt_id)

    # ------------------------------------------------------------------ #
    # Called by session engine                                            #
    # ------------------------------------------------------------------ #

    def get_due_question_ids(
        self, user_id: int, limit: Optional[int] = None
    ) -> List[int]:
        """
        Return up to `limit` question IDs that are due for review today (UTC).
        Ordered by stage descending (highest urgency first).
        """
        limit = limit if limit is not None else Config.SR_MAX_REVIEWS_PER_DAY
        today_end = datetime.utcnow().replace(hour=23, minute=59, second=59)
        rows = (
            self.db.query(SpacedRepetitionQueue)
            .filter(
                SpacedRepetitionQueue.user_id == user_id,
                SpacedRepetitionQueue.is_active == True,
                SpacedRepetitionQueue.due_date <= today_end,
            )
            .order_by(SpacedRepetitionQueue.stage.desc())
            .limit(limit)
            .all()
        )
        return [r.question_id for r in rows]

    def is_review_question(self, user_id: int, question_id: int) -> bool:
        """True if this question is an active review for this user."""
        return self._get_active_entry(user_id, question_id) is not None

    def get_review_stage(self, user_id: int, question_id: int) -> Optional[int]:
        """Return the current review stage (1-3) or None if not a review."""
        entry = self._get_active_entry(user_id, question_id)
        return entry.stage if entry else None

    def record_skip_on_review(self, user_id: int, question_id: int) -> bool:
        """
        Call when user skips a review question.
        Postpones due_date by 1 day so they don't see it again in the next session
        (avoids same question every session when repeatedly skipping).
        Returns True if it was a review question and was postponed.
        """
        entry = self._get_active_entry(user_id, question_id)
        if not entry:
            return False
        entry.due_date = datetime.utcnow() + timedelta(days=1)
        self.db.commit()
        logger.info(
            f"⏭️ Spaced repetition postponed (skip): user={user_id} q={question_id} "
            f"→ due={entry.due_date.date()}"
        )
        return True

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_active_entry(self, user_id: int, question_id: int):
        return (
            self.db.query(SpacedRepetitionQueue)
            .filter(
                SpacedRepetitionQueue.user_id    == user_id,
                SpacedRepetitionQueue.question_id == question_id,
                SpacedRepetitionQueue.is_active   == True,
            )
            .first()
        )

    def _create_entry(
        self,
        user_id: int,
        question_id: int,
        stage: int,
        attempt_id: Optional[int] = None,
    ) -> SpacedRepetitionQueue:
        # Guard: avoid duplicate active entries (e.g. race or double-submit)
        existing = self._get_active_entry(user_id, question_id)
        if existing:
            return existing
        intervals = Config.get_sr_intervals()
        due = datetime.utcnow() + timedelta(days=intervals.get(stage, 3))
        entry = SpacedRepetitionQueue(
            user_id=user_id,
            question_id=question_id,
            stage=stage,
            due_date=due,
            is_active=True,
            original_attempt_id=attempt_id,
        )
        self.db.add(entry)
        self.db.commit()
        logger.info(
            f"📅 Spaced repetition scheduled: user={user_id} q={question_id} "
            f"stage={stage} due={due.date()}"
        )
        return entry

    def _update_review(self, entry: SpacedRepetitionQueue, is_correct: bool) -> None:
        if is_correct:
            if entry.stage >= MAX_STAGE:
                # Graduated — no more reviews needed
                entry.is_active    = False
                entry.completed_at = datetime.utcnow()
                logger.info(
                    f"🎓 Spaced repetition GRADUATED: user={entry.user_id} q={entry.question_id}"
                )
            else:
                # Advance to next stage
                next_stage = entry.stage + 1
                intervals = Config.get_sr_intervals()
                entry.stage = next_stage
                entry.due_date = datetime.utcnow() + timedelta(
                    days=intervals.get(next_stage, 7)
                )
                logger.info(
                    f"⬆️  Spaced repetition advanced: user={entry.user_id} q={entry.question_id} "
                    f"→ stage={next_stage} due={entry.due_date.date()}"
                )
        else:
            # Wrong again — reset to stage 1
            intervals = Config.get_sr_intervals()
            entry.stage = 1
            entry.due_date = datetime.utcnow() + timedelta(days=intervals.get(1, 3))
            logger.info(
                f"🔄 Spaced repetition reset: user={entry.user_id} q={entry.question_id} "
                f"→ stage=1 due={entry.due_date.date()}"
            )
        self.db.commit()
