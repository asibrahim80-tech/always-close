# =========================================================
# Always Close - Core V2 (Matching + Pagination + Filters)
# =========================================================

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

#=====================================
# PROFILE STATES
#=====================================

PROFILE_AGE = 1
PROFILE_GENDER = 2
PROFILE_BIO = 3

# =========================================================
# LANGUAGE
# =========================================================

def detect_language(language_code):
    if language_code and language_code.startswith("ar"):
        return "ar"
    return "en"

#=====================================
# TEXT SYSTEM
#=====================================

def get_text(lang, key):

    texts = {
        "ar": {
            "welcome": "🤍 أهلاً بك في Always Close",
            "register": "يرجى التسجيل للبدء:",
            "no_users": "لا يوجد مستخدمين قريبين حالياً.",
            "active_now": "🟢 نشط الآن",
            "years": "سنة",
            "distance": "كم",
            "like": "❤️ إعجاب",
            "next": "⏭ التالي",
            "contact": "💬 تواصل",
            "matches": "🔥 التطابقات",
            "requests": "📥 طلباتي",
            "hide_account": "👻 إخفاء حسابي",
            "toggle_phone": "📞 إظهار/إخفاء رقمي"
        },
        "en": {
            "welcome": "🤍 Welcome to Always Close",
            "register": "Please register to continue:",
            "no_users": "No nearby users found.",
            "active_now": "🟢 Active now",
            "years": "years",
            "distance": "km",
            "like": "❤️ Like",
            "next": "⏭ Next",
            "contact": "💬 Message",
            "matches": "🔥 Matches",
            "requests": "📥 Requests",
            "hide_account": "👻 Hide Account",
            "toggle_phone": "📞 Show/Hide Phone"
        }
    }

    return texts.get(lang, texts["en"]).get(key, key)

# =========================================================
# TIME
# =========================================================

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
    except:
        return "?"


#=====================================
# START
#=====================================
    
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    lang = detect_language(user.language_code)

    keyboard = [
        [KeyboardButton("📱 تسجيل الهاتف" if lang == "ar" else "📱 Register Phone", request_contact=True)],
        [KeyboardButton("📍 مشاركة الموقع" if lang == "ar" else "📍 Share Location", request_location=True)],
        [KeyboardButton("👥 عرض الأقرب" if lang == "ar" else "👥 Nearby")],
        [KeyboardButton("🔥 التطابقات" if lang == "ar" else "🔥 Matches"),
         KeyboardButton("📥 طلباتي" if lang == "ar" else "📥 Requests")],
        [KeyboardButton("👻 إخفاء حسابي" if lang == "ar" else "👻 Hide Account"),
         KeyboardButton("📞 إظهار/إخفاء رقمي" if lang == "ar" else "📞 Show/Hide Phone")]
    ]

    await update.message.reply_text(
        "🤍 أهلاً بك في Always Close" if lang == "ar" else "🤍 Welcome to Always Close",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

    #=====================================
    # START PROFILE SETUP
    #=====================================

    async def start_profile_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):

        user = update.effective_user
        lang = detect_language(user.language_code)

        context.user_data["profile_lang"] = lang

        text = "كم عمرك؟" if lang == "ar" else "How old are you?"

        await update.message.reply_text(text)

        context.user_data["profile_step"] = PROFILE_AGE

    #=====================================
    # HANDLE AGE
    #=====================================

    async def handle_profile_age(update: Update, context: ContextTypes.DEFAULT_TYPE):

        if context.user_data.get("profile_step") != PROFILE_AGE:
            return

        try:
            age = int(update.message.text)
        except:
            await update.message.reply_text("اكتب رقم صحيح للعمر")
            return

        context.user_data["profile_age"] = age
        context.user_data["profile_step"] = PROFILE_GENDER

        lang = context.user_data["profile_lang"]

        keyboard = [
            [KeyboardButton("ذكر"), KeyboardButton("أنثى")]
        ] if lang == "ar" else [
            [KeyboardButton("Male"), KeyboardButton("Female")]
        ]

        text = "اختر النوع" if lang == "ar" else "Select gender"

        await update.message.reply_text(
            text,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
    #=====================================
    # HANDLE GENDER
    #=====================================

    async def handle_profile_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):

        if context.user_data.get("profile_step") != PROFILE_GENDER:
            return

        text = update.message.text.lower()

        if text in ["ذكر", "male"]:
            gender = "male"
        elif text in ["أنثى", "female"]:
            gender = "female"
        else:
            await update.message.reply_text("اختر من الأزرار")
            return

        context.user_data["profile_gender"] = gender
        context.user_data["profile_step"] = PROFILE_BIO

        lang = context.user_data["profile_lang"]

        msg = "اكتب نبذة قصيرة عنك" if lang == "ar" else "Write a short bio"

        await update.message.reply_text(msg)

    #=====================================
    # HANDLE BIO
    #=====================================

    async def handle_profile_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):

        if context.user_data.get("profile_step") != PROFILE_BIO:
            return

        bio = update.message.text
        age = context.user_data.get("profile_age")
        gender = context.user_data.get("profile_gender")

        telegram_id = update.effective_user.id

        user = supabase.table("users_v1") \
            .select("id") \
            .eq("telegram_id", telegram_id) \
            .execute()

        if not user.data:
            return

        user_id = user.data[0]["id"]

        supabase.table("users_v1") \
            .update({
                "age": age,
                "gender": gender,
                "bio": bio,
                "profile_completed": True
            }) \
            .eq("id", user_id) \
            .execute()

        lang = context.user_data["profile_lang"]

        msg = "تم حفظ البروفايل بنجاح 🎉" if lang == "ar" else "Profile saved successfully 🎉"

        await update.message.reply_text(msg)

        context.user_data["profile_step"] = None


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
    else:
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
            "age": 25,        # مؤقت لحين شاشة البروفايل
            "gender": "male", # مؤقت
            "is_active": True,
            "is_visible": True,
            "show_phone": True
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


  # فحص اكتمال البروفايل
