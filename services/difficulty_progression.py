"""
Difficulty progression: adapts question difficulty to user skill level.
Computes user tier from recent performance and returns target difficulty mix.
"""
from datetime import datetime, timedelta
from typing import Dict, Tuple
from sqlalchemy.orm import Session

from models import Attempt


# Target (easy_pct, medium_pct, hard_pct) per tier
# Percentages are approximate; we round when distributing
TIER_MIX = {
    "beginner":   (0.70, 0.25, 0.05),   # Mostly easy, some medium
    "intermediate": (0.30, 0.50, 0.20),  # Balanced
    "advanced":   (0.20, 0.40, 0.40),   # More hard challenges
}


def get_user_difficulty_tier(db: Session, user_id: int, lookback_days: int = 14) -> str:
    """
    Compute user's difficulty tier from recent performance.
    Returns: "beginner" | "intermediate" | "advanced"
    """
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    attempts = (
        db.query(Attempt)
        .filter(
            Attempt.user_id == user_id,
            Attempt.asked_at >= cutoff,
            Attempt.is_skipped == False,
        )
        .all()
    )

    if len(attempts) < 10:
        return "beginner"

    correct = 0
    for a in attempts:
        if a.grade and a.grade.score_0_5 >= 3:
            correct += 1
    accuracy = correct / len(attempts)

    # Advanced: 80%+ accuracy over 20+ questions
    if len(attempts) >= 20 and accuracy >= 0.80:
        return "advanced"

    # Intermediate: 50%+ accuracy or 15+ questions
    if len(attempts) >= 15 or accuracy >= 0.50:
        return "intermediate"

    return "beginner"


def get_difficulty_mix(tier: str) -> Tuple[float, float, float]:
    """Return (easy_ratio, medium_ratio, hard_ratio) for the tier."""
    return TIER_MIX.get(tier, TIER_MIX["intermediate"])


def distribute_by_difficulty(
    total: int,
    easy_ratio: float,
    medium_ratio: float,
    hard_ratio: float,
) -> Dict[str, int]:
    """
    Distribute `total` slots across easy/medium/hard.
    Returns {"easy": n, "medium": n, "hard": n} that sum to total.
    """
    e = max(0, round(total * easy_ratio))
    m = max(0, round(total * medium_ratio))
    h = max(0, round(total * hard_ratio))
    s = e + m + h
    if s != total:
        diff = total - s
        if diff > 0:
            e = min(e + diff, total)
        elif diff < 0:
            e = max(0, e + diff)
        s = e + m + h
        if s != total:
            m += total - s
    return {"easy": e, "medium": m, "hard": h}
