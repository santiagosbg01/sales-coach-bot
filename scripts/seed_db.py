"""
Ejecuta solo el seed de preguntas (data/*.json) en la base de datos
que marque DATABASE_URL. No arranca el bot.

Útil para emparejar la base en Railway sin redesplegar:
  railway run python scripts/seed_db.py

En local (para refrescar desde los JSON):
  python3 scripts/seed_db.py
"""
import os
import sys

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "seed_script")
os.environ.setdefault("OPENAI_API_KEY", "seed_script")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from models import init_db, migrate_db
from startup_enroll import seed_questions

if __name__ == "__main__":
    print("Usando DATABASE_URL del entorno actual...")
    init_db()
    migrate_db()
    seed_questions()
    print("Listo.")
