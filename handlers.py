import os
import logging
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import ContextTypes
from database import supabase
from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, atan2
import geohash2
from lang import T, detect_lang, ALL_BTN

logger = logging.getLogger(__name__)

# Priority: APP_DOMAIN (manual override) → REPLIT_DOMAINS (runtime) → REPLIT_DEV_DOMAIN (dev)
_raw_domains = os.environ.get("REPLIT_DOMAINS", "")
DOMAIN = (
    os.environ.get("APP_DOMAIN", "").strip()
    or (_raw_domains.split(",")[0].strip() if _raw_domains else "")
    or os.environ.get("REPLIT_DEV_DOMAIN", "")
)
logger.info(f"🌐 WebApp DOMAIN = {DOMAIN!r}  (APP_DOMAIN={os.environ.get('APP_DOMAIN')!r}, REPLIT_DOMAINS={_raw_domains!r})")


# =========================================================
# HELPERS
# =========================================================

def get_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if context.user_data.get("lang"):
        return context.user_data["lang"]
    lang = detect_lang(update.effective_user.language_code)
    context.user_data["lang"] = lang
    return lang


def time_ago(timestamp: str, lang: str) -> str:
    if not timestamp:
        return "?"
    try:
        past = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - past).total_seconds())
        if diff < 60:
            return T(lang, "now_unit")
        elif diff < 3600:
            return f"{diff // 60} {T(lang, 'min_unit')}"
        elif diff < 86400:
            return f"{diff // 3600} {T(lang, 'hour_unit')}"
        else:
            return f"{diff // 86400} {T(lang, 'day_unit')}"
    except Exception:
        return "?"


def calculate_distance(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def normalize_gender(text: str, lang: str) -> str:
    """Return stored gender value in English (Male/Female)."""
    text_lower = text.lower()
    if "ذكر" in text or "male" in text_lower:
        return "Male"
    return "Female"


def display_gender(gender: str, lang: str) -> str:
    """Translate stored gender (Male/Female) to display language."""
    if gender == "Male":
        return T(lang, "gender_male")
    elif gender == "Female":
        return T(lang, "gender_female")
    return T(lang, "unknown_gender")


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(lang: str, tg_id: int = 0) -> ReplyKeyboardMarkup:
    def wb(path: str) -> WebAppInfo:
        sep = "&" if "?" in path else "?"
        return WebAppInfo(url=f"https://{DOMAIN}{path}{sep}uid={tg_id}&lang={lang}")

    if tg_id:
        return ReplyKeyboardMarkup([
            [KeyboardButton(T(lang, "btn_profile"),          web_app=wb("/profile")),
             KeyboardButton(T(lang, "btn_map"),              web_app=wb("/map"))],
            [KeyboardButton(T(lang, "btn_settings"),         web_app=wb("/settings")),
             KeyboardButton(T(lang, "btn_public_chat"),      web_app=wb("/public-chat"))],
            [KeyboardButton(T(lang, "btn_users_list"),       web_app=wb("/users")),
             KeyboardButton(T(lang, "btn_view_nearby"),      web_app=wb("/users?nearby=1"))],
            [KeyboardButton(T(lang, "btn_objects_list"),     web_app=wb("/objects")),
             KeyboardButton(T(lang, "btn_create_object"),    web_app=wb("/create-object"))],
            [KeyboardButton(T(lang, "btn_matches_requests"), web_app=wb("/likes"))],
        ], resize_keyboard=True)

    # Fallback (no tg_id yet — first interaction before registration)
    return ReplyKeyboardMarkup([
        [KeyboardButton(T(lang, "btn_share_location"), request_location=True)],
        [KeyboardButton(T(lang, "btn_profile")),       KeyboardButton(T(lang, "btn_map"))],
        [KeyboardButton(T(lang, "btn_settings"),       KeyboardButton(T(lang, "btn_public_chat")))],
        [KeyboardButton(T(lang, "btn_users_list")),    KeyboardButton(T(lang, "btn_view_nearby"))],
        [KeyboardButton(T(lang, "btn_objects_list")),  KeyboardButton(T(lang, "btn_create_object"))],
        [KeyboardButton(T(lang, "btn_matches_requests"))],
    ], resize_keyboard=True)


def edit_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [T(lang, "btn_edit_gender")],
        [T(lang, "btn_edit_birthdate")],
        [T(lang, "btn_edit_bio")],
    ], resize_keyboard=True)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    tg_id = tg_user.id
    lang = detect_lang(tg_user.language_code)
    context.user_data["lang"] = lang
    context.user_data.pop("step", None)  # clear any old setup step

    user = supabase.table("users_v1").select("id, language, first_name").eq("telegram_id", tg_id).execute()

    if not user.data:
        # New user — create basic record immediately using Telegram data
        supabase.table("users_v1").insert({
            "telegram_id": tg_id,
            "username": tg_user.username or "",
            "first_name": tg_user.first_name or "",
            "last_name": tg_user.last_name or "",
            "language": lang,
            "is_active": True,
            "is_visible": True,
        }).execute()
        welcome_text = T(lang, "welcome_new")
    else:
        # Returning user — update language in DB if changed
        stored_lang = user.data[0].get("language") or "en"
        if stored_lang != lang:
            supabase.table("users_v1").update({"language": lang}).eq("telegram_id", tg_id).execute()
        welcome_text = T(lang, "welcome_back")

    # Build display name from Telegram profile
    display_name = f"{tg_user.first_name or ''} {tg_user.last_name or ''}".strip()
    greeting = f"{welcome_text}\n\n👤 {display_name}" if display_name else welcome_text

    keyboard = main_keyboard(lang, tg_id)

    # Try to send profile photo alongside the welcome message
    try:
        photos = await tg_user.get_profile_photos(limit=1)
        if photos.total_count > 0:
            photo_file_id = photos.photos[0][-1].file_id
            await update.message.reply_photo(
                photo=photo_file_id,
                caption=greeting,
                reply_markup=keyboard,
            )
            return
    except Exception as _photo_err:
        logger.warning(f"Could not fetch profile photo for {tg_id}: {_photo_err}")

    # Fallback — text only
    await update.message.reply_text(greeting, reply_markup=keyboard)


