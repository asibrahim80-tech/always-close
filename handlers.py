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
# MENUS
# =========================================================

def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📱 تسجيل الهاتف", request_contact=True)],
        [KeyboardButton("📍 مشاركة الموقع", request_location=True)],
        [KeyboardButton("👥 عرض الأقرب")],
        [KeyboardButton("🔥 التطابقات"), KeyboardButton("📥 طلباتي")],
        [KeyboardButton("👻 إخفاء حسابي"), KeyboardButton("📞 إظهار/إخفاء رقمي")],
        [KeyboardButton("✏️ تعديل بياناتي")]
    ], resize_keyboard=True)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    user = supabase.table("users_v1").select("id").eq("telegram_id", tg_id).execute()

    if not user.data:
        context.user_data["step"] = "gender"
        await update.message.reply_text(
            "🤍 أهلاً بك في Always Close\n\nاختر نوعك:",
            reply_markup=ReplyKeyboardMarkup(
                [["👨 ذكر", "👩 أنثى"]],
                resize_keyboard=True
            )
        )
    else:
        await update.message.reply_text(
            "🤍 Welcome Back!",
            reply_markup=main_keyboard()
        )


# =========================================================
# PROFILE SETUP (STEPS)
# =========================================================

async def handle_profile_steps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    text = update.message.text

    if step == "gender":
        context.user_data["gender"] = "ذكر" if "ذكر" in text else "أنثى"
        context.user_data["step"] = "birthdate"
        await update.message.reply_text("🎂 اكتب تاريخ ميلادك بالشكل:\n1998-05-10")
        return

    elif step == "birthdate":
        try:
            year, month, day = map(int, text.split("-"))
            today = datetime.today()
            age = today.year - year - ((today.month, today.day) < (month, day))
            context.user_data["birthdate"] = text
            context.user_data["age"] = age
            context.user_data["step"] = "bio"
            await update.message.reply_text("📝 اكتب نبذة عن نفسك:")
        except Exception:
            await update.message.reply_text("❌ التاريخ غير صحيح. اكتبه بالشكل:\n1998-05-10")
        return

    elif step == "bio":
        tg_id = update.effective_user.id
        username = update.effective_user.username

        user_check = supabase.table("users_v1").select("*").eq("telegram_id", tg_id).execute()

        data = {
            "telegram_id": tg_id,
            "username": username,
            "gender": context.user_data.get("gender"),
            "birthdate": context.user_data.get("birthdate"),
            "age": context.user_data.get("age"),
            "bio": text,
            "is_active": True,
            "is_visible": True
        }

        if user_check.data:
            supabase.table("users_v1").update(data).eq("telegram_id", tg_id).execute()
        else:
            supabase.table("users_v1").insert(data).execute()

        context.user_data.clear()
        await update.message.reply_text("✅ تم حفظ بياناتك 🎉", reply_markup=main_keyboard())
        return

    elif step == "edit_gender":
        supabase.table("users_v1").update({
            "gender": "ذكر" if "ذكر" in text else "أنثى"
        }).eq("telegram_id", update.effective_user.id).execute()
        context.user_data.clear()
        await update.message.reply_text("✅ تم التحديث", reply_markup=main_keyboard())
        return

    elif step == "edit_birthdate":
        try:
            year, month, day = map(int, text.split("-"))
            today = datetime.today()
            age = today.year - year - ((today.month, today.day) < (month, day))
            supabase.table("users_v1").update({
                "birthdate": text,
                "age": age
            }).eq("telegram_id", update.effective_user.id).execute()
            context.user_data.clear()
            await update.message.reply_text("✅ تم التحديث", reply_markup=main_keyboard())
        except Exception:
            await update.message.reply_text("❌ تنسيق خاطئ. مثال: 1998-05-10")
        return

    elif step == "edit_bio":
        supabase.table("users_v1").update({
            "bio": text
        }).eq("telegram_id", update.effective_user.id).execute()
        context.user_data.clear()
        await update.message.reply_text("✅ تم التحديث", reply_markup=main_keyboard())
        return


# =========================================================
# EDIT PROFILE
# =========================================================

