import os
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

DOMAIN = os.environ.get("REPLIT_DEV_DOMAIN", "")


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

def main_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        [KeyboardButton(T(lang, "btn_share_phone"), request_contact=True)],
        [KeyboardButton(T(lang, "btn_share_location"), request_location=True)],
        [KeyboardButton(T(lang, "btn_map")), KeyboardButton(T(lang, "btn_users_list"))],
        [KeyboardButton(T(lang, "btn_rooms_nearby")), KeyboardButton(T(lang, "btn_create_room"))],
        [KeyboardButton(T(lang, "btn_view_nearby"))],
        [KeyboardButton(T(lang, "btn_matches")), KeyboardButton(T(lang, "btn_requests"))],
        [KeyboardButton(T(lang, "btn_hide")), KeyboardButton(T(lang, "btn_phone_toggle"))],
        [KeyboardButton(T(lang, "btn_edit")), KeyboardButton(T(lang, "btn_settings"))],
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
    tg_id = update.effective_user.id
    lang = detect_lang(update.effective_user.language_code)
    context.user_data["lang"] = lang

    user = supabase.table("users_v1").select("id, language").eq("telegram_id", tg_id).execute()

    if not user.data:
        # New user — start profile setup
        context.user_data["step"] = "gender"
        await update.message.reply_text(
            T(lang, "welcome_new"),
            reply_markup=ReplyKeyboardMarkup(
                [[T(lang, "btn_male"), T(lang, "btn_female")]],
                resize_keyboard=True
            )
        )
    else:
        # Returning user — update language in DB if changed
        stored_lang = user.data[0].get("language") or "en"
        if stored_lang != lang:
            supabase.table("users_v1").update({"language": lang}).eq("telegram_id", tg_id).execute()
        context.user_data["lang"] = lang
        await update.message.reply_text(
            T(lang, "welcome_back"),
            reply_markup=main_keyboard(lang)
        )


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
        await update.message.reply_text(T(lang, "profile_saved"), reply_markup=main_keyboard(lang))
        return

    elif step == "edit_gender":
        supabase.table("users_v1").update({
            "gender": normalize_gender(text, lang)
        }).eq("telegram_id", update.effective_user.id).execute()
        context.user_data.clear()
        context.user_data["lang"] = lang
        await update.message.reply_text(T(lang, "updated"), reply_markup=main_keyboard(lang))
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
            await update.message.reply_text(T(lang, "updated"), reply_markup=main_keyboard(lang))
        except Exception:
            await update.message.reply_text(T(lang, "invalid_date"))
        return

    elif step == "edit_bio":
        supabase.table("users_v1").update({
            "bio": text
        }).eq("telegram_id", update.effective_user.id).execute()
        context.user_data.clear()
        context.user_data["lang"] = lang
        await update.message.reply_text(T(lang, "updated"), reply_markup=main_keyboard(lang))
        return

    elif step == "create_room_name":
        if text in ALL_BTN.get("cancel_action", []):
            context.user_data.clear()
            context.user_data["lang"] = lang
            await update.message.reply_text(T(lang, "room_cancel"), reply_markup=main_keyboard(lang))
            return
        context.user_data["room_name"] = text.strip()
        context.user_data["step"] = "create_room_purpose"
        await update.message.reply_text(
            T(lang, "create_room_ask_purpose"),
            reply_markup=ReplyKeyboardMarkup(
                [[T(lang, "btn_cancel_action")]], resize_keyboard=True
            )
        )
        return

    elif step == "create_room_purpose":
        if text in ALL_BTN.get("cancel_action", []):
            context.user_data.clear()
            context.user_data["lang"] = lang
            await update.message.reply_text(T(lang, "room_cancel"), reply_markup=main_keyboard(lang))
            return
        tg_id = update.effective_user.id
        room_name    = context.user_data.get("room_name", "Room")
        room_purpose = text.strip()

        # Clear step FIRST so bot never gets stuck
        context.user_data.clear()
        context.user_data["lang"] = lang

        me = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()
        if not me.data:
            await update.message.reply_text(T(lang, "register_first"), reply_markup=main_keyboard(lang))
            return

        creator_id = me.data[0]["id"]
        try:
            result = supabase.table("rooms_v1").insert({
                "name": room_name,
                "purpose": room_purpose,
                "creator_id": creator_id,
                "is_active": True,
            }).execute()
            rows = result.data or []
            if rows:
                room_id = rows[0]["id"]
                try:
                    supabase.table("room_members_v1").insert({
                        "room_id": room_id,
                        "user_id": creator_id,
                        "status": "accepted",
                    }).execute()
                except Exception:
                    pass
            await update.message.reply_text(
                T(lang, "room_created").format(room_name, room_purpose),
                reply_markup=main_keyboard(lang)
            )
        except Exception as e:
            logger.error(f"Room creation error: {e}")
            await update.message.reply_text(T(lang, "room_create_error"), reply_markup=main_keyboard(lang))
        return


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

    # UPDATE location record instead of inserting a new one each time
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
# SHOW NEARBY
# =========================================================

