"""
Thin bridge so the Flask dashboard thread can access the live PTB application.
Set once at startup in bot.py, then read from any Flask route.
"""
import logging
import os
import requests

logger = logging.getLogger(__name__)

_application = None   # set by bot.py


def set_application(app) -> None:
    global _application
    _application = app


def get_application():
    return _application


# ─────────────────────────────────────────────────────────────────────────────
# Telegram HTTP helpers (no asyncio needed from Flask thread)
# ─────────────────────────────────────────────────────────────────────────────

def get_bot_username() -> str:
    """Get bot username from Telegram API (for invite links)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return ""
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=5,
        )
        if r.ok:
            data = r.json()
            return data.get("result", {}).get("username", "")
    except Exception:
        pass
    return ""


def send_telegram_message(chat_id: str, text: str, parse_mode: str = "HTML"):
    """Send a message via the Telegram Bot API using plain HTTP (requests).
    Returns (True, None) on success, or (False, error_description) on failure.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set — cannot send message")
        return False, "TELEGRAM_BOT_TOKEN no configurado"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if r.ok:
            return True, None
        data = r.json() if r.text else {}
        desc = data.get("description", r.text or f"HTTP {r.status_code}")
        logger.error(f"Telegram API error: {desc}")
        return False, desc
    except Exception as exc:
        logger.error(f"Error sending Telegram message: {exc}")
        return False, str(exc)


def arm_bot_state(chat_id: str, question_id: int, session_id: int) -> None:
    """
    Write session state into bot_data so the PTB message handler knows
    which question is awaiting an answer when the user next replies.
    bot_data is a plain dict shared across threads — safe for simple key writes.
    """
    app = _application
    if app is None:
        return
    key = str(chat_id)
    app.bot_data.setdefault(key, {})
    app.bot_data[key]["last_question_id"]   = question_id
    app.bot_data[key]["session_id"]         = session_id
    app.bot_data[key]["awaiting_answer"]    = True
    app.bot_data[key]["grading_in_progress"] = False
