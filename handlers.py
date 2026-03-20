from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes
from database import supabase
from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, atan2
from config import BOT_TOKEN
import geohash2


# =========================================================
# HELPERS
# =========================================================

def detect_language(language_code):
    return "ar" if language_code and language_code.startswith("ar") else "en"


def time_ago(timestamp):
    if not timestamp:
        return "?"
    try:
        past = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - past).total_seconds())
        if diff < 60:
            return "الآن"
        elif diff < 3600:
            return f"{diff // 60} دقيقة"
        elif diff < 86400:
            return f"{diff // 3600} ساعة"
        else:
            return f"{diff // 86400} يوم"
    except Exception:
        return "?"


def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("📱 تسجيل الهاتف", request_contact=True)],
        [KeyboardButton("📍 مشاركة الموقع", request_location=True)],
        [KeyboardButton("👥 عرض الأقرب")],
        [KeyboardButton("🔥 التطابقات"), KeyboardButton("📥 طلباتي")],
        [KeyboardButton("👻 إخفاء حسابي"), KeyboardButton("📞 إظهار/إخفاء رقمي")]
    ]
    await update.message.reply_text(
        "🤍 Welcome to Always Close\n\nيرجى التسجيل للبدء:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


# =========================================================
# HANDLE CONTACT
# =========================================================

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    phone = update.message.contact.phone_number

    supabase.table("users_v1") \
        .update({"phone": phone}) \
        .eq("telegram_id", telegram_id) \
        .execute()

    await update.message.reply_text("📱 تم حفظ رقم الهاتف بنجاح ✅")


# =========================================================
# HANDLE LOCATION
# =========================================================

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    username = user.username
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    geo = geohash2.encode(lat, lon, precision=7)
    lang = detect_language(user.language_code)

    existing = supabase.table("users_v1") \
        .select("*") \
        .eq("telegram_id", telegram_id) \
        .execute()

    photos = await context.bot.get_user_profile_photos(telegram_id, limit=1)
    photo_url = None

    try:
        if photos.total_count > 0:
            file = await context.bot.get_file(photos.photos[0][0].file_id)
            photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    except Exception:
        photo_url = None

    if existing.data:
        user_id = existing.data[0]["id"]
        supabase.table("users_v1") \
            .update({
                "username": username,
                "photo_url": photo_url,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }) \
            .eq("id", user_id) \
            .execute()
    else:
        insert = supabase.table("users_v1") \
            .insert({
                "telegram_id": telegram_id,
                "username": username,
                "language": lang,
                "photo_url": photo_url,
                "is_active": True,
                "is_visible": True
            }) \
            .execute()

        if not insert.data:
            await update.message.reply_text("❌ خطأ في التسجيل.")
            return

        user_id = insert.data[0]["id"]

    supabase.table("user_locations_v1") \
        .insert({
            "user_id": user_id,
            "latitude": lat,
            "longitude": lon,
            "geohash": geo,
            "source": "GPS"
        }) \
        .execute()

    await update.message.reply_text("🚀 تم تحديث موقعك بنجاح!")


# =========================================================
# SHOW NEARBY
# =========================================================

async def show_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tg_id = update.effective_user.id

        user_res = supabase.table("users_v1") \
            .select("*") \
            .eq("telegram_id", tg_id) \
            .execute()

        if not user_res.data:
            await update.message.reply_text("❌ يجب التسجيل أولاً.")
            return

        my_user = user_res.data[0]
        my_id = my_user["id"]

        loc_res = supabase.table("user_locations_v1") \
            .select("*") \
            .eq("user_id", my_id) \
            .order("recorded_at", desc=True) \
            .limit(1) \
            .execute()

        if not loc_res.data:
            await update.message.reply_text("❌ يجب مشاركة موقعك أولاً.")
            return

        my_loc = loc_res.data[0]
        my_lat = my_loc["latitude"]
        my_lon = my_loc["longitude"]

        all_users = supabase.table("users_v1") \
            .select("id, username, age, gender, bio, photo_url, updated_at") \
            .eq("is_active", True) \
            .eq("is_visible", True) \
            .neq("id", my_id) \
            .execute()

        result = []

        for u in all_users.data:
            loc = supabase.table("user_locations_v1") \
                .select("latitude, longitude") \
                .eq("user_id", u["id"]) \
                .order("recorded_at", desc=True) \
                .limit(1) \
                .execute()

            if not loc.data:
                continue

            dist = calculate_distance(
                my_lat, my_lon,
                loc.data[0]["latitude"],
                loc.data[0]["longitude"]
            )
            u["distance"] = round(dist, 2)
            result.append(u)

        result.sort(key=lambda x: x["distance"])

        if not result:
            await update.message.reply_text("❌ لا يوجد أشخاص قريبين حالياً.")
            return

        context.user_data["nearby_list"] = result
        context.user_data["current_index"] = 0

        await send_profile_card(update.effective_chat.id, context)

    except Exception as e:
        print("ERROR IN SHOW_NEARBY:", e)
        await update.message.reply_text("❌ حدث خطأ، حاول مرة أخرى.")


# =========================================================
# SEND PROFILE CARD
# =========================================================

async def send_profile_card(chat_id, context):
    data = context.user_data.get("nearby_list", [])
    idx = context.user_data.get("current_index", 0)

    if not data or idx >= len(data):
        await context.bot.send_message(chat_id, "انتهت قائمة المستخدمين القريبين.")
        return

    user = data[idx]

    name = user.get("username") or "مستخدم"
    dist = user.get("distance", 0)
    age = user.get("age") or "?"
    gender = user.get("gender") or "غير محدد"
    last_seen = time_ago(user.get("updated_at"))
    status = "🟢 نشط الآن" if last_seen == "الآن" else f"🕒 منذ {last_seen}"

    caption = (
        f"<b>{name}</b> | {age} سنة\n"
        f"⚥ {gender}\n"
        f"📍 {dist} كم\n"
        f"{status}"
    )

    keyboard = [
        [
            InlineKeyboardButton("⏮️ السابق", callback_data="prev"),
            InlineKeyboardButton("⏭️ التالي", callback_data="next"),
        ],
        [
            InlineKeyboardButton("❤️ إعجاب", callback_data=f"like_{user['id']}"),
            InlineKeyboardButton("⭐ سوبر", callback_data=f"superlike_{user['id']}"),
            InlineKeyboardButton("❌ تخطي", callback_data="skip"),
        ]
    ]

    if user.get("username"):
        keyboard.append([
            InlineKeyboardButton("💬 مراسلة", url=f"https://t.me/{user['username']}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    photo = user.get("photo_url")

    if photo:
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="HTML",
            reply_markup=reply_markup
        )


# =========================================================
# HANDLE BUTTONS
# =========================================================

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    telegram_id = query.from_user.id
    data = query.data
    chat_id = query.message.chat.id
    idx = context.user_data.get("current_index", 0)

    if data == "next":
        context.user_data["current_index"] = idx + 1
        await send_profile_card(chat_id, context)

    elif data == "prev":
        context.user_data["current_index"] = max(0, idx - 1)
        await send_profile_card(chat_id, context)

    elif data == "skip":
        context.user_data["current_index"] = idx + 1
        await send_profile_card(chat_id, context)

    elif data.startswith("like_"):
        target_id = int(data.split("_")[1])

        me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
        if not me.data:
            return

        my_id = me.data[0]["id"]

        supabase.table("likes_v1").insert({
            "from_user_id": my_id,
            "to_user_id": target_id
        }).execute()

        mutual = supabase.table("likes_v1") \
            .select("*") \
            .eq("from_user_id", target_id) \
            .eq("to_user_id", my_id) \
            .execute()

        if mutual.data:
            match_exists = supabase.table("matches_v1") \
                .select("*") \
                .or_(
                    f"and(user1_id.eq.{my_id},user2_id.eq.{target_id}),"
                    f"and(user1_id.eq.{target_id},user2_id.eq.{my_id})"
                ).execute()

            if not match_exists.data:
                supabase.table("matches_v1").insert({
                    "user1_id": my_id,
                    "user2_id": target_id
                }).execute()

            await context.bot.send_message(chat_id, "🎉 تم التطابق! يمكنكما التواصل الآن.")
        else:
            await query.answer("تم الإعجاب ❤️", show_alert=False)

        context.user_data["current_index"] = idx + 1
        await send_profile_card(chat_id, context)

    elif data.startswith("superlike_"):
        await query.answer("⭐ سوبر لايك!", show_alert=True)
        context.user_data["current_index"] = idx + 1
        await send_profile_card(chat_id, context)


# =========================================================
# SHOW MATCHES
# =========================================================

async def show_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text("يجب التسجيل أولاً.")
        return

    my_id = me.data[0]["id"]

    matches = supabase.table("matches_v1") \
        .select("*") \
        .or_(f"user1_id.eq.{my_id},user2_id.eq.{my_id}") \
        .execute()

    if not matches.data:
        await update.message.reply_text("لا يوجد تطابقات بعد 🔥")
        return

    text = "🔥 تطابقاتك:\n\n"
    for m in matches.data:
        other_id = m["user2_id"] if m["user1_id"] == my_id else m["user1_id"]
        other = supabase.table("users_v1").select("username").eq("id", other_id).execute()
        if other.data:
            uname = other.data[0].get("username") or "مجهول"
            text += f"• @{uname}\n"

    await update.message.reply_text(text)


# =========================================================
# SHOW REQUESTS
# =========================================================

async def show_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text("يجب التسجيل أولاً.")
        return

    my_id = me.data[0]["id"]

    likes = supabase.table("likes_v1") \
        .select("from_user_id") \
        .eq("to_user_id", my_id) \
        .execute()

    if not likes.data:
        await update.message.reply_text("لا يوجد طلبات إعجاب بعد 📥")
        return

    text = "📥 الأشخاص الذين أعجبوا بك:\n\n"
    for like in likes.data:
        sender = supabase.table("users_v1").select("username").eq("id", like["from_user_id"]).execute()
        if sender.data:
            uname = sender.data[0].get("username") or "مجهول"
            text += f"• @{uname}\n"

    await update.message.reply_text(text)


# =========================================================
# TOGGLE VISIBILITY
# =========================================================

async def toggle_visibility(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id, is_visible").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text("يجب التسجيل أولاً.")
        return

    user_id = me.data[0]["id"]
    new_val = not me.data[0].get("is_visible", True)

    supabase.table("users_v1").update({"is_visible": new_val}).eq("id", user_id).execute()

    msg = "✅ حسابك مرئي الآن." if new_val else "👻 تم إخفاء حسابك."
    await update.message.reply_text(msg)


# =========================================================
# TOGGLE PHONE VISIBILITY
# =========================================================

async def toggle_phone_visibility(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id, show_phone").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text("يجب التسجيل أولاً.")
        return

    user_id = me.data[0]["id"]
    new_val = not me.data[0].get("show_phone", False)

    supabase.table("users_v1").update({"show_phone": new_val}).eq("id", user_id).execute()

    msg = "📞 رقمك مرئي الآن." if new_val else "🔒 تم إخفاء رقمك."
    await update.message.reply_text(msg)
