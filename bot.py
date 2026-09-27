import os
import logging
import os
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db

load_dotenv()

logging.basicConfig(format="%(levelname)s %(name)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("pendientes")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
ALLOWED_USER_IDS = {int(x) for x in os.environ["ALLOWED_USER_IDS"].split(",")}
BOGOTA = ZoneInfo("America/Bogota")
HORA_DIGEST = time(hour=8, minute=30, tzinfo=BOGOTA)


def allowed(update: Update) -> bool:
    return update.effective_user.id in ALLOWED_USER_IDS


def build_list(chat_id: int):
    rows = db.list_open(chat_id)
    if not rows:
        return "✅ No hay pendientes abiertos.", None
    lineas = [f"· {r['title']}" for r in rows]
    texto = "🧾 Pendientes abiertos\n\n" + "\n".join(lineas)
    botones = [
        [
            InlineKeyboardButton(
                f"✅ {r['title'][:40]}",
                callback_data=f"resolve:{r['id']}",
            )
        ]
        for r in rows
    ]
    return texto, InlineKeyboardMarkup(botones)


async def send_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    abiertos = len(db.list_open(CHAT_ID))
    texto, botones = build_list(CHAT_ID)
    await context.bot.send_message(CHAT_ID, texto, reply_markup=botones)
    log.info("digest enviado con %s pendientes abiertos", abiertos)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        log.warning("mensaje ignorado de user_id=%s", update.effective_user.id)
        return
    title = update.message.text.strip()
    pending_id = db.create_pending(
        chat_id=update.effective_chat.id,
        created_by=update.effective_user.id,
        title=title,
    )
    log.info("pendiente #%s creado por %s: %r", pending_id, update.effective_user.id, title)
    await update.message.reply_text(f"✅ Guardado: {title}")


async def on_lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    texto, botones = build_list(update.effective_chat.id)
    await update.message.reply_text(texto, reply_markup=botones)


async def on_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    await send_digest(context)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not allowed(update):
        await query.answer()
        return
    pending_id = int(query.data.split(":")[1])
    if not db.resolve_pending(pending_id, update.effective_user.id):
        log.info("pendiente #%s ya estaba resuelto", pending_id)
        await query.answer("Ya estaba resuelto")
        return
    log.info("pendiente #%s resuelto por %s", pending_id, update.effective_user.id)
    await query.answer("Resuelto ✅")
    texto, botones = build_list(update.effective_chat.id)
    await query.edit_message_text(texto, reply_markup=botones)


def main() -> None:
    db.init()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler(["lista", "list", "hoy", "tareas"], on_lista))
    app.add_handler(CommandHandler(["digest", "resumen"], on_digest))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.job_queue.run_daily(send_digest, time=HORA_DIGEST, name="digest")
    log.info("bot arriba, digest diario a las %s", HORA_DIGEST)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
