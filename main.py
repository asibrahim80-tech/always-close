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
    toggle_phone_visibility,
    handle_profile_steps,
    edit_profile,
    handle_edit_choice
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

    # Commands
    app.add_handler(CommandHandler("start", start))

    # Contact & Location
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    # Inline Buttons
    app.add_handler(CallbackQueryHandler(handle_buttons))

    # Main Menu Buttons
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^👥 عرض الأقرب$"), show_nearby))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🔥 التطابقات$"), show_matches))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📥 طلباتي$"), show_requests))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^👻 إخفاء حسابي$"), toggle_visibility))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📞 إظهار/إخفاء رقمي$"), toggle_phone_visibility))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^✏️ تعديل بياناتي$"), edit_profile))

    # Edit Profile Choices
    app.add_handler(MessageHandler(
        filters.TEXT & (
            filters.Regex("^👤 تعديل النوع$") |
            filters.Regex("^🎂 تعديل تاريخ الميلاد$") |
            filters.Regex("^📝 تعديل النبذة$")
        ),
        handle_edit_choice
    ))

    # Profile Setup Steps (catches remaining text when step is active)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_steps))

    # Error Handler
    app.add_error_handler(error_handler)

    logger.info("🚀 Always Close Bot Started...")
    app.run_polling()


if __name__ == "__main__":
    main()