# =========================================================
# PROFILE SETUP (STEPS)
# =========================================================

async def handle_profile_steps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    if not step:
        return

    text = update.message.text
    lang = get_lang(update, context)

    if step == "gender":
        context.user_data["gender"] = normalize_gender(text, lang)
        context.user_data["step"] = "birthdate"
        await update.message.reply_text(T(lang, "enter_birthdate"))
        return

    elif step == "birthdate":
        try:
            year, month, day = map(int, text.split("-"))
            today = datetime.today()
            age = today.year - year - ((today.month, today.day) < (month, day))
            if age < 13 or age > 100:
                raise ValueError("Invalid age")
            context.user_data["birthdate"] = text
            context.user_data["age"] = age
            context.user_data["step"] = "bio"
            await update.message.reply_text(T(lang, "enter_bio"))
        except Exception:
            await update.message.reply_text(T(lang, "invalid_date"))
        return

    elif step == "bio":
        tg_id = update.effective_user.id
        username = update.effective_user.username

        user_check = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()

        data = {
            "telegram_id": tg_id,
            "username": username,
            "gender": context.user_data.get("gender"),
            "birthdate": context.user_data.get("birthdate"),
            "age": context.user_data.get("age"),
            "bio": text,
            "language": lang,
            "is_active": True,
            "is_visible": True,
        }

        if user_check.data:
            supabase.table("users_v1").update(data).eq("telegram_id", tg_id).execute()
        else:
            supabase.table("users_v1").insert(data).execute()

        context.user_data.clear()
        context.user_data["lang"] = lang
        await update.message.reply_text(T(lang, "profile_saved"), reply_markup=main_keyboard(lang, update.effective_user.id))
        return

    elif step == "edit_gender":
        supabase.table("users_v1").update({
            "gender": normalize_gender(text, lang)
        }).eq("telegram_id", update.effective_user.id).execute()
        context.user_data.clear()
        context.user_data["lang"] = lang
        await update.message.reply_text(T(lang, "updated"), reply_markup=main_keyboard(lang, update.effective_user.id))
        return

    elif step == "edit_birthdate":
        try:
            year, month, day = map(int, text.split("-"))
            today = datetime.today()
            age = today.year - year - ((today.month, today.day) < (month, day))
            if age < 13 or age > 100:
                raise ValueError("Invalid age")
            supabase.table("users_v1").update({
                "birthdate": text,
                "age": age
            }).eq("telegram_id", update.effective_user.id).execute()
            context.user_data.clear()
            context.user_data["lang"] = lang
            await update.message.reply_text(T(lang, "updated"), reply_markup=main_keyboard(lang, update.effective_user.id))
        except Exception:
            await update.message.reply_text(T(lang, "invalid_date"))
        return

    elif step == "edit_bio":
        supabase.table("users_v1").update({
            "bio": text
        }).eq("telegram_id", update.effective_user.id).execute()
        context.user_data.clear()
        context.user_data["lang"] = lang