async def show_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    try:
        tg_id = update.effective_user.id
        chat_id = update.effective_chat.id

        me = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()
        if not me.data:
            await update.message.reply_text(T(lang, "register_first"))
            return

        my_id = me.data[0]["id"]

        loc_res = supabase.table("user_locations_v1") \
            .select("latitude, longitude") \
            .eq("user_id", my_id) \
            .limit(1) \
            .execute()

        if not loc_res.data:
            await update.message.reply_text(T(lang, "share_location_first"))
            return

        my_lat = loc_res.data[0]["latitude"]
        my_lon = loc_res.data[0]["longitude"]

        all_users = supabase.table("users_v1") \
            .select("id, username, age, gender, bio, photo_url, language, created_at") \
            .eq("is_active", True) \
            .eq("is_visible", True) \
            .neq("id", my_id) \
            .execute()

        result = []
        for u in all_users.data:
            loc = supabase.table("user_locations_v1") \
                .select("latitude, longitude, recorded_at") \
                .eq("user_id", u["id"]) \
                .limit(1) \
                .execute()

            if not loc.data:
                continue

            dist = calculate_distance(
                my_lat, my_lon,
                loc.data[0]["latitude"],
                loc.data[0]["longitude"]
            )
            u["distance"]  = round(dist, 2)
            u["last_seen"] = loc.data[0].get("recorded_at")
            result.append(u)

        if not result:
            await update.message.reply_text(T(lang, "no_nearby"))
            return

        result.sort(key=lambda x: x["distance"])

        context.user_data["nearby_list"] = result
        context.user_data["current_index"] = 0

        await send_profile_card(context, chat_id, result[0], lang)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await update.message.reply_text(T(lang, "error"))


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

        else:
            await query.answer()

    except Exception:
        import traceback
        traceback.print_exc()
        try:
            await query.answer(T(lang, "error_answer"))
        except Exception:
            pass


# =========================================================
# SHOW MATCHES
# =========================================================

async def show_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text(T(lang, "register_first"))
        return

    my_id = me.data[0]["id"]

    matches = supabase.table("matches_v1") \
        .select("user1_id, user2_id") \
        .or_(f"user1_id.eq.{my_id},user2_id.eq.{my_id}") \
        .execute()

    if not matches.data:
        await update.message.reply_text(T(lang, "no_matches"))
        return

    text = T(lang, "matches_title")
    for m in matches.data:
        other_id = m["user2_id"] if m["user1_id"] == my_id else m["user1_id"]
        other = supabase.table("users_v1").select("username").eq("id", other_id).execute()
        if other.data:
            uname = other.data[0].get("username") or T(lang, "unknown_label")
            text += f"• @{uname}\n"

    await update.message.reply_text(text)


# =========================================================
# SHOW REQUESTS (who liked me)
# =========================================================

async def show_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text(T(lang, "register_first"))
        return

    my_id = me.data[0]["id"]

    likes = supabase.table("likes_v1") \
        .select("from_user_id") \
        .eq("to_user_id", my_id) \
        .execute()

    if not likes.data:
        await update.message.reply_text(T(lang, "no_requests"))
        return

    text = T(lang, "requests_title")
    for like in likes.data:
        sender = supabase.table("users_v1").select("username").eq("id", like["from_user_id"]).execute()
        if sender.data:
            uname = sender.data[0].get("username") or T(lang, "unknown_label")
            text += f"• @{uname}\n"

    await update.message.reply_text(text)