user = supabase.table("users_v1") \
      .select("profile_completed") \
      .eq("telegram_id", telegram_id) \
      .execute()

        if user.data and not user.data[0]["profile_completed"]:
            await start_profile_setup(update, context)
            return

        await update.message.reply_text("Welcome back!")

# =========================================================
# SHOW NEARBY (Optimized)
# =========================================================

async def show_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    me = supabase.table("users_v1") \
        .select("*") \
        .eq("telegram_id", telegram_id) \
        .eq("is_active", True) \
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
        await update.message.reply_text("لم يتم العثور على موقعك.")
        return

    my_lat = my_location.data[0]["latitude"]
    my_lon = my_location.data[0]["longitude"]

    all_users = supabase.table("users_v1") \
    .select("id, username, age, gender, bio, photo_url, updated_at, language, phone, show_phone") \
        .eq("is_active", True) \
        .eq("is_visible", True) \
        .neq("id", my_id) \
        .execute()

    results = []

    for user in all_users.data:
        location = supabase.table("user_locations_v1") \
            .select("latitude, longitude") \
            .eq("user_id", user["id"]) \
            .order("recorded_at", desc=True) \
            .limit(1) \
            .execute()

        if not location.data:
            continue

        distance = calculate_distance(
            my_lat,
            my_lon,
            location.data[0]["latitude"],
            location.data[0]["longitude"]
        )

        user["distance"] = round(distance, 2)
        results.append(user)

    results.sort(key=lambda x: x["distance"])

    if not results:
        await update.message.reply_text("لا يوجد مستخدمين قريبين.")
        return

context.user_data["viewer_id"] = telegram_id
context.user_data["nearby_users"] = results
context.user_data["index"] = 0
context.bot_data["current_viewer"] = telegram_id

await send_user_card(update.effective_chat.id, context)


#=====================================
# SEND USER CARD (FINAL STABLE)
#=====================================

