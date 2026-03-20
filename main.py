import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from config import BOT_TOKEN
from keep_alive import keep_alive
from handlers import (
    start,
    handle_contact,
    handle_location,
    show_nearby,
    handle_buttons,
    show_matches,
    show_requests,
    toggle_visibility,
    toggle_phone_visibility
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


def main():
    keep_alive()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    app.add_handler(CallbackQueryHandler(handle_buttons))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^👥 عرض الأقرب$"), show_nearby))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🔥 التطابقات$"), show_matches))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📥 طلباتي$"), show_requests))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^👻 إخفاء حسابي$"), toggle_visibility))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📞 إظهار/إخفاء رقمي$"), toggle_phone_visibility))

    app.add_error_handler(error_handler)

    logger.info("🚀 Always Close Bot Started...")
    app.run_polling()


if __name__ == "__main__":
    main()
