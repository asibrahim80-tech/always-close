# ==============================
# Always Close - Main Entry
# ==============================

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
from handlers import (
    start,
    handle_location,
    handle_buttons,
    show_nearby,
    handle_contact,
    show_matches,
    show_requests,
    toggle_visibility,
    toggle_phone_visibility
)
from keep_alive import keep_alive
keep_alive()

# ==============================
# Logging System (Production)
# ==============================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ==============================
# Global Error Handler
# ==============================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# ==============================
# Main Function
# ==============================

def main():

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # -------- Commands --------
    app.add_handler(CommandHandler("start", start))

    # -------- Location --------
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    # -------- Contact --------
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))

    # -------- Buttons (Inline) --------
    app.add_handler(CallbackQueryHandler(handle_buttons))

    # -------- Menu Handlers --------
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^👥 عرض الأقرب$"), show_nearby))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🔥 التطابقات$"), show_matches))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📥 طلباتي$"), show_requests))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^👻 إخفاء حسابي$"), toggle_visibility))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📞 إظهار/إخفاء رقمي$"), toggle_phone_visibility))

    # -------- Error Handler --------
    app.add_error_handler(error_handler)

    logger.info("🚀 Always Close Bot Started...")

app.run_polling()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_age))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_gender))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_profile_bio))

# ==============================
# Run Application
# ==============================

if __name__ == "__main__":
    main()
