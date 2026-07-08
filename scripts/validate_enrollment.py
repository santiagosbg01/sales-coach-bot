#!/usr/bin/env python3
"""
Validate enrollment configuration and invite link.
Run from project root: python scripts/validate_enrollment.py
"""
import os
import sys

# Load env and config from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    from dotenv import load_dotenv
    load_dotenv()
    from config import Config
    from dashboard_app.bot_bridge import get_bot_username

    enroll_code = (Config.ENROLL_CODE or "enroll").strip()
    username = (Config.TELEGRAM_BOT_USERNAME or "").strip() or get_bot_username()
    if not username:
        username = "Coach_growth99_bot"
        print("⚠️  TELEGRAM_BOT_USERNAME no configurado y getMe no disponible; usando fallback:", username)
    else:
        print("✅ Bot username:", username)

    link = f"https://t.me/{username}?start={enroll_code}"
    print("✅ ENROLL_CODE:", repr(enroll_code))
    print("✅ Enlace de inscripción (el bot recibirá /start con argumento):")
    print("   ", link)
    print()
    print("Cuando el usuario abre este enlace, Telegram envía: /start", enroll_code)
    print("El bot compara el argumento con ENROLL_CODE (sin distinguir mayúsculas).")
    print()
    if not Config.TELEGRAM_BOT_TOKEN:
        print("⚠️  TELEGRAM_BOT_TOKEN no está configurado; no se puede verificar getMe.")
    else:
        uname = get_bot_username()
        if uname:
            print("✅ getMe OK — el token es válido y el bot existe.")
        else:
            print("❌ getMe falló — revisa TELEGRAM_BOT_TOKEN.")

if __name__ == "__main__":
    main()