# =========================================================
# EDIT PROFILE
# =========================================================

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    await update.message.reply_text(
        T(lang, "what_to_edit"),
        reply_markup=edit_keyboard(lang)
    )


async def handle_edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    lang = get_lang(update, context)

    # Match both Arabic and English edit buttons
    edit_gender_btns = ALL_BTN["edit_gender"]
    edit_bdate_btns = ALL_BTN["edit_birthdate"]
    edit_bio_btns = ALL_BTN["edit_bio"]

    if any(b in text for b in edit_gender_btns):
        context.user_data["step"] = "edit_gender"
        await update.message.reply_text(
            T(lang, "choose_gender"),
            reply_markup=ReplyKeyboardMarkup(
                [[T(lang, "btn_male"), T(lang, "btn_female")]],
                resize_keyboard=True
            )
        )
    elif any(b in text for b in edit_bdate_btns):
        context.user_data["step"] = "edit_birthdate"
        await update.message.reply_text(T(lang, "enter_birthdate_edit"))
    elif any(b in text for b in edit_bio_btns):
        context.user_data["step"] = "edit_bio"
        await update.message.reply_text(T(lang, "enter_bio_edit"))


# =========================================================
# HANDLE CONTACT
# =========================================================

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    phone = update.message.contact.phone_number
    supabase.table("users_v1").update({"phone": phone}).eq(
        "telegram_id", update.effective_user.id
    ).execute()
    await update.message.reply_text(T(lang, "phone_saved"))


# =========================================================
# HANDLE LOCATION
# =========================================================

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_lang(update, context)
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    geo = geohash2.encode(lat, lon, precision=7)

    # Get profile photo file_id (never expires, Telegram caches by file_id)
    photo_url = None
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            photo_url = photos.photos[0][0].file_id
    except Exception:
        photo_url = None

    # Get or create user record
    existing = supabase.table("users_v1").select("id").eq("telegram_id", user.id).execute()

    if existing.data:
        user_id = existing.data[0]["id"]
        update_data = {"username": user.username}
        if photo_url:
            update_data["photo_url"] = photo_url
        supabase.table("users_v1").update(update_data).eq("id", user_id).execute()
    else:
        insert = supabase.table("users_v1").insert({
            "telegram_id": user.id,
            "username": user.username,
            "photo_url": photo_url,
            "language": lang,
            "is_active": True,
            "is_visible": True,
        }).execute()
        if not insert.data:
            await update.message.reply_text(T(lang, "registration_error"))
            return
        user_id = insert.data[0]["id"]

    # Always update user_locations_v1 with this fresh GPS fix
    existing_loc = supabase.table("user_locations_v1") \
        .select("id") \
        .eq("user_id", user_id) \
        .limit(1) \
        .execute()

    now_iso = datetime.now(timezone.utc).isoformat()
    loc_data = {
        "latitude":    lat,
        "longitude":   lon,
        "geohash":     geo,
        "source":      "GPS",
        "recorded_at": now_iso,
    }

    if existing_loc.data:
        loc_id = existing_loc.data[0]["id"]
        supabase.table("user_locations_v1").update(loc_data).eq("id", loc_id).execute()
    else:
        loc_data["user_id"] = user_id
        supabase.table("user_locations_v1").insert(loc_data).execute()

    await update.message.reply_text(T(lang, "location_updated"))


# =========================================================
# SEND PROFILE CARD
# =========================================================

