"""
Always Close — Security Module
Telegram WebApp initData validation + input sanitization
"""
import hashlib
import hmac
import json
import logging
from functools import wraps
from urllib.parse import unquote

from flask import request, jsonify

logger = logging.getLogger("security")

# ── Telegram initData Validation ──────────────────────────────────────────────

def validate_telegram_init_data(init_data_raw: str, bot_token: str) -> dict | None:
    """
    Validate Telegram WebApp initData using HMAC-SHA256.
    Returns parsed data dict if valid, None if invalid/tampered.
    Docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data_raw or not bot_token:
        return None
    try:
        # Parse key=value pairs
        pairs = {}
        for part in init_data_raw.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                pairs[k] = unquote(v)

        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        # Build the data-check string (sorted keys, \n separated)
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(pairs.items())
        )

        # Secret key = HMAC-SHA256("WebAppData", bot_token)
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        # Expected hash
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            logger.warning("initData hash mismatch — possible tampering")
            return None

        # Decode JSON sub-fields (user, receiver, chat, etc.)
        result = {}
        for k, v in pairs.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                result[k] = v

        return result

    except Exception as e:
        logger.error(f"initData validation error: {e}")
        return None


def get_telegram_user_id(init_data_raw: str, bot_token: str) -> int | None:
    """Return the validated Telegram user ID from initData, or None."""
    data = validate_telegram_init_data(init_data_raw, bot_token)
    if not data:
        return None
    user = data.get("user")
    if isinstance(user, dict):
        return user.get("id")
    return None


# ── Decorator: require valid Telegram initData ────────────────────────────────

def require_telegram_auth(f):
    """
    Decorator for POST endpoints.
    Reads `init_data` from JSON body, validates it, and
    injects `_tg_uid` (verified Telegram user ID) into kwargs.
    Falls back gracefully in development (no initData = warning only).
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        from config import BOT_TOKEN
        data       = request.get_json(force=True) or {}
        init_data  = data.get("init_data", "")

        if not init_data:
            # Allow without initData but log a warning
            # In production you can make this a hard reject
            logger.warning(f"[{f.__name__}] No initData provided — skipping Telegram auth check")
            kwargs["_tg_uid"] = None
            return f(*args, **kwargs)

        tg_uid = get_telegram_user_id(init_data, BOT_TOKEN)
        if tg_uid is None:
            logger.warning(f"[{f.__name__}] Invalid initData — rejecting request")
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        kwargs["_tg_uid"] = tg_uid
        return f(*args, **kwargs)
    return wrapper


# ── Input Sanitization ────────────────────────────────────────────────────────

def sanitize_text(value: str | None, max_len: int = 500) -> str:
    """Strip whitespace and enforce max length."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_len]


def sanitize_int(value, default: int = 0, min_val: int = 0, max_val: int = 10**12) -> int:
    """Safely convert to int within bounds."""
    try:
        v = int(value)
        return max(min_val, min(max_val, v))
    except (TypeError, ValueError):
        return default


# ── Rate Limit Key Functions ──────────────────────────────────────────────────

def get_remote_addr():
    """Best-effort IP extraction (handles proxies)."""
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP", "")
        or request.remote_addr
        or "unknown"
    )
