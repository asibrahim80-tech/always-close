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
from lang import btn_regex
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
    handle_edit_choice,
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

    # Main Menu Buttons (Arabic & English)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("view_nearby")), show_nearby))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("matches")), show_matches))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("requests")), show_requests))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("hide")), toggle_visibility))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("phone_toggle")), toggle_phone_visibility))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("edit_profile")), edit_profile))

    # Edit Profile Choices (Arabic & English)
    app.add_handler(MessageHandler(
        filters.TEXT & (
            filters.Regex(btn_regex("edit_gender")) |
            filters.Regex(btn_regex("edit_birthdate")) |
            filters.Regex(btn_regex("edit_bio"))
        ),
        handle_edit_choice
    ))

    # Profile Setup Steps (catch-all for text when a step is active)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_steps))

    # Error Handler
    app.add_error_handler(error_handler)

    logger.info("🚀 Always Close Bot Started...")
    app.run_polling()


if __name__ == "__main__":
    main()