async def send_profile_card(context, chat_id: int, user: dict, lang: str):
    name = user.get("username") or T(lang, "user_label")
    age = user.get("age") or "?"
    gender_raw = user.get("gender") or ""
    gender = display_gender(gender_raw, lang)
    bio = user.get("bio") or ""
    distance = user.get("distance", 0)
    photo_url = user.get("photo_url")

    # Distance text
    if distance:
        distance_text = f"{distance} {T(lang, 'km_unit')}"
    else:
        distance_text = T(lang, "unknown_distance")

    # Last seen — use location timestamp when available, fall back to created_at
    last_ts  = user.get("last_seen") or user.get("created_at")
    raw_time = time_ago(last_ts, lang)
    if raw_time == T(lang, "now_unit"):
        status = T(lang, "active_now")
    else:
        status = f"🕒 {T(lang, 'last_seen_label')} {raw_time}"

    caption = (
        f"<b>👤 {name}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎂 {age} {T(lang, 'years_unit')}\n"
        f"🚻 {gender}\n"
        f"📍 {distance_text}\n"
        f"{status}"
    )
    if bio:
        caption += f"\n📝 {bio}"

    uid = user.get("id")
    keyboard = [
        [
            InlineKeyboardButton(T(lang, "btn_prev"), callback_data="prev"),
            InlineKeyboardButton(T(lang, "btn_next"), callback_data="next"),
        ],
        [
            InlineKeyboardButton(T(lang, "btn_like"), callback_data=f"like_{uid}"),
            InlineKeyboardButton(T(lang, "btn_superlike"), callback_data=f"superlike_{uid}"),
            InlineKeyboardButton(T(lang, "btn_skip"), callback_data="skip"),
        ],
    ]

    if user.get("username"):
        keyboard.append([
            InlineKeyboardButton(T(lang, "btn_message"), url=f"https://t.me/{user['username']}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Try sending with photo (file_id never expires)
    if photo_url:
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass

    # Fallback: text only
    await context.bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


# =========================================================
# HANDLE BUTTONS
# =========================================================

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    lang = context.user_data.get("lang") or detect_lang(query.from_user.language_code)
    telegram_id = query.from_user.id
    data = query.data
    chat_id = query.message.chat.id
    users = context.user_data.get("nearby_list", [])
    idx = context.user_data.get("current_index", 0)

    try:
        if data in ("next", "prev", "skip"):
            await query.answer()
            if not users:
                return
            if data == "prev":
                new_idx = (idx - 1) % len(users)
            else:
                new_idx = (idx + 1) % len(users)
            context.user_data["current_index"] = new_idx
            await send_profile_card(context, chat_id, users[new_idx], lang)

        elif data.startswith("like_"):
            target_id = int(data.split("_")[1])

            me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
            if not me.data:
                await query.answer(T(lang, "register_first_answer"))
                return

            my_id = me.data[0]["id"]

            # Insert like — ignore duplicate errors
            try:
                supabase.table("likes_v1").insert({
                    "from_user_id": my_id,
                    "to_user_id": target_id,
                }).execute()
            except Exception:
                pass

            # Check mutual like
            mutual = supabase.table("likes_v1") \
                .select("id") \
                .eq("from_user_id", target_id) \
                .eq("to_user_id", my_id) \
                .execute()

            if mutual.data:
                # Create match if it doesn't exist
                match_exists = supabase.table("matches_v1") \
                    .select("id") \
                    .or_(
                        f"and(user1_id.eq.{my_id},user2_id.eq.{target_id}),"
                        f"and(user1_id.eq.{target_id},user2_id.eq.{my_id})"
                    ).execute()

                if not match_exists.data:
                    try:
                        supabase.table("matches_v1").insert({
                            "user1_id": my_id,
                            "user2_id": target_id,
                        }).execute()
                    except Exception:
                        pass

                await query.answer(T(lang, "answer_match"))
                await context.bot.send_message(chat_id, T(lang, "mutual_match"))
            else:
                await query.answer(T(lang, "answer_liked"))

            # Advance to next card
            if users:
                new_idx = (idx + 1) % len(users)
                context.user_data["current_index"] = new_idx
                await send_profile_card(context, chat_id, users[new_idx], lang)

        elif data.startswith("superlike_"):
            await query.answer(T(lang, "answer_superlike"), show_alert=True)
            if users:
                new_idx = (idx + 1) % len(users)
                context.user_data["current_index"] = new_idx
                await send_profile_card(context, chat_id, users[new_idx], lang)

        # ── Room chat select — open WebApp chat page ──────
        elif data.startswith("room_chat_sel:"):
            room_id  = int(data.split(":")[1])
            room_res = supabase.table("rooms_v1").select("name").eq("id", room_id).execute()
            room_name = room_res.data[0]["name"] if room_res.data else "?"
            chat_url  = f"https://{DOMAIN}/group-chat?uid={telegram_id}&type=room&id={room_id}&lang={lang}"
            btn_label = ("💬 فتح دردشة الغرفة" if lang == "ar" else "💬 Open Room Chat")
            txt = (f"🏠 دردشة غرفة «{room_name}»" if lang == "ar"
                   else f"🏠 Room chat: «{room_name}»")
            await query.answer()
            await query.message.reply_text(
                txt,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(btn_label, web_app=WebAppInfo(url=chat_url))
                ]])
            )

        # ── Store chat select — open WebApp chat page ─────
        elif data.startswith("store_chat_sel:"):
            store_id   = int(data.split(":")[1])
            store_res  = supabase.table("stores_v1").select("name").eq("id", store_id).execute()
            store_name = store_res.data[0]["name"] if store_res.data else "?"
            chat_url   = f"https://{DOMAIN}/group-chat?uid={telegram_id}&type=store&id={store_id}&lang={lang}"
            btn_label  = ("💬 فتح دردشة المتجر" if lang == "ar" else "💬 Open Store Chat")
            txt = (f"🏪 دردشة متجر «{store_name}»" if lang == "ar"
                   else f"🏪 Store chat: «{store_name}»")
            await query.answer()
            await query.message.reply_text(
                txt,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(btn_label, web_app=WebAppInfo(url=chat_url))
                ]])
            )

        # ── Object chat select ────────────────────────────
        elif data.startswith("object_chat_sel:"):
            object_id = int(data.split(":")[1])
            _object_chat_sessions[telegram_id] = object_id
            _room_chat_sessions.pop(telegram_id, None)
            _store_chat_sessions.pop(telegram_id, None)
            _private_chats.pop(telegram_id, None)
            obj_res  = supabase.table("objects_v1").select("name").eq("id", object_id).execute()
            obj_name = obj_res.data[0]["name"] if obj_res.data else "?"
            txt = (f"🗂️ دردشة كيان «{obj_name}»" if lang == "ar"
                   else f"🗂️ Entity chat: «{obj_name}»")
            await query.answer()
            await query.message.reply_text(txt, reply_markup=_exit_btn(lang))

        # ── Start private chat ────────────────────────────
        elif data.startswith("priv_chat:"):
            target_tg_id = int(data.split(":")[1])
            if target_tg_id == telegram_id:
                await query.answer("❌")
                return
            # Set both sides into private chat
            _private_chats[telegram_id] = target_tg_id
            _private_chats[target_tg_id] = telegram_id
            _room_chat_sessions.pop(telegram_id, None)
            _store_chat_sessions.pop(telegram_id, None)
            _object_chat_sessions.pop(telegram_id, None)
            _room_chat_sessions.pop(target_tg_id, None)
            _store_chat_sessions.pop(target_tg_id, None)
            _object_chat_sessions.pop(target_tg_id, None)

            me_user = supabase.table("users_v1").select("username").eq("telegram_id", telegram_id).execute()
            my_name = f"@{me_user.data[0]['username']}" if me_user.data and me_user.data[0].get("username") else "?"

            tg_user = supabase.table("users_v1").select("username").eq("telegram_id", target_tg_id).execute()
            target_name = f"@{tg_user.data[0]['username']}" if tg_user.data and tg_user.data[0].get("username") else "?"

            await query.answer()
            await query.message.reply_text(
                T(lang, "chat_private_started", target_name),
                reply_markup=_exit_btn(lang)
            )
            try:
                await context.bot.send_message(
                    target_tg_id,
                    T(lang, "chat_private_notify", my_name),
                    reply_markup=_exit_btn(lang)
                )
            except Exception:
                pass

        # ── Exit chat ─────────────────────────────────────
        elif data == "chat_exit":
            _exit_all_chats(telegram_id)
            await query.answer()
            await query.message.reply_text(T(lang, "chat_exited"))

        else:
            await query.answer()

    except Exception:
        import traceback
        traceback.print_exc()
        try:
            await query.answer(T(lang, "error_answer"))
        except Exception:
            pass


