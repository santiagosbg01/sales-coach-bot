"""
Muestra qué base de datos usa este entorno y cuántas preguntas tiene.
Úsalo en local y en Railway para comprobar que todos usan la misma DB.

  Local:    python3 scripts/check_db.py
  Railway: railway run python scripts/check_db.py
"""
import os
import sys

# Evitar validación de token en este script
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "check_db_script")
os.environ.setdefault("OPENAI_API_KEY", "check_db_script")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

url = os.getenv("DATABASE_URL", "sqlite:///sales_coach.db")
# Enmascarar contraseña
if "@" in url and ":" in url:
    try:
        pre, rest = url.split("@", 1)
        if ":" in pre:
            user, _ = pre.rsplit(":", 1)
            url_mask = user + ":****@" + rest
        else:
            url_mask = url
    except Exception:
        url_mask = url[:50] + "..." if len(url) > 50 else url
else:
    url_mask = url

print("DATABASE_URL (actual):", url_mask)
print("Tipo:", "PostgreSQL" if "postgres" in url.lower() else "SQLite")

from models import SessionLocal, Question
db = SessionLocal()
try:
    total = db.query(Question).count()
    active = db.query(Question).filter(Question.active == True).count()
    print("Total preguntas:", total)
    print("Preguntas activas:", active)
finally:
    db.close()
