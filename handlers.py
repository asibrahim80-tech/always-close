# ==============================
# Always Close - Handlers
# ==============================

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


# ==============================
# Language Detection
# ==============================

def detect_language(language_code):
    if language_code and language_code.startswith("ar"):
        return "ar"
    return "en"


# ==============================
# Time Ago Helper
# ==============================

def time_ago(timestamp):
    if not timestamp:
        return "غير معروف"

    try:
        past = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        if past.tzinfo is None:
            past = past.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = now - past

        seconds = int(diff.total_seconds())

        if seconds < 60:
            return "الآن"
        elif seconds < 3600:
            return f"{seconds // 60} دقيقة"
        elif seconds < 86400:
            return f"{seconds // 3600} ساعة"
        else:
            return f"{seconds // 86400} يوم"
    except:
        return "غير معروف"

    

# ==============================
# Start
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    location_button= KeyboardButton("📍 Share Location", request_location=True)
    keyboard = [[location_button]]

    await update.message.reply_text(
        "🤍 Welcome to Always Close\n\nPlease share your location to begin 📍",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    
    from telegram import ReplyKeyboardMarkup, KeyboardButton

    keyboard = [
        [KeyboardButton("📍 مشاركة الموقع", request_location=True)],
        [KeyboardButton("📱 مشاركة رقم الهاتف", request_contact=True)]
    ]

    await update.message.reply_text(
        "يرجى مشاركة الموقع ورقم الهاتف لإكمال التسجيل:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )

# ==============================
# Handle Location (Insert / Update Smart)
# ==============================

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):

user = update.effective_user
telegram_id = user.id
username = user.username
lat = update.message.location.latitude
lon = update.message.location.longitude

detected_lang = detect_language(user.language_code)

# 🔎 Check if user exists
existing = supabase.table("users_v1") \
    .select("id") \
    .eq("telegram_id", telegram_id) \
    .execute()

# 📷 Get Telegram profile photo
photos = await context.bot.get_user_profile_photos(telegram_id, limit=1)

photo_url = None

if photos.total_count > 0:
    file = await context.bot.get_file(photos.photos[0][0].file_id)
    photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

# 👤 Insert or Update user
if existing.data:
    user_db_id = existing.data[0]["id"]

    supabase.table("users_v1") \
        .update({
            "username": username,
            "language": detected_lang,
            "updated_at": datetime.utcnow().isoformat()
        }) \
        .eq("id", user_db_id) \
        .execute()

else:
    insert = supabase.table("users_v1") \
        .insert({
            "telegram_id": telegram_id,
            "username": username,
            "language": detected_lang,
            "photo_url": photo_url
        }) \
        .execute()

    user_db_id = insert.data[0]["id"]

# 📍 Save location
supabase.table("user_locations_v1") \
    .insert({
        "user_id": user_db_id,
        "latitude": lat,
        "longitude": lon,
        "source": "GPS"
    }) \
    .execute()

keyboard = [
    [InlineKeyboardButton("✅ Confirm Account", callback_data="confirm")],
    [InlineKeyboardButton("❌ Cancel Registration", callback_data="cancel")]
]

if photo_url:
    await update.message.reply_photo(
        photo=photo_url,
        caption="Account created 👇\n\nDo you want to activate your profile?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
else:
    await update.message.reply_text(
        "Account created 👇\n\nDo you want to activate your profile?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
# ==============================
# Handle Buttons
# ==============================

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data == "confirm":

        supabase.table("users_v1") \
            .update({
                "is_active": True,
                "profile_completed": True
            }) \
            .eq("telegram_id", user_id) \
            .execute()

        keyboard = [[KeyboardButton("👥 عرض الأقرب")]]

        await query.edit_message_text("🎉 Setup completed successfully!")

        await context.bot.send_message(
            chat_id=user_id,
            text="اختر:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

    elif query.data == "cancel":

        supabase.table("users").delete() \
            .eq("telegram_id", user_id).execute()

        await query.edit_message_text("Registration cancelled ❌")

    elif query.data == "next_user":

        users = context.user_data.get("nearby_users", [])
        index = context.user_data.get("current_index", 0)

        if index >= len(users):
            await query.edit_message_caption("لا يوجد المزيد حالياً.")
            return

        user_data = users[index]
        context.user_data["current_index"] = index + 1

        await send_user_card(query.message.chat_id, context, user_data)

    
        users = context.user_data.get("nearby_users", [])
        index = context.user_data.get("current_index", 0) + 1

        if index >= len(users):
            await query.answer()
            await query.edit_message_caption(
                caption="لا يوجد مستخدمين متصلين بالقرب منك الآن.",
                reply_markup=None
            )
            return

        context.user_data["current_index"] = index

        await send_user_card(query.message.chat.id, context, users[index])


# ==============================
# Show Nearby (Distance + Pagination Memory)
# ==============================

async def show_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE):

        telegram_id = update.effective_user.id

        # Get my user from users_v1
        me = supabase.table("users_v1") \
            .select("id, username") \
            .eq("telegram_id", telegram_id) \
            .execute()

        if not me.data:
            await update.message.reply_text("يجب التسجيل أولًا.")
            return

        my_user = me.data[0]
        my_id = my_user["id"]

        # Get my last location
        my_location = supabase.table("user_locations_v1") \
            .select("latitude, longitude") \
            .eq("user_id", my_id) \
            .order("recorded_at", desc=True) \
            .limit(1) \
            .execute()

        if not my_location.data:
            await update.message.reply_text("لم يتم العثور على موقعك.")
            return

        my_lat = my_location.data[0]["latitude"]
        my_lon = my_location.data[0]["longitude"]

        # Get all other users locations
        all_locations = supabase.table("user_locations_v1") \
            .select("user_id, latitude, longitude") \
            .neq("user_id", my_id) \
            .execute()

        if not all_locations.data:
            await update.message.reply_text("لا يوجد مستخدمين حالياً.")
            return

        results = []

        for loc in all_locations.data:

            distance = calculate_distance(
                my_lat,
                my_lon,
                loc["latitude"],
                loc["longitude"]
            )

            # Get user info
            user_info = supabase.table("users_v1") \
                .select("username, age, gender, bio, photo_url") \
                .eq("id", loc["user_id"]) \
                .execute()

            if user_info.data:
                user_data = user_info.data[0]
                user_data["distance"] = round(distance, 2)
                results.append(user_data)

        results.sort(key=lambda x: x["distance"])

        if not results:
            await update.message.reply_text("لا يوجد مستخدمين قريبين.")
            return

        context.user_data["nearby_users"] = results
        context.user_data["current_index"] = 0

        await send_user_card(update.effective_chat.id, context, results[0])


# ==============================
# Send User Card
# ==============================

async def send_user_card(chat_id, context, user_data):

    last_seen = time_ago(user_data.get("last_update"))

    caption_text = f"""
    <b>{user['username']}</b> | {user.get('age','?')} سنة
    📍 {user['distance']} كم
    🟢 نشط الآن
    """


    keyboard = [
        [
            InlineKeyboardButton(
                "💬 تواصل",
                url=f"https://t.me/{user_data['username']}"
            ) if user_data.get("username") else None
        ],
        [
            InlineKeyboardButton("⏭ التالي", callback_data="next_user")
        ]
    ]

    keyboard = [[btn for btn in row if btn] for row in keyboard]

    if user_data.get("photo_url"):
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=user_data["photo_url"],
            caption=caption,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        if user.get("photo_url"):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=user["photo_url"],
                caption=caption_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=caption_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )


# ==============================
# Handle phone
# ==============================

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):

    telegram_id = update.effective_user.id
    phone = update.message.contact.phone_number

supabase.table("users_v1") \
    .update({"phone": phone}) \
    .eq("telegram_id", telegram_id) \
    .execute()

await update.message.reply_text("تم حفظ رقم الهاتف بنجاح ✅")
