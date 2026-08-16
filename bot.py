import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_IDS = {int(x) for x in os.environ["ALLOWED_USER_IDS"].split(",")}


def allowed(update: Update) -> bool:
    return update.effective_user.id in ALLOWED_USER_IDS


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    title = update.message.text.strip()
    pending_id = db.create_pending(
        chat_id=update.effective_chat.id,
        created_by=update.effective_user.id,
        title=title,
    )
    await update.message.reply_text(f"✅ Guardado #{pending_id}: {title}")


async def on_lista(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return
    rows = db.list_open(update.effective_chat.id)
    if not rows:
        await update.message.reply_text("✅ No hay pendientes abiertos.")
        return
    lineas = [f"#{r['id']} · {r['title']}" for r in rows]
    await update.message.reply_text("🧾 Pendientes abiertos\n\n" + "\n".join(lineas))


def main() -> None:
    db.init()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("lista", on_lista))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    print("Bot corriendo. Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
