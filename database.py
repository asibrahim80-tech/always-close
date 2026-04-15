import logging
from config import SUPABASE_URL, SUPABASE_KEY

_logger = logging.getLogger(__name__)

supabase = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        _logger.error(f"Failed to create Supabase client: {e}")
else:
    _logger.warning("Supabase client not initialized — credentials missing.")