async def send_user_card(chat_id, context):

    users = context.user_data.get("nearby_users", [])
    index = context.user_data.get("index", 0)

    if index >= len(users):
        await context.bot.send_message(chat_id, "No more users.")
        return

    user = users[index]

    # جلب لغة المشاهد من قاعدة البيانات
    viewer = supabase.table("users_v1") \
        .select("language") \
        .eq("telegram_id", context.user_data.get("viewer_id")) \
        .execute()

    lang = viewer.data[0]["language"] if viewer.data else "en"

    years_text = "سنة" if lang == "ar" else "years"
    active_text = "🟢 نشط الآن" if lang == "ar" else "🟢 Active now"
    like_text = "❤️ إعجاب" if lang == "ar" else "❤️ Like"
    next_text = "⏭ التالي" if lang == "ar" else "⏭ Next"
    msg_text = "💬 تواصل" if lang == "ar" else "💬 Message"

    age = user.get("age") or "?"
    gender = user.get("gender") or "-"

    caption = f"""
<b>{user.get('username','User')}</b> | {age} {years_text}
gender_icon = "♂" if gender == "male" else "♀"
{gender_icon} {gender}
📍 {user.get('distance','?')} km
{active_text}
"""

    if user.get("show_phone") and user.get("phone"):
        caption += f"\n📞 {user.get('phone')}"

    keyboard = [
        [
            InlineKeyboardButton("❌ Skip", callback_data=f"skip_{user['id']}"),
            InlineKeyboardButton("❤️ Like", callback_data=f"like_{user['id']}"),
            InlineKeyboardButton("⭐ Super", callback_data=f"super_{user['id']}")
        ],
        [
            InlineKeyboardButton("⏭ Next", callback_data="next")
        ]
    ]

relation = supabase.table("friendships_v1") \
    .select("status") \
    .or_(f"and(requester_id.eq.{user['id']},receiver_id.eq.{context.user_data['viewer_id']}),and(requester_id.eq.{context.user_data['viewer_id']},receiver_id.eq.{user['id']})") \
    .execute()

if relation.data and relation.data[0]["status"] == "accepted":

    keyboard.append([
        InlineKeyboardButton("💬 Message", url=f"https://t.me/{user['username']}")
    ])

    if user.get("username"):
        keyboard.append([
            InlineKeyboardButton(msg_text, url=f"https://t.me/{user['username']}")
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
    await query.answer()

    telegram_id = query.from_user.id

    me = supabase.table("users_v1") \
        .select("id") \
        .eq("telegram_id", telegram_id) \
        .execute()

    if not me.data:
        return

    my_id = me.data[0]["id"]


    # ❤️ LIKE
    if query.data.startswith("like_"):

        target_id = int(query.data.split("_")[1])

        result = await process_like(my_id, target_id)

        if result == "matched":
            await query.message.reply_text("🎉 Match!")

        context.user_data["index"] = context.user_data.get("index", 0) + 1
        await send_user_card(query.message.chat.id, context)

        return


    # ⭐ SUPER LIKE
    elif query.data.startswith("super_"):

        target_id = int(query.data.split("_")[1])

        supabase.table("friendships_v1") \
            .insert({
                "requester_id": my_id,
                "receiver_id": target_id,
                "status": "pending_request",
                "is_super": True
            }) \
            .execute()

        await query.answer("⭐ Super Like sent!")

        # ارسال إشعار للطرف الآخر
        target = supabase.table("users_v1") \
            .select("telegram_id") \
            .eq("id", target_id) \
            .execute()

        if target.data:
            await context.bot.send_message(
                chat_id=target.data[0]["telegram_id"],
                text="⭐ Someone sent you a Super Like!"
            )

        context.user_data["index"] = context.user_data.get("index", 0) + 1
        await send_user_card(query.message.chat.id, context)

        return


    # ⏭ NEXT
    elif query.data == "next":

        context.user_data["index"] = context.user_data.get("index", 0) + 1
        await send_user_card(query.message.chat.id, context)

        return