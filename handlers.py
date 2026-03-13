from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ContextTypes

from database import supabase
from helpers import calculate_distance
from datetime import datetime, timezone
from config import BOT_TOKEN


# =========================================================
# HELPERS
# =========================================================

def detect_language(language_code):
    if language_code and language_code.startswith("ar"):
        return "ar"
    return "en"


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
# HANDLE PHONE
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
    lang = detect_language(user.language_code)

    existing = supabase.table("users_v1") \
        .select("*") \
        .eq("telegram_id", telegram_id) \
        .execute()

    photos = await context.bot.get_user_profile_photos(telegram_id, limit=1)
    photo_url = None

    if photos.total_count > 0:
        file = await context.bot.get_file(photos.photos[0][0].file_id)
        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

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

        if insert.data:
            user_id = insert.data[0]["id"]
        else:
            await update.message.reply_text("❌ حدث خطأ أثناء التسجيل.")
            return

    supabase.table("user_locations_v1") \
        .insert({
            "user_id": user_id,
            "latitude": lat,
            "longitude": lon,
            "source": "GPS"
        }) \
        .execute()

    await update.message.reply_text("🚀 تم تحديث موقعك بنجاح!")


# =========================================================
# SHOW NEARBY
# =========================================================

async def show_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1") \
        .select("*") \
        .eq("telegram_id", telegram_id) \
        .execute()

    if not me.data:
        await update.message.reply_text("يجب التسجيل أولاً.")
        return

    my_user = me.data[0]
    my_id = my_user["id"]

    my_location = supabase.table("user_locations_v1") \
        .select("latitude, longitude") \
        .eq("user_id", my_id) \
        .order("recorded_at", desc=True) \
        .limit(1) \
        .execute()

    if not my_location.data:
        await update.message.reply_text("يجب مشاركة موقعك أولاً.")
        return

    my_lat = my_location.data[0]["latitude"]
    my_lon = my_location.data[0]["longitude"]

    all_users = supabase.table("users_v1") \
        .select("id, username, age, gender, bio, photo_url, updated_at") \
        .eq("is_active", True) \
        .eq("is_visible", True) \
        .neq("id", my_id) \
        .execute()

    results = []

    for u in all_users.data:
        loc = supabase.table("user_locations_v1") \
            .select("latitude, longitude") \
            .eq("user_id", u["id"]) \
            .order("recorded_at", desc=True) \
            .limit(1) \
            .execute()

        if not loc.data:
            continue

        distance = calculate_distance(
            my_lat, my_lon,
            loc.data[0]["latitude"],
            loc.data[0]["longitude"]
        )
        u["distance"] = round(distance, 2)
        results.append(u)

    results.sort(key=lambda x: x["distance"])

    if not results:
        await update.message.reply_text("لا يوجد مستخدمين قريبين حالياً.")
        return

    context.user_data["nearby_users"] = results
    context.user_data["index"] = 0

    await send_user_card(update.effective_chat.id, context)


# =========================================================
# SEND USER CARD
# =========================================================

async def send_user_card(chat_id, context):
    users = context.user_data.get("nearby_users", [])
    index = context.user_data.get("index", 0)

    if index >= len(users):
        await context.bot.send_message(chat_id, "انتهت قائمة المستخدمين القريبين.")
        return

    user = users[index]

    last_seen = time_ago(user.get("updated_at"))
    status = "🟢 نشط الآن" if last_seen == "الآن" else f"🕒 منذ {last_seen}"
    age = user.get("age") or "?"
    gender = user.get("gender") or "غير محدد"
    distance = user.get("distance", "?")

    caption = (
        f"<b>{user.get('username', 'مستخدم')}</b> | {age} سنة\n"
        f"⚥ {gender}\n"
        f"📍 {distance} كم\n"
        f"{status}"
    )

    keyboard = [
        [
            InlineKeyboardButton("❤️ إعجاب", callback_data=f"like_{user['id']}"),
            InlineKeyboardButton("⏭ التالي", callback_data="next")
        ]
    ]

    if user.get("username"):
        keyboard.append([
            InlineKeyboardButton("💬 تواصل", url=f"https://t.me/{user['username']}")
        ])

    if user.get("photo_url"):
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=user["photo_url"],
            caption=caption,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================================================
# HANDLE BUTTONS (LIKE + MATCH + NEXT)
# =========================================================

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    telegram_id = query.from_user.id

    me = supabase.table("users_v1") \
        .select("id") \
        .eq("telegram_id", telegram_id) \
        .execute()

    if not me.data:
        return

    my_id = me.data[0]["id"]

    if query.data.startswith("like_"):
        target_id = int(query.data.split("_")[1])

        supabase.table("likes_v1") \
            .insert({
                "from_user_id": my_id,
                "to_user_id": target_id
            }) \
            .execute()

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
                ) \
                .execute()

            if not match_exists.data:
                supabase.table("matches_v1") \
                    .insert({
                        "user1_id": my_id,
                        "user2_id": target_id
                    }) \
                    .execute()

                old_caption = query.message.caption or query.message.text or ""
                new_caption = old_caption + "\n\n🎉 تم التطابق! يمكنكما التواصل الآن."

                try:
                    await query.edit_message_caption(
                        caption=new_caption,
                        parse_mode="HTML"
                    )
                except Exception:
                    await query.message.reply_text("🎉 تم التطابق! يمكنكما التواصل الآن.")
            else:
                await query.answer("أنتما متطابقان بالفعل! 🎉", show_alert=True)
        else:
            await query.answer("تم الإعجاب ❤️")

    elif query.data == "next":
        context.user_data["index"] = context.user_data.get("index", 0) + 1
        await send_user_card(query.message.chat.id, context)


# =========================================================
# MENU HANDLERS
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
            uname = other.data[0].get("username", "مجهول")
            text += f"• @{uname}\n"

    await update.message.reply_text(text)


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
            uname = sender.data[0].get("username", "مجهول")
            text += f"• @{uname}\n"

    await update.message.reply_text(text)


async def toggle_visibility(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id, is_visible").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text("يجب التسجيل أولاً.")
        return

    user_id = me.data[0]["id"]
    current = me.data[0].get("is_visible", True)
    new_val = not current

    supabase.table("users_v1").update({"is_visible": new_val}).eq("id", user_id).execute()

    msg = "✅ حسابك مرئي الآن." if new_val else "👻 تم إخفاء حسابك."
    await update.message.reply_text(msg)


async def toggle_phone_visibility(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1").select("id, show_phone").eq("telegram_id", telegram_id).execute()
    if not me.data:
        await update.message.reply_text("يجب التسجيل أولاً.")
        return

    user_id = me.data[0]["id"]
    current = me.data[0].get("show_phone", False)
    new_val = not current

    supabase.table("users_v1").update({"show_phone": new_val}).eq("id", user_id).execute()

    msg = "📞 رقمك مرئي الآن." if new_val else "🔒 تم إخفاء رقمك."
    await update.message.reply_text(msg)