# =========================================================
# SHOW MAP
# =========================================================

async def show_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    tg_id = update.effective_user.id

    # Verify user exists
    me = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()
    if not me.data:
        await update.message.reply_text(T(lang, "map_not_registered"))
        return

    my_id = me.data[0]["id"]

    # Verify location exists
    loc = supabase.table("user_locations_v1") \
        .select("id") \
        .eq("user_id", my_id) \
        .limit(1) \
        .execute()

    if not loc.data:
        await update.message.reply_text(T(lang, "map_no_location"))
        return

    map_url = f"https://{DOMAIN}/map?uid={tg_id}&lang={lang}"

    await update.message.reply_text(
        T(lang, "map_tap"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                T(lang, "map_btn_open"),
                web_app=WebAppInfo(url=map_url),
            )
        ]])
    )


# =========================================================
# SHOW USERS LIST
# =========================================================

async def show_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    tg_id = update.effective_user.id

    me = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()
    if not me.data:
        await update.message.reply_text(T(lang, "users_not_registered"))
        return

    my_id = me.data[0]["id"]

    loc = supabase.table("user_locations_v1") \
        .select("id") \
        .eq("user_id", my_id) \
        .limit(1) \
        .execute()

    if not loc.data:
        await update.message.reply_text(T(lang, "users_no_location"))
        return

    users_url = f"https://{DOMAIN}/users?uid={tg_id}&lang={lang}"

    await update.message.reply_text(
        T(lang, "users_tap"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                T(lang, "users_btn_open"),
                web_app=WebAppInfo(url=users_url),
            )
        ]])
    )


# =========================================================
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
# SHOW NEARBY ROOMS
# =========================================================

async def show_nearby_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    tg_id = update.effective_user.id

    # get user id
    me = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()
    if not me.data:
        await update.message.reply_text("❌ Register first")
        return

    my_id = me.data[0]["id"]

    # get location
    loc = supabase.table("user_locations_v1") \
        .select("latitude, longitude") \
        .eq("user_id", my_id) \
        .limit(1) \
        .execute()

    if not loc.data:
        await update.message.reply_text("📍 Share location first")
        return

    lat = loc.data[0]["latitude"]
    lng = loc.data[0]["longitude"]

    # call RPC function
    try:
        res = supabase.rpc("get_nearby_rooms", {
            "user_lat": lat,
            "user_lng": lng
        }).execute()

        rooms = res.data

    except Exception as e:
        print(e)
        await update.message.reply_text("❌ Error loading rooms")
        return

    if not rooms:
        await update.message.reply_text("❌ No rooms nearby")
        return

    text = "📍 Nearby Rooms:\n\n"

    for r in rooms:
        text += f"💬 {r['name']} ({r['members']} people)\n"

    await update.message.reply_text(text)

# =========================================================
# SETTINGS
# =========================================================

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    tg_id = update.effective_user.id
    settings_url = f"https://{DOMAIN}/settings?uid={tg_id}&lang={lang}"
    await update.message.reply_text(
        T(lang, "settings_tap"),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                T(lang, "settings_btn_open"),
                web_app=WebAppInfo(url=settings_url)
            )
        ]])
    )


# =========================================================
# CREATE ROOM
# =========================================================

async def create_room_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(update, context)
    tg_id = update.effective_user.id

    me = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()
    if not me.data:
        await update.message.reply_text(T(lang, "register_first"))
        return

    context.user_data["step"] = "create_room_name"
    await update.message.reply_text(
        T(lang, "create_room_ask_name"),
        reply_markup=ReplyKeyboardMarkup(
            [[T(lang, "btn_cancel_action")]], resize_keyboard=True
        )
    )


# =========================================================
# HANDLE MESSAGES
# =========================================================

async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    if step:
        await handle_profile_steps(update, context)
        return

    lang = get_lang(update, context)
    text = update.message.text

    if text in ALL_BTN["rooms_nearby"]:
        await show_nearby_rooms(update, context)
        return

    # Catch-all: unknown message → restore main keyboard
    await update.message.reply_text(
        "👋",
        reply_markup=main_keyboard(lang)
    )
