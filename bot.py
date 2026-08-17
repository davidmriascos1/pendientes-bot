import os

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

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USER_IDS = {int(x) for x in os.environ["ALLOWED_USER_IDS"].split(",")}


def allowed(update: Update) -> bool:
    return update.effective_user.id in ALLOWED_USER_IDS


def build_list(chat_id: int):
    rows = db.list_open(chat_id)
    if not rows:
        return "✅ No hay pendientes abiertos.", None
    lineas = [f"#{r['id']} · {r['title']}" for r in rows]
    texto = "🧾 Pendientes abiertos\n\n" + "\n".join(lineas)
    botones = [
        [
            InlineKeyboardButton(
                f"✅ #{r['id']} {r['title'][:20]}",
                callback_data=f"resolve:{r['id']}",
            )
        ]
        for r in rows
    ]
    return texto, InlineKeyboardMarkup(botones)


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
    texto, botones = build_list(update.effective_chat.id)
    await update.message.reply_text(texto, reply_markup=botones)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not allowed(update):
        await query.answer()
        return
    pending_id = int(query.data.split(":")[1])
    if not db.resolve_pending(pending_id, update.effective_user.id):
        await query.answer("Ya estaba resuelto")
        return
    await query.answer("Resuelto ✅")
    texto, botones = build_list(update.effective_chat.id)
    await query.edit_message_text(texto, reply_markup=botones)


def main() -> None:
    db.init()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("lista", on_lista))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    print("Bot corriendo. Ctrl+C para parar.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
