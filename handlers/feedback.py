"""
/feedback command — lets reps flag confusing or incorrect questions.
The comment is stored in QuestionFeedback and forwarded to admins/managers.
"""
import logging
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from models import SessionLocal, ChannelIdentity, Question, User, QuestionFeedback, Attempt

logger = logging.getLogger(__name__)


async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage: /feedback <comentario>
    Captures which question the user was looking at (from context),
    stores the comment in QuestionFeedback, and forwards it to admins.
    """
    user = update.effective_user
    comment = " ".join(context.args).strip() if context.args else ""

    if not comment:
        await update.message.reply_text(
            "✍️ *¿Cómo enviar un comentario?*\n\n"
            "Escribe `/feedback` seguido de tu comentario. Ejemplo:\n\n"
            "`/feedback La pregunta sobre drayage no tiene sentido para Colombia`\n\n"
            "Lo revisamos y actualizamos el banco de preguntas. 🙏",
            parse_mode="Markdown",
        )
        return

    # Resolve which question was last shown to this user
    chat_id_str = str(update.effective_chat.id)
    last_question_id = (
        context.user_data.get("last_question_id")
        or context.application.bot_data.get("last_question_id", {}).get(chat_id_str)
    )
    last_attempt_id = context.user_data.get("last_attempt_id")

    question_text = "_(pregunta no identificada)_"
    product_info = ""

    db = SessionLocal()
    try:
        q = None
        if last_question_id:
            q = db.query(Question).filter(Question.id == last_question_id).first()
            if q:
                question_text = f'"{q.prompt}"'
                product_info = f"📦 {q.product or 'general'}  🌎 {q.country or 'all'}"

        # Resolve the rep's internal user and name
        rep_name = user.first_name or user.username or str(user.id)
        internal_user = None
        identity = db.query(ChannelIdentity).filter(
            ChannelIdentity.telegram_user_id == str(user.id)
        ).first()
        if identity:
            internal_user = db.query(User).filter(User.id == identity.user_id).first()
            if internal_user:
                rep_name = internal_user.name

        # Persist feedback in DB (if we know the internal_user)
        if internal_user:
            fb = QuestionFeedback(
                user_id=internal_user.id,
                question_id=last_question_id if last_question_id else None,
                attempt_id=last_attempt_id
                if last_attempt_id and db.query(Attempt).get(last_attempt_id)
                else None,
                comment=comment,
            )
            db.add(fb)
            db.commit()

        # Confirm to the rep
        await update.message.reply_text(
            "✅ *¡Gracias por tu comentario!*\n\n"
            "Lo revisaremos y si es necesario corregimos la pregunta o la respuesta. 💪",
            parse_mode="Markdown",
        )

        # Forward to admin
        ts = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        admin_msg = (
            f"⚠️ *Feedback de pregunta — {Config.APP_NAME}*\n"
            f"_{ts}_\n\n"
            f"👤 *Rep:* {rep_name} (`{user.id}`)\n"
            f"❓ *Pregunta:* {question_text}\n"
        )
        if product_info:
            admin_msg += f"   {product_info}\n"

        admin_msg += f"\n💬 *Comentario:*\n{comment}"

        from services.proactive_sender import _admin_chat_ids

        chat_ids = _admin_chat_ids(db)
        for chat_id in chat_ids:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=admin_msg,
                    parse_mode="Markdown",
                )
                logger.info("Feedback from %s forwarded to %s", rep_name, chat_id)
            except Exception as e:
                logger.error("Failed to forward feedback to %s: %s", chat_id, e)
    finally:
        db.close()
