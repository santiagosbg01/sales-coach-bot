"""Configuration management for Sales Coach Bot."""
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""

    # Product / branding — override in .env to customize your deployment
    APP_NAME: str = os.getenv("APP_NAME", "Sales Coach")
    COMPANY_NAME: str = os.getenv("COMPANY_NAME", "Your Company")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    # Bot username for invite links (e.g. YourBotName) — optional
    TELEGRAM_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "")
    # Single shared invite code for enrollment (same link for everyone; admin approves each user)
    ENROLL_CODE: str = os.getenv("ENROLL_CODE", "enroll")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_GRADING_MODEL: str = os.getenv("OPENAI_GRADING_MODEL", "gpt-4o-mini")
    OPENAI_WHISPER_MODEL: str = os.getenv("OPENAI_WHISPER_MODEL", "whisper-1")

    # Anthropic (kept as fallback)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///sales_coach.db")
    
    # Dashboard
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-secret-key")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
    DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "5000"))
    # Base URL for redemption links (e.g. https://your-app.railway.app or http://localhost:5000)
    # Railway sets RAILWAY_PUBLIC_DOMAIN automatically — use it as a smart fallback.
    _railway_domain: str = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    BASE_URL: str = os.getenv(
        "BASE_URL",
        os.getenv(
            "DASHBOARD_URL",
            f"https://{_railway_domain}" if _railway_domain else "http://localhost:5000",
        ),
    )
    
    # Bot behavior
    DAILY_QUESTIONS_COUNT: int = int(os.getenv("DAILY_QUESTIONS_COUNT", "5"))
    # Max questions per day (base + extra via /mas); extra questions award extra credits
    DAILY_QUESTIONS_MAX: int = int(os.getenv("DAILY_QUESTIONS_MAX", "10"))
    MAX_PROBES_PER_QUESTION: int = int(os.getenv("MAX_PROBES_PER_QUESTION", "3"))
    ANTI_REPEAT_DAYS: int = int(os.getenv("ANTI_REPEAT_DAYS", "7"))
    REMINDER_HOURS: int = int(os.getenv("REMINDER_HOURS", "4"))

    # Spaced repetition (wrong answers re-sent at stage intervals)
    # SR_REVIEW_INTERVALS: comma-separated days for stage 1, 2, 3 (e.g. "3,7,14")
    SR_REVIEW_INTERVALS: str = os.getenv("SR_REVIEW_INTERVALS", "3,7,14")
    SR_MAX_REVIEWS_PER_DAY: int = int(os.getenv("SR_MAX_REVIEWS_PER_DAY", "2"))

    # Admin Telegram chat IDs (comma-separated): receives feedback, redemption alerts, weekly digest.
    # Configure this in your .env once you know your admin's Telegram chat_id (send /start to your bot to see it).
    MANAGER_ALERT_CHAT_IDS: str = os.getenv("MANAGER_ALERT_CHAT_IDS", os.getenv("ADMIN_CHAT_ID", ""))
    # Days without answering before rep + manager get inactivity Telegram alerts (weekdays 9am local)
    INACTIVITY_ALERT_DAYS: int = int(os.getenv("INACTIVITY_ALERT_DAYS", "3"))
    # Legacy: used only if scripts/dashboard still call AlertSystem (low engagement, etc.)
    MANAGER_ALERT_ACCURACY_THRESHOLD: float = float(os.getenv("MANAGER_ALERT_ACCURACY_THRESHOLD", "2.5"))

    # ── Weekly report email (Friday 10am CST — job in proactive_sender) ──
    # Preferred: use Resend (HTTPS, works from most hosts). Alternative: SMTP.
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USE_SSL: bool = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
    # Prevents the dashboard from hanging if the SMTP port is blocked (some hosts).
    SMTP_TIMEOUT: int = int(os.getenv("SMTP_TIMEOUT", "25"))
    # Email sender address for weekly report — must be a verified sender in your email provider.
    WEEKLY_REPORT_EMAIL_FROM: str = os.getenv("WEEKLY_REPORT_EMAIL_FROM", "")
    # Comma-separated recipient list. Empty = report is generated but not emailed.
    WEEKLY_REPORT_EMAIL_RECIPIENTS: str = os.getenv("WEEKLY_REPORT_EMAIL_RECIPIENTS", "")
    WEEKLY_REPORT_EMAIL_ENABLED: bool = os.getenv("WEEKLY_REPORT_EMAIL_ENABLED", "true").lower() == "true"

    # Transactional email vía HTTPS (Resend). Si está presente, tiene prioridad sobre SMTP.
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")

    @classmethod
    def get_sr_intervals(cls) -> dict:
        """Parse SR_REVIEW_INTERVALS into {1: days, 2: days, 3: days}."""
        parts = [p.strip() for p in cls.SR_REVIEW_INTERVALS.split(",") if p.strip()]
        if len(parts) >= 3:
            return {1: int(parts[0]), 2: int(parts[1]), 3: int(parts[2])}
        return {1: 3, 2: 7, 3: 14}
    
    # Difficulty progression (adapt question difficulty to user skill)
    # Disabled by default so leaderboard is apples-to-apples (same difficulty for all)
    ENABLE_DIFFICULTY_PROGRESSION: bool = os.getenv("ENABLE_DIFFICULTY_PROGRESSION", "false").lower() == "true"
    DIFFICULTY_LOOKBACK_DAYS: int = int(os.getenv("DIFFICULTY_LOOKBACK_DAYS", "14"))

    # Scoring
    ENABLE_SPIN_EVALUATION: bool = os.getenv("ENABLE_SPIN_EVALUATION", "true").lower() == "true"
    ENABLE_CHALLENGER_EVALUATION: bool = os.getenv("ENABLE_CHALLENGER_EVALUATION", "true").lower() == "true"
    SHOW_BONUS_SCORES_TO_REPS: bool = os.getenv("SHOW_BONUS_SCORES_TO_REPS", "false").lower() == "true"
    
    # Environment
    ENV: str = os.getenv("ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    
    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration."""
        required = [
            ("TELEGRAM_BOT_TOKEN", cls.TELEGRAM_BOT_TOKEN),
            ("OPENAI_API_KEY", cls.OPENAI_API_KEY),
        ]
        
        missing = [name for name, value in required if not value]
        
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        
        return True


# Validate on import
try:
    Config.validate()
except ValueError as e:
    if Config.ENV != "test":
        print(f"⚠️  Configuration warning: {e}")
