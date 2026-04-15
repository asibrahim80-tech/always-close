import os
import logging

_logger = logging.getLogger(__name__)

# ==========================
# Telegram Bot Token
# ==========================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not BOT_TOKEN:
    _logger.warning("BOT_TOKEN is not set — Telegram bot features will be unavailable.")


# ==========================
# Supabase Credentials
# ==========================

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    _logger.warning("Supabase credentials are missing — database features will be unavailable.")