# TOGGLE VISIBILITY
# =========================================================

async def toggle_visibility(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id, is_visible").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text(T(lang, "register_first"))
        return

    user_id = me.data[0]["id"]
    new_val = not me.data[0].get("is_visible", True)
    supabase.table("users_v1").update({"is_visible": new_val}).eq("id", user_id).execute()

    msg = T(lang, "account_visible") if new_val else T(lang, "account_hidden")
    await update.message.reply_text(msg)


# =========================================================
# TOGGLE PHONE VISIBILITY
# =========================================================

async def toggle_phone_visibility(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id, show_phone").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text(T(lang, "register_first"))
        return

    user_id = me.data[0]["id"]
    new_val = not me.data[0].get("show_phone", False)
    supabase.table("users_v1").update({"show_phone": new_val}).eq("id", user_id).execute()

    msg = T(lang, "phone_visible") if new_val else T(lang, "phone_hidden")
    await update.message.reply_text(msg)

# =========================================================
# CHAT STATE  (in-memory — lost on restart, acceptable)
# =========================================================

_room_chat_sessions:   dict = {}   # telegram_id → room_id
_store_chat_sessions:  dict = {}   # telegram_id → store_id
_object_chat_sessions: dict = {}   # telegram_id → object_id
_private_chats:        dict = {}   # telegram_id → target telegram_id


def _in_any_chat(tg_id: int) -> bool:
    return (tg_id in _room_chat_sessions
            or tg_id in _store_chat_sessions
            or tg_id in _object_chat_sessions
            or tg_id in _private_chats)


def _exit_all_chats(tg_id: int):
    _room_chat_sessions.pop(tg_id, None)
    _store_chat_sessions.pop(tg_id, None)
    _object_chat_sessions.pop(tg_id, None)
    _private_chats.pop(tg_id, None)


def _exit_btn(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(T(lang, "chat_btn_exit"), callback_data="chat_exit")
    ]])