async def edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["👤 تعديل النوع"],
        ["🎂 تعديل تاريخ الميلاد"],
        ["📝 تعديل النبذة"]
    ]
    await update.message.reply_text(
        "✏️ ماذا تريد تعديله؟",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


async def handle_edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "تعديل النوع" in text:
        context.user_data["step"] = "edit_gender"
        await update.message.reply_text(
            "👤 اختر النوع:",
            reply_markup=ReplyKeyboardMarkup([["👨 ذكر", "👩 أنثى"]], resize_keyboard=True)
        )
    elif "تعديل تاريخ الميلاد" in text:
        context.user_data["step"] = "edit_birthdate"
        await update.message.reply_text("🎂 اكتب التاريخ:\n1998-05-10")
    elif "تعديل النبذة" in text:
        context.user_data["step"] = "edit_bio"
        await update.message.reply_text("📝 اكتب النبذة الجديدة:")


# =========================================================
# HANDLE CONTACT
# =========================================================

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number
    supabase.table("users_v1").update({"phone": phone}).eq(
        "telegram_id", update.effective_user.id
    ).execute()
    await update.message.reply_text("📱 تم حفظ رقم الهاتف ✅")


# =========================================================
# HANDLE LOCATION
# =========================================================

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lat = update.message.location.latitude
    lon = update.message.location.longitude
    geo = geohash2.encode(lat, lon, precision=7)

    photo_url = None
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            # Store file_id directly - never expires and Telegram accepts it in send_photo
            photo_url = photos.photos[0][0].file_id
    except Exception:
        photo_url = None

    existing = supabase.table("users_v1").select("*").eq("telegram_id", user.id).execute()

    if existing.data:
        user_id = existing.data[0]["id"]
        supabase.table("users_v1").update({
            "username": user.username,
            "photo_url": photo_url
        }).eq("id", user_id).execute()
    else:
        insert = supabase.table("users_v1").insert({
            "telegram_id": user.id,
            "username": user.username,
            "photo_url": photo_url,
            "is_active": True,
            "is_visible": True
        }).execute()
        if not insert.data:
            await update.message.reply_text("❌ خطأ في التسجيل.")
            return
        user_id = insert.data[0]["id"]

    supabase.table("user_locations_v1").insert({
        "user_id": user_id,
        "latitude": lat,
        "longitude": lon,
        "geohash": geo,
        "source": "GPS"
    }).execute()

    await update.message.reply_text("🚀 تم تحديث موقعك بنجاح!")


# =========================================================
# SHOW NEARBY
# =========================================================

async def show_nearby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tg_id = update.effective_user.id
        chat_id = update.effective_chat.id

        me = supabase.table("users_v1").select("*").eq("telegram_id", tg_id).execute()
        if not me.data:
            await update.message.reply_text("❌ يجب التسجيل أولاً.")
            return

        my_id = me.data[0]["id"]

        loc_res = supabase.table("user_locations_v1") \
            .select("*") \
            .eq("user_id", my_id) \
            .order("recorded_at", desc=True) \
            .limit(1) \
            .execute()

        if not loc_res.data:
            await update.message.reply_text("❌ شارك موقعك أولاً.")
            return

        my_lat = loc_res.data[0]["latitude"]
        my_lon = loc_res.data[0]["longitude"]

        all_users = supabase.table("users_v1") \
            .select("id, username, age, gender, bio, photo_url, created_at") \
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
            u["distance"] = round(dist,2)
            result.append(u)

        if not result:
            await update.message.reply_text("❌ لا يوجد أشخاص قريبين حالياً.")
            return

        result.sort(key=lambda x: x["distance"])

        context.user_data["nearby_list"] = result
        context.user_data["current_index"] = 0

        await send_profile_card(context, chat_id, result[0])

    except Exception as e:
        import traceback
        traceback.print_exc()
        await update.message.reply_text(f"❌ حدث خطأ: {e}")


# =========================================================
# SEND PROFILE CARD
# =========================================================

async def send_profile_card(context, chat_id, user):
    name = user.get("username") or "مستخدم"
    age = user.get("age") or "?"
    gender = user.get("gender") or "غير محدد"
    bio = user.get("bio") or ""
    distance = user.get("distance", 0)
    distance_text = f"{distance} كم" if distance else "غير معروف"
    last_seen = time_ago(user.get("created_at"))
    status = "🟢 نشط الآن" if last_seen == "الآن" else f"🕒 منذ {last_seen}"
    photo_url = user.get("photo_url")

    caption = (
        f"<b>👤 {name}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎂 {age} سنة\n"
        f"🚻 {gender}\n"
        f"📍 {distance_text}\n"
        f"{status}"
    )
    if bio:
        caption += f"\n📝 {bio}"

    keyboard = [
        [
            InlineKeyboardButton("⬅️ السابق", callback_data="prev"),
            InlineKeyboardButton("التالي ➡️", callback_data="next")
        ],
        [
            InlineKeyboardButton("❤️ إعجاب", callback_data=f"like_{user.get('id')}"),
            InlineKeyboardButton("⭐ سوبر", callback_data=f"superlike_{user.get('id')}"),
            InlineKeyboardButton("❌ تخطي", callback_data="skip")
        ]
    ]

    if user.get("username"):
        keyboard.append([
            InlineKeyboardButton("💬 مراسلة", url=f"https://t.me/{user['username']}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if photo_url:
        try:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            return
        except Exception:
            pass

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

    telegram_id = query.from_user.id
    data = query.data
    chat_id = query.message.chat.id
    users = context.user_data.get("nearby_list", [])
    idx = context.user_data.get("current_index", 0)

    try:
        if data == "next":
            await query.answer()
            if not users:
                return
            new_idx = (idx + 1) % len(users)
            context.user_data["current_index"] = new_idx
            await send_profile_card(context, chat_id, users[new_idx])

        elif data == "prev":
            await query.answer()
            if not users:
                return
            new_idx = (idx - 1) % len(users)
            context.user_data["current_index"] = new_idx
            await send_profile_card(context, chat_id, users[new_idx])

        elif data == "skip":
            await query.answer()
            if not users:
                return
            new_idx = (idx + 1) % len(users)
            context.user_data["current_index"] = new_idx
            await send_profile_card(context, chat_id, users[new_idx])

        elif data.startswith("like_"):
            target_id = int(data.split("_")[1])

            me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
            if not me.data:
                await query.answer("❌ سجّل أولاً")
                return

            my_id = me.data[0]["id"]

            # Insert like (ignore if already liked)
            try:
                supabase.table("likes_v1").insert({
                    "from_user_id": my_id,
                    "to_user_id": target_id
                }).execute()
            except Exception:
                pass  # Already liked - continue

            # Check mutual like
            mutual = supabase.table("likes_v1") \
                .select("*") \
                .eq("from_user_id", target_id) \
                .eq("to_user_id", my_id) \
                .execute()

            if mutual.data:
                # Check match doesn't already exist
                match_exists = supabase.table("matches_v1") \
                    .select("*") \
                    .or_(
                        f"and(user1_id.eq.{my_id},user2_id.eq.{target_id}),"
                        f"and(user1_id.eq.{target_id},user2_id.eq.{my_id})"
                    ).execute()

                if not match_exists.data:
                    try:
                        supabase.table("matches_v1").insert({
                            "user1_id": my_id,
                            "user2_id": target_id
                        }).execute()
                    except Exception:
                        pass

                await query.answer("🎉 تطابق!")
                await context.bot.send_message(chat_id, "🎉 تم التطابق! يمكنكما التواصل الآن.")
            else:
                await query.answer("تم الإعجاب ❤️")

            if users:
                new_idx = (idx + 1) % len(users)
                context.user_data["current_index"] = new_idx
                await send_profile_card(context, chat_id, users[new_idx])

        elif data.startswith("superlike_"):
            await query.answer("⭐ سوبر لايك!")
            if users:
                new_idx = (idx + 1) % len(users)
                context.user_data["current_index"] = new_idx
                await send_profile_card(context, chat_id, users[new_idx])

        else:
            await query.answer()

    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await query.answer("❌ حدث خطأ")
        except Exception:
            pass


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
