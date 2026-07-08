"""
/report command — admin only.
Shows team and per-user stats across Current Month, Last Month, and Total.
"""
import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from models import SessionLocal, User, Attempt, Grade, UserStatus
from services.stats import user_stats, fmt, tag_breakdown, format_tag_breakdown

logger = logging.getLogger(__name__)

# Admin telegram chat_ids that can request /report. Configure via ADMIN_CHAT_ID env var
# (comma-separated). Users with role=ADMIN in the DB are also allowed automatically.
import os as _os_admin
ADMIN_TELEGRAM_IDS = {
    x.strip() for x in _os_admin.getenv("ADMIN_CHAT_ID", "").split(",") if x.strip()
}


def _team_period(user_stat_list: list, period: str) -> dict:
    total = {"sent": 0, "answered": 0, "expired": 0, "correct": 0}
    for s in user_stat_list:
        for k in total:
            total[k] += s[period][k]
    return total


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = str(update.effective_user.id)

    if tg_id not in ADMIN_TELEGRAM_IDS:
        await update.message.reply_text("⛔ No tienes acceso a este comando.")
        return

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.status == UserStatus.ACTIVE).all()

        if not users:
            await update.message.reply_text("No hay usuarios activos aún.")
            return

        all_stats = [user_stats(u.id, db) for u in users]

        # Team totals
        cur  = _team_period(all_stats, "current_month")
        last = _team_period(all_stats, "last_month")
        tot  = _team_period(all_stats, "total")

        def pct(a, b): return f"{round(a/b*100)}%" if b else "—"

        msg = (
            f"📊 *Reporte del Equipo — {Config.APP_NAME}*\n"
            f"_Generado: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC_\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 *Usuarios activos:* {len(users)}\n\n"
            "*── Mes actual ──*\n"
            f"📤 Enviadas: {cur['sent']}  💬 Respondidas: {cur['answered']} ({pct(cur['answered'], cur['sent'])})\n"
            f"✅ Correctas: {cur['correct']} ({pct(cur['correct'], cur['answered'])})  ⏰ Expiradas: {cur['expired']}\n\n"
            "*── Mes pasado ──*\n"
            f"📤 Enviadas: {last['sent']}  💬 Respondidas: {last['answered']} ({pct(last['answered'], last['sent'])})\n"
            f"✅ Correctas: {last['correct']} ({pct(last['correct'], last['answered'])})  ⏰ Expiradas: {last['expired']}\n\n"
            "*── Total histórico ──*\n"
            f"📤 Enviadas: {tot['sent']}  💬 Respondidas: {tot['answered']} ({pct(tot['answered'], tot['sent'])})\n"
            f"✅ Correctas: {tot['correct']} ({pct(tot['correct'], tot['answered'])})  ⏰ Expiradas: {tot['expired']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*Detalle por usuario:*\n\n"
        )

        # Build overview block first, then one message per user with tag detail
        messages = [msg]

        for user, stats in zip(users, all_stats):
            c = stats["current_month"]
            l = stats["last_month"]
            t = stats["total"]
            bd = tag_breakdown(user.id, db)

            _flag = {"mexico": "🇲🇽", "colombia": "🇨🇴", "chile": "🇨🇱", "peru": "🇵🇪"}
            role_label = {"hunter": "🎯 Hunter", "farmer": "🌱 Farmer"}.get(
                (user.sales_role.value if user.sales_role else ""), ""
            )
            country_str = (
                _flag.get(user.base_country or "", "🌎") + " " + (user.base_country or "").capitalize()
                if user.base_country else ""
            )
            specs_str = (
                "📦 " + " · ".join(s.capitalize() for s in (user.specializations or []))
                if user.specializations else ""
            )
            profile_bits = [x for x in [role_label, country_str, specs_str] if x]
            profile_line = ("  " + "  ".join(profile_bits) + "\n") if profile_bits else ""

            user_block = (
                f"👤 *{user.name}*\n"
                f"{profile_line}"
                f"  Este mes:   {fmt(c)}\n"
                f"  Mes pasado: {fmt(l)}\n"
                f"  Total:      {fmt(t)}\n\n"
                + format_tag_breakdown(bd)
                + "\n"
            )
            messages[-1] += user_block

            # Split into a new message if approaching Telegram's 4096-char limit
            if len(messages[-1]) > 3800:
                messages.append("")

        for chunk in messages:
            if chunk.strip():
                await update.message.reply_text(chunk, parse_mode="Markdown")

    finally:
        db.close()