# =========================================================
# SHOW ROOM CHATS LIST
# =========================================================

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle data sent via tg.sendData() from WebApp buttons."""
    data = update.message.web_app_data.data if update.message.web_app_data else ""
    lang = get_lang(update, context)
    tg_id = update.effective_user.id

    if data.startswith("room_chat_sel:"):
        try:
            room_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            return
        _room_chat_sessions[tg_id]  = room_id
        _store_chat_sessions.pop(tg_id, None)
        _private_chats.pop(tg_id, None)
        room_res  = supabase.table("rooms_v1").select("name").eq("id", room_id).execute()
        room_name = room_res.data[0]["name"] if room_res.data else "?"
        await update.message.reply_text(
            T(lang, "chat_room_joined", room_name),
            reply_markup=_exit_btn(lang)
        )

    elif data.startswith("store_chat_sel:"):
        try:
            store_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            return
        _store_chat_sessions[tg_id] = store_id
        _room_chat_sessions.pop(tg_id, None)
        _object_chat_sessions.pop(tg_id, None)
        _private_chats.pop(tg_id, None)
        store_res  = supabase.table("stores_v1").select("name").eq("id", store_id).execute()
        store_name = store_res.data[0]["name"] if store_res.data else "?"
        await update.message.reply_text(
            T(lang, "chat_store_joined", store_name),
            reply_markup=_exit_btn(lang)
        )

    elif data.startswith("object_chat_sel:"):
        try:
            object_id = int(data.split(":")[1])
        except (IndexError, ValueError):
            return
        _object_chat_sessions[tg_id] = object_id
        _room_chat_sessions.pop(tg_id, None)
        _store_chat_sessions.pop(tg_id, None)
        _private_chats.pop(tg_id, None)
        obj_res   = supabase.table("objects_v1").select("name").eq("id", object_id).execute()
        obj_name  = obj_res.data[0]["name"] if obj_res.data else "?"
        txt = (f"🗂️ دردشة كيان «{obj_name}»" if lang == "ar" else f"🗂️ Entity chat: «{obj_name}»")
        await update.message.reply_text(txt, reply_markup=_exit_btn(lang))


# =========================================================
# EXIT CHAT
# =========================================================

async def exit_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang  = get_lang(update, context)
    tg_id = update.effective_user.id
    _exit_all_chats(tg_id)
    await update.message.reply_text(T(lang, "chat_exited"), reply_markup=main_keyboard(lang, update.effective_user.id))


# =========================================================
# RELAY HELPERS
# =========================================================

async def _send_relayed(bot, target_chat_id: int, msg, header: str,
                        reply_markup=None):
    """Send any message type to target_chat_id with a header."""
    cap = lambda extra="": f"{header}\n\n{extra}".strip()

    if msg.sticker:
        await bot.send_message(target_chat_id, header, reply_markup=reply_markup)
        await bot.send_sticker(target_chat_id, msg.sticker.file_id)
    elif msg.photo:
        await bot.send_photo(target_chat_id, msg.photo[-1].file_id,
                             caption=cap(msg.caption or ""), reply_markup=reply_markup)
    elif msg.video:
        await bot.send_video(target_chat_id, msg.video.file_id,
                             caption=cap(msg.caption or ""), reply_markup=reply_markup)
    elif msg.document:
        await bot.send_document(target_chat_id, msg.document.file_id,
                                caption=cap(msg.caption or ""), reply_markup=reply_markup)
    elif msg.voice:
        await bot.send_voice(target_chat_id, msg.voice.file_id,
                             caption=cap(msg.caption or ""), reply_markup=reply_markup)
    elif msg.audio:
        await bot.send_audio(target_chat_id, msg.audio.file_id,
                             caption=cap(msg.caption or ""), reply_markup=reply_markup)
    elif msg.video_note:
        await bot.send_message(target_chat_id, header, reply_markup=reply_markup)
        await bot.send_video_note(target_chat_id, msg.video_note.file_id)
    elif msg.animation:
        await bot.send_animation(target_chat_id, msg.animation.file_id,
                                 caption=cap(msg.caption or ""), reply_markup=reply_markup)
    elif msg.text:
        await bot.send_message(target_chat_id, cap(msg.text), reply_markup=reply_markup)
    else:
        await bot.send_message(target_chat_id, header, reply_markup=reply_markup)


async def _get_room_member_tg_ids(room_id: int, exclude_my_id: int = -1) -> list:
    """Return telegram_ids of ALL room members (include sender for echo)."""
    memb = supabase.table("room_members_v1").select("user_id").eq("room_id", room_id).execute()
    targets = []
    for m in (memb.data or []):
        u = supabase.table("users_v1").select("telegram_id").eq("id", m["user_id"]).execute()
        if u.data:
            targets.append(u.data[0]["telegram_id"])
    return targets


async def _get_store_member_tg_ids(store_id: int, exclude_my_id: int = -1) -> list:
    """Return telegram_ids of ALL store followers (include sender for echo)."""
    memb = supabase.table("store_members_v1").select("user_id").eq("store_id", store_id).execute()
    targets = []
    for m in (memb.data or []):
        u = supabase.table("users_v1").select("telegram_id").eq("id", m["user_id"]).execute()
        if u.data:
            targets.append(u.data[0]["telegram_id"])
    return targets


async def _get_object_member_tg_ids(object_id: int) -> list:
    """Return telegram_ids of ALL object members."""
    memb = supabase.table("object_members_v1").select("user_id").eq("object_id", object_id).execute()
    targets = []
    for m in (memb.data or []):
        u = supabase.table("users_v1").select("telegram_id").eq("id", m["user_id"]).execute()
        if u.data:
            targets.append(u.data[0]["telegram_id"])
    return targets


# =========================================================
# RELAY ANY MESSAGE
# =========================================================

async def relay_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relay any message type when user is in an active chat session."""
    tg_id = update.effective_user.id
    msg   = update.message
    lang  = get_lang(update, context)

    # ── Not in any chat → restore main keyboard ───────────
    if not _in_any_chat(tg_id):
        kb_msg = "القائمة 👇" if lang == "ar" else "Menu 👇"
        await msg.reply_text(kb_msg, reply_markup=main_keyboard(lang, tg_id))
        return

    user_obj      = update.effective_user
    display_name  = f"@{user_obj.username}" if user_obj.username else (user_obj.full_name or "?")

    # ── Room group chat ──────────────────────────────────
    if tg_id in _room_chat_sessions:
        room_id  = _room_chat_sessions[tg_id]
        room_res = supabase.table("rooms_v1").select("name").eq("id", room_id).execute()
        room_name = room_res.data[0]["name"] if room_res.data else "?"

        targets = await _get_room_member_tg_ids(room_id)
        others  = [t for t in targets if t != tg_id]

        # Echo back to sender as confirmation
        sent_header = (f"✅ رسالتك — غرفة «{room_name}»"
                       if lang == "ar" else
                       f"✅ Your message — Room «{room_name}»")
        try:
            await _send_relayed(context.bot, tg_id, msg, sent_header, None)
        except Exception as e:
            logger.error(f"room echo → sender: {e}")

        if not others:
            note = ("ℹ️ لا يوجد أعضاء آخرون في الغرفة الآن."
                    if lang == "ar" else
                    "ℹ️ No other members in this room right now.")
            await msg.reply_text(note)
            return

        # Relay to other members with join + private buttons
        other_btns = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "💬 أدخل الدردشة" if lang == "ar" else "💬 Join Chat",
                callback_data=f"room_chat_sel:{room_id}"
            ),
            InlineKeyboardButton(T(lang, "chat_btn_private"), callback_data=f"priv_chat:{tg_id}")
        ]])
        header = T(lang, "chat_from", display_name, room_name)
        for t in others:
            try:
                await _send_relayed(context.bot, t, msg, header, other_btns)
            except Exception as e:
                logger.error(f"room relay → {t}: {e}")
        return

    # ── Store group chat ─────────────────────────────────
    if tg_id in _store_chat_sessions:
        store_id  = _store_chat_sessions[tg_id]
        store_res = supabase.table("stores_v1").select("name").eq("id", store_id).execute()
        store_name = store_res.data[0]["name"] if store_res.data else "?"

        targets = await _get_store_member_tg_ids(store_id)
        others  = [t for t in targets if t != tg_id]

        # Echo back to sender as confirmation
        sent_header = (f"✅ رسالتك — متجر «{store_name}»"
                       if lang == "ar" else
                       f"✅ Your message — Store «{store_name}»")
        try:
            await _send_relayed(context.bot, tg_id, msg, sent_header, None)
        except Exception as e:
            logger.error(f"store echo → sender: {e}")

        if not others:
            note = ("ℹ️ لا يوجد متابعون آخرون للمتجر الآن."
                    if lang == "ar" else
                    "ℹ️ No other store followers right now.")
            await msg.reply_text(note)
            return

        # Relay to other members with join + private buttons
        other_btns = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "💬 أدخل الدردشة" if lang == "ar" else "💬 Join Chat",
                callback_data=f"store_chat_sel:{store_id}"
            ),
            InlineKeyboardButton(T(lang, "chat_btn_private"), callback_data=f"priv_chat:{tg_id}")
        ]])
        header = T(lang, "chat_from_store", display_name, store_name)
        for t in others:
            try:
                await _send_relayed(context.bot, t, msg, header, other_btns)
            except Exception as e:
                logger.error(f"store relay → {t}: {e}")
        return

    # ── Object (entity) group chat ───────────────────────
    if tg_id in _object_chat_sessions:
        object_id  = _object_chat_sessions[tg_id]
        obj_res    = supabase.table("objects_v1").select("name").eq("id", object_id).execute()
        obj_name   = obj_res.data[0]["name"] if obj_res.data else "?"

        targets = await _get_object_member_tg_ids(object_id)
        others  = [t for t in targets if t != tg_id]

        sent_header = (f"✅ رسالتك — كيان «{obj_name}»"
                       if lang == "ar" else
                       f"✅ Your message — Entity «{obj_name}»")
        try:
            await _send_relayed(context.bot, tg_id, msg, sent_header, None)
        except Exception as e:
            logger.error(f"object echo → sender: {e}")

        if not others:
            note = ("ℹ️ لا يوجد أعضاء آخرون في الكيان الآن."
                    if lang == "ar" else
                    "ℹ️ No other members in this entity right now.")
            await msg.reply_text(note)
            return

        other_btns = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "💬 أدخل الدردشة" if lang == "ar" else "💬 Join Chat",
                callback_data=f"object_chat_sel:{object_id}"
            ),
            InlineKeyboardButton(T(lang, "chat_btn_private"), callback_data=f"priv_chat:{tg_id}")
        ]])
        header = (f"💬 {display_name} ← 🗂️ {obj_name}" if lang == "ar"
                  else f"💬 {display_name} → 🗂️ {obj_name}")
        for t in others:
            try:
                await _send_relayed(context.bot, t, msg, header, other_btns)
            except Exception as e:
                logger.error(f"object relay → {t}: {e}")
        return

    # ── Private chat ─────────────────────────────────────
    if tg_id in _private_chats:
        target_tg_id = _private_chats[tg_id]
        header   = T(lang, "chat_private_from", display_name)
        reply_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton(T(lang, "chat_btn_reply"), callback_data=f"priv_chat:{tg_id}")
        ]])
        try:
            await _send_relayed(context.bot, target_tg_id, msg, header, reply_btn)
        except Exception as e:
            logger.error(f"private relay → {target_tg_id}: {e}")
        return


# =========================================================
# HANDLE MESSAGES
# =========================================================

async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    if step:
        await handle_profile_steps(update, context)
        return

    tg_id = update.effective_user.id
    lang  = get_lang(update, context)
    text  = update.message.text

    # Exit chat button
    if text in ALL_BTN["exit_chat"]:
        await exit_chat(update, context)
        return

    # If in any chat session → relay the text message
    if _in_any_chat(tg_id):
        await relay_any_message(update, context)
        return

    # Catch-all: unknown message → restore main keyboard
    kb_msg = "القائمة 👇" if lang == "ar" else "Menu 👇"
    await update.message.reply_text(
        kb_msg,
        reply_markup=main_keyboard(lang, update.effective_user.id)
    )
