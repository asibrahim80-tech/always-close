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
    show_nearby_rooms,
    create_room_start,
    show_map,
    show_users_list,
    handle_buttons,
    show_matches,
    show_requests,
    toggle_visibility,
    toggle_phone_visibility,
    edit_profile,
    handle_edit_choice,
    handle_text_buttons,
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
        filters.TEXT & filters.Regex(btn_regex("map")), show_map))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("users_list")), show_users_list))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("view_nearby")), show_nearby))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("rooms_nearby")), show_nearby_rooms))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("create_room")), create_room_start))
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

    # Edit Profile Choices (Arabic & English) — must come before the catch-all
    app.add_handler(MessageHandler(
        filters.TEXT & (
            filters.Regex(btn_regex("edit_gender")) |
            filters.Regex(btn_regex("edit_birthdate")) |
            filters.Regex(btn_regex("edit_bio"))
        ),
        handle_edit_choice
    ))

    # Catch-all: handles profile setup steps AND Rooms Nearby
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))

    # Error Handler
    app.add_error_handler(error_handler)

    logger.info("🚀 Always Close Bot Started...")
    app.run_polling()


if __name__ == "__main__":
    main()
