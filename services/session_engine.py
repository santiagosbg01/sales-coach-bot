"""Session engine for managing daily training sessions."""
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from config import Config
from models import (
    Session as SessionModel, User, Question, Attempt,
    SessionStatus, QuestionCategory
)
import random


class SessionEngine:
    """Manages daily training sessions."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_daily_session(self, user_id: int, date: Optional[datetime] = None) -> Optional[SessionModel]:
        """
        Create a new daily session for a user.
        Always respects the daily cap (DAILY_QUESTIONS_MAX): if the user already
        answered questions today (in a previous session), only allocates enough
        questions to reach the cap — never exceeding it.

        Returns None if the user has already hit the daily cap.
        """
        if date is None:
            date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Return existing session for today if one exists
        existing = self.db.query(SessionModel).filter(
            and_(
                SessionModel.user_id == user_id,
                SessionModel.date == date
            )
        ).first()
        if existing:
            return existing

        # How many questions has this user already answered today (across all sessions)?
        count_today = self.count_today_attempts(user_id, date)
        remaining = Config.DAILY_QUESTIONS_MAX - count_today
        if remaining <= 0:
            # Already at or past the daily cap — don't create a new session
            return None

        # Cap new session size: never exceed what's needed to hit the daily max
        num_questions = min(Config.DAILY_QUESTIONS_COUNT, remaining)
        question_ids = self._select_questions_for_session(user_id, num_questions=num_questions)

        session = SessionModel(
            user_id=user_id,
            date=date,
            status=SessionStatus.PENDING,
            question_ids=question_ids,
            total_questions=len(question_ids),
            current_question_index=0
        )

        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return session
    
    def _select_questions_for_session(
        self, user_id: int, num_questions: Optional[int] = None
    ) -> List[int]:
        """
        Select questions for a session using anti-repeat logic.
        num_questions overrides Config.DAILY_QUESTIONS_COUNT when provided.
        """
        num_questions = num_questions or Config.DAILY_QUESTIONS_COUNT
        anti_repeat_days = Config.ANTI_REPEAT_DAYS
        
        # Get recently asked questions
        cutoff_date = datetime.utcnow() - timedelta(days=anti_repeat_days)
        recent_attempts = self.db.query(Attempt.question_id).filter(
            and_(
                Attempt.user_id == user_id,
                Attempt.asked_at >= cutoff_date
            )
        ).all()
        recent_question_ids = [a.question_id for a in recent_attempts]
        
        # Get questions user struggled with (for spaced repetition)
        struggling_questions = self._get_struggling_questions(user_id)
        
        # Build profile-based filters for this user
        profile_filters = self._profile_filters(user_id)

        # Get active questions not recently asked, filtered by user profile
        base_q = self.db.query(Question).filter(
            and_(
                Question.active == True,
                *profile_filters,
                ~Question.id.in_(recent_question_ids) if recent_question_ids else True,
            )
        )
        available_questions = base_q.all()

        if not available_questions:
            # Relax anti-repeat constraint but keep profile filter
            available_questions = self.db.query(Question).filter(
                and_(Question.active == True, *profile_filters)
            ).all()

        if not available_questions:
            # Last resort: ignore profile filter entirely
            available_questions = self.db.query(Question).filter(
                Question.active == True
            ).all()
        
        # Inject spaced-repetition review questions first (highest priority)
        from services.spaced_repetition import SpacedRepetitionService
        sr_service = SpacedRepetitionService(self.db)
        due_review_ids = sr_service.get_due_question_ids(user_id)

        selected = []
        for q_id in due_review_ids:
            if len(selected) < num_questions:
                selected.append(q_id)
                # Remove from available pool to avoid duplication
                available_questions = [q for q in available_questions if q.id != q_id]

        # Fill remaining slots — skip the old "struggling" logic (SR handles it now)
        struggle_count = 0

        # Fill remaining slots with a balanced mix of question types (and difficulty when enabled)
        remaining = num_questions - len(selected)

        if remaining > 0 and available_questions:
            type_keys = ["multiple_choice", "yes_no", "open_ended"]

            if Config.ENABLE_DIFFICULTY_PROGRESSION:
                from services.difficulty_progression import (
                    get_user_difficulty_tier,
                    get_difficulty_mix,
                    distribute_by_difficulty,
                )
                tier = get_user_difficulty_tier(
                    self.db, user_id,
                    lookback_days=Config.DIFFICULTY_LOOKBACK_DAYS,
                )
                er, mr, hr = get_difficulty_mix(tier)
                by_type_diff: Dict[tuple, List[int]] = {}
                for q in available_questions:
                    qt = (q.question_type.value if q.question_type else "open_ended")
                    qd = (q.difficulty.value if q.difficulty else "medium")
                    by_type_diff.setdefault((qt, qd), []).append(q.id)
                for bucket in by_type_diff.values():
                    random.shuffle(bucket)

                # Type mix: equal thirds; cap by available
                base, extra = divmod(remaining, len(type_keys))
                type_counts = {k: base + (1 if i < extra else 0) for i, k in enumerate(type_keys)}
                for k in type_keys:
                    avail = sum(len(by_type_diff.get((k, d), [])) for d in ["easy", "medium", "hard"])
                    if avail < type_counts[k]:
                        type_counts[k] = avail
                shortfall = remaining - sum(type_counts.values())
                for k in type_keys:
                    if shortfall <= 0:
                        break
                    avail = sum(len(by_type_diff.get((k, d), [])) for d in ["easy", "medium", "hard"])
                    spare = avail - type_counts[k]
                    add = min(spare, shortfall)
                    type_counts[k] += add
                    shortfall -= add

                # Build (type, diff) wish list; then fill from pools (with fallback within same type)
                taken_ids = set()
                diff_order = ["easy", "medium", "hard"]
                for k in type_keys:
                    tc = type_counts[k]
                    if tc <= 0:
                        continue
                    diff_counts = distribute_by_difficulty(tc, er, mr, hr)
                    need = tc
                    for d in diff_order:
                        want = diff_counts.get(d, 0)
                        if want <= 0:
                            continue
                        pool = [x for x in by_type_diff.get((k, d), []) if x not in taken_ids]
                        take = min(want, len(pool))
                        for qid in pool[:take]:
                            selected.append(qid)
                            taken_ids.add(qid)
                            need -= 1
                    # Fill any remaining for this type from any difficulty
                    if need > 0:
                        for d in diff_order:
                            if need <= 0:
                                break
                            pool = [x for x in by_type_diff.get((k, d), []) if x not in taken_ids]
                            take = min(need, len(pool))
                            for qid in pool[:take]:
                                selected.append(qid)
                                taken_ids.add(qid)
                                need -= 1
            else:
                # Original logic: type mix only, no difficulty
                by_type: Dict[str, List[int]] = {}
                for q in available_questions:
                    qt = (q.question_type.value if q.question_type else "open_ended")
                    by_type.setdefault(qt, []).append(q.id)
                for bucket in by_type.values():
                    random.shuffle(bucket)
                base, extra = divmod(remaining, len(type_keys))
                type_counts = {k: base + (1 if i < extra else 0) for i, k in enumerate(type_keys)}
                shortfall = 0
                for k in type_keys:
                    available_count = len(by_type.get(k, []))
                    if available_count < type_counts[k]:
                        shortfall += type_counts[k] - available_count
                        type_counts[k] = available_count
                for k in type_keys:
                    if shortfall <= 0:
                        break
                    spare = len(by_type.get(k, [])) - type_counts[k]
                    add = min(spare, shortfall)
                    type_counts[k] += add
                    shortfall -= add
                for k in type_keys:
                    pool = by_type.get(k, [])
                    selected.extend(pool[:type_counts[k]])
        
        # Shuffle to avoid patterns
        random.shuffle(selected)
        
        return selected[:num_questions]
    
    def _profile_filters(self, user_id: int) -> list:
        """
        Build SQLAlchemy filter clauses based on the user's sales profile.
        - country: include questions for user's country OR "all"
        - specializations: include questions for user's services OR "general"
        Returns an empty list if no profile is set (no filtering applied).
        """
        from sqlalchemy import or_
        user = self.db.query(User).get(user_id)
        if not user:
            return []

        filters = []

        # Country filter
        if user.base_country:
            filters.append(
                or_(
                    Question.country == user.base_country,
                    Question.country == "all",
                    Question.country == None,
                )
            )

        # Specialization filter
        specs = user.specializations or []
        if specs:
            filters.append(
                or_(
                    Question.product.in_(specs),
                    Question.product == "general",
                    Question.product == None,
                )
            )

        return filters

    def _get_struggling_questions(self, user_id: int, lookback_days: int = 14) -> List[int]:
        """Get questions user has struggled with recently."""
        from models import Grade, PassState
        
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
        
        struggling = self.db.query(Attempt.question_id).join(Grade).filter(
            and_(
                Attempt.user_id == user_id,
                Attempt.asked_at >= cutoff_date,
                Grade.pass_state.in_([PassState.FAIL, PassState.BORDERLINE])
            )
        ).group_by(Attempt.question_id).all()
        
        return [q_id for (q_id,) in struggling]
    
    def start_session(self, session_id: int) -> bool:
        """Start a session."""
        session = self.db.query(SessionModel).get(session_id)
        if not session:
            return False
        
        session.status = SessionStatus.IN_PROGRESS
        session.started_at = datetime.utcnow()
        self.db.commit()
        
        return True
    
    def pause_session(self, session_id: int) -> bool:
        """Pause a session."""
        session = self.db.query(SessionModel).get(session_id)
        if not session:
            return False
        
        session.status = SessionStatus.PAUSED
        self.db.commit()
        
        return True
    
    def resume_session(self, session_id: int) -> bool:
        """Resume a paused session."""
        session = self.db.query(SessionModel).get(session_id)
        if not session or session.status != SessionStatus.PAUSED:
            return False
        
        session.status = SessionStatus.IN_PROGRESS
        self.db.commit()
        
        return True
    
    def complete_session(self, session_id: int) -> bool:
        """Mark session as completed and compute summary stats."""
        session = self.db.query(SessionModel).get(session_id)
        if not session:
            return False
        
        # Get all attempts for this session
        attempts = self.db.query(Attempt).filter(
            Attempt.session_id == session_id
        ).all()
        
        from models import Grade
        
        answered = len([a for a in attempts if not a.is_skipped])
        skipped = len([a for a in attempts if a.is_skipped])
        
        # Calculate average score
        scores = []
        for attempt in attempts:
            if not attempt.is_skipped and attempt.grade:
                scores.append(attempt.grade.score_0_5)
        
        avg_score = sum(scores) / len(scores) if scores else None
        
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.utcnow()
        session.answered_questions = answered
        session.skipped_questions = skipped
        session.avg_score = int(avg_score * 100) if avg_score else None
        
        # Update user's last_active_at
        user = self.db.query(User).get(session.user_id)
        if user:
            user.last_active_at = datetime.utcnow()
        
        self.db.commit()
        
        return True
    
    def get_active_session(self, user_id: int) -> Optional[SessionModel]:
        """Get user's active session."""
        return self.db.query(SessionModel).filter(
            and_(
                SessionModel.user_id == user_id,
                SessionModel.status.in_([SessionStatus.PENDING, SessionStatus.IN_PROGRESS, SessionStatus.PAUSED])
            )
        ).order_by(desc(SessionModel.created_at)).first()

    def _today_start(self, date: Optional[datetime] = None) -> datetime:
        """UTC date at midnight for today or given date."""
        if date is None:
            date = datetime.utcnow()
        return date.replace(hour=0, minute=0, second=0, microsecond=0)

    def count_today_attempts(self, user_id: int, date: Optional[datetime] = None) -> int:
        """Count non-skipped attempts for this user on the given day (default today UTC)."""
        today = self._today_start(date)
        return self.db.query(Attempt).join(SessionModel).filter(
            and_(
                SessionModel.user_id == user_id,
                SessionModel.date == today,
                Attempt.is_skipped == False,
            )
        ).count()

    def get_today_session(self, user_id: int, date: Optional[datetime] = None) -> Optional[SessionModel]:
        """Get the session for this user for the given day (default today UTC), if any."""
        today = self._today_start(date)
        return self.db.query(SessionModel).filter(
            and_(
                SessionModel.user_id == user_id,
                SessionModel.date == today,
            )
        ).order_by(desc(SessionModel.created_at)).first()

    def add_extra_questions(self, user_id: int, date: Optional[datetime] = None) -> tuple[Optional[SessionModel], int]:
        """
        Add extra questions to today's session (for /mas). User must have completed the base set.
        Returns (session, num_added). If no session or at cap, returns (None, 0).
        """
        today = self._today_start(date)
        count = self.count_today_attempts(user_id, date)
        if count >= Config.DAILY_QUESTIONS_MAX:
            return None, 0
        session = self.get_today_session(user_id, date)
        if not session or session.status != SessionStatus.COMPLETED:
            return None, 0
        to_add = min(Config.DAILY_QUESTIONS_MAX - count, 5)
        if to_add <= 0:
            return None, 0
        extra_ids = self._select_questions_for_session(user_id, num_questions=to_add)
        if not extra_ids:
            return None, 0
        existing_ids = list(session.question_ids or [])
        session.question_ids = existing_ids + extra_ids
        session.total_questions = len(session.question_ids)
        session.current_question_index = len(existing_ids)
        session.status = SessionStatus.IN_PROGRESS
        session.completed_at = None
        self.db.commit()
        self.db.refresh(session)
        return session, len(extra_ids)

    def get_current_question(self, session) -> Optional[Question]:
        """Return the current question in a session, or None if done."""
        if session.current_question_index >= len(session.question_ids or []):
            return None
        question_id = session.question_ids[session.current_question_index]
        return self.db.query(Question).get(question_id)

    def advance_to_next_question(self, session_id: int) -> bool:
        """Move to next question in session."""
        session = self.db.query(SessionModel).get(session_id)
        if not session:
            return False
        
        session.current_question_index += 1
        
        # Check if session is complete
        if session.current_question_index >= len(session.question_ids):
            self.complete_session(session_id)
        
        self.db.commit()
        
        return True
