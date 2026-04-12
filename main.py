import logging
import os
import sys
import time

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
    show_rooms_list,
    create_room_start,
    show_stores_list,
    show_nearby_stores,
    create_store_start,
    show_settings,
    show_profile,
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
    show_room_chats,
    show_store_chats,
    exit_chat,
    relay_any_message,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

_LOCK_FILE = "/tmp/always_close_bot.lock"


def _acquire_lock() -> bool:
    """Return True if this process owns the lock, False if another instance is running."""
    my_pid = os.getpid()
    if os.path.exists(_LOCK_FILE):
        try:
            with open(_LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if that process is still alive
            os.kill(old_pid, 0)
            # Still alive → another instance is running
            logger.warning(
                f"Another bot instance (PID {old_pid}) is already running. "
                "This instance will handle only Flask (web server)."
            )
            return False
        except (ProcessLookupError, ValueError, OSError):
            # Old process is dead → we can take over
            pass
    with open(_LOCK_FILE, "w") as f:
        f.write(str(my_pid))
    return True


def _release_lock():
    try:
        os.remove(_LOCK_FILE)
    except OSError:
        pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


def main():
    # Always start Flask (web server) so the port is served
    keep_alive()

    # Only ONE instance should run the Telegram bot polling
    if not _acquire_lock():
        logger.info("Flask web server started. Bot polling is handled by the primary instance.")
        # Block forever so the process stays alive for the webview port
        import time
        while True:
            time.sleep(60)

    import atexit
    atexit.register(_release_lock)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

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
        filters.TEXT & filters.Regex(btn_regex("rooms_list")), show_rooms_list))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("create_room")), create_room_start))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("stores_list")), show_stores_list))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("create_store")), create_store_start))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("stores_nearby")), show_nearby_stores))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("settings")), show_settings))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("profile")), show_profile))
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
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("room_chats")), show_room_chats))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("store_chats")), show_store_chats))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(btn_regex("exit_chat")), exit_chat))

    # Edit Profile Choices (Arabic & English) — must come before the catch-all
    app.add_handler(MessageHandler(
        filters.TEXT & (
            filters.Regex(btn_regex("edit_gender")) |
            filters.Regex(btn_regex("edit_birthdate")) |
            filters.Regex(btn_regex("edit_bio"))
        ),
        handle_edit_choice
    ))

    # Media relay — handles photos, stickers, files, videos, voice etc when in chat mode
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.Sticker.ALL | filters.Document.ALL |
         filters.VIDEO | filters.VOICE | filters.AUDIO |
         filters.VIDEO_NOTE | filters.ANIMATION) & ~filters.COMMAND,
        relay_any_message
    ))

    # Catch-all: handles profile setup steps AND Rooms Nearby
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))

    # Error Handler
    app.add_error_handler(error_handler)

    logger.info("🚀 Always Close Bot Started...")

    # ── Polling with auto-reconnect ──────────────────────────────────────
    retry_delay = 5   # seconds between reconnect attempts
    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=False,
                poll_interval=1.0,
                timeout=20,
            )
        except Exception as exc:
            logger.error(f"Bot polling crashed: {exc}. Reconnecting in {retry_delay}s…")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # exponential back-off, max 60s
        else:
            break   # clean shutdown (e.g. SIGTERM)


if __name__ == "__main__":
    main()
