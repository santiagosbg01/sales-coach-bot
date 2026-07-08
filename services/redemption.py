"""Point redemption service."""
from typing import Tuple
from sqlalchemy.orm import Session
from models import User, Prize, Redemption


def ensure_redeem_token(db: Session, user_id: int) -> str:
    """Ensure user has a redeem token; generate if missing. Returns token."""
    import secrets
    user = db.query(User).get(user_id)
    if not user:
        return ""
    if user.redeem_token:
        return user.redeem_token
    token = secrets.token_urlsafe(32)
    user.redeem_token = token
    db.commit()
    return token


def redeem_prize(db: Session, user_id: int, prize_id: int) -> Tuple[bool, str]:
    """
    Redeem a prize for a user. Returns (success, message).
    Deducts points, creates redemption record, decrements prize quantity if limited.
    """
    user = db.query(User).get(user_id)
    prize = db.query(Prize).get(prize_id)
    if not user:
        return False, "Usuario no encontrado."
    if not prize:
        return False, "Premio no encontrado."
    if not prize.active:
        return False, "Este premio ya no está disponible."
    if prize.quantity_available is not None and prize.quantity_available <= 0:
        return False, "Este premio ya no tiene stock."
    points = int(user.points or 0)
    if points < prize.points_cost:
        return False, f"Necesitas {prize.points_cost} puntos. Tienes {points}."

    user.points = points - prize.points_cost
    if prize.quantity_available is not None:
        prize.quantity_available -= 1
    db.add(Redemption(user_id=user_id, prize_id=prize_id, points_spent=prize.points_cost))
    db.commit()
    return True, f"¡Canjeado! {prize.name} por {prize.points_cost} pts. Te quedan {user.points} puntos."
