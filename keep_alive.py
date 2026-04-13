from flask import Flask, render_template, jsonify, request
from flask_limiter import Limiter
from threading import Thread
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime, timezone
import httpx
import os
import time
import logging

from security import sanitize_text, sanitize_int, get_remote_addr

_ka_logger = logging.getLogger("keep_alive")

app = Flask(__name__)

# ── Rate Limiting ─────────────────────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_addr,
    app=app,
    default_limits=["200 per minute"],          # global: max 200 req/min per IP
    storage_uri="memory://",
)

@app.errorhandler(429)
def rate_limit_handler(e):
    return jsonify({"ok": False, "error": "too_many_requests",
                    "message": "طلبات كثيرة جداً، انتظر لحظة / Too many requests"}), 429

# Simple in-memory photo URL cache  {file_id: photo_url}
_photo_cache = {}


def _resolve_photo(file_id: str, bot_token: str) -> str | None:
    """Convert Telegram file_id → HTTPS URL (cached)."""
    if not file_id:
        return None
    if file_id in _photo_cache:
        return _photo_cache[file_id]
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
            timeout=5,
        )
        if r.status_code == 200:
            fp  = r.json()["result"]["file_path"]
            url = f"https://api.telegram.org/file/bot{bot_token}/{fp}"
            _photo_cache[file_id] = url
            return url
    except Exception:
        pass
    return None


def _haversine(lat1, lng1, lat2, lng2) -> float:
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return round(6371 * 2 * atan2(sqrt(a), sqrt(1 - a)), 2)


def _is_active(recorded_at_str: str | None) -> bool:
    """True if last location update was within 5 minutes."""
    if not recorded_at_str:
        return False
    try:
        dt   = datetime.fromisoformat(recorded_at_str.replace("Z", "+00:00"))
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        return diff < 300
    except Exception:
        return False


@app.route('/')
def home():
    return render_template("index.html")


@app.route('/map')
def map_page():
    return render_template("map.html")


@app.route('/users')
def users_page():
    return render_template("users.html")


@app.route('/settings')
def settings_page():
    return render_template("settings.html")


@app.route('/rooms')
def rooms_page():
    return render_template("rooms.html")


@app.route('/stores')
def stores_page():
    return render_template("stores.html")


@app.route('/likes')
def likes_page():
    return render_template("likes.html")


@app.route('/profile')
def profile_page():
    return render_template("profile.html")


# ── Profile: load ─────────────────────────────────────────────────────────
@app.route('/api/profile/<int:telegram_id>')
def api_profile_get(telegram_id):
    try:
        from database import supabase
        from config import BOT_TOKEN

        # Try full query (requires migrate_profile.sql to have been run)
        try:
            me = supabase.table("users_v1") \
                .select("id,telegram_id,username,first_name,last_name,gender,birthdate,age,bio,email,phone,"
                        "photo_url,zodiac,social_status,has_children,education,profession,university,"
                        "school,country,city,neighborhood,hobbies,habits,personality_traits,purpose,"
                        "is_visible,show_phone,profile_complete") \
                .eq("telegram_id", telegram_id).execute()
        except Exception:
            # Fall back to base columns (migration not yet applied)
            me = supabase.table("users_v1") \
                .select("id,telegram_id,username,gender,birthdate,age,bio,phone,"
                        "photo_url,is_visible,show_phone") \
                .eq("telegram_id", telegram_id).execute()

        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        u = me.data[0]
        u["photo_url"] = _resolve_photo(u.get("photo_url"), BOT_TOKEN)

        # Extra photos (table may not exist yet)
        try:
            photos = supabase.table("user_photos_v1") \
                .select("id,photo_url,order_num") \
                .eq("user_id", u["id"]) \
                .order("order_num").execute()
            u["extra_photos"] = photos.data or []
        except Exception:
            u["extra_photos"] = []

        # Ratings count & avg
        try:
            ratings = supabase.table("user_ratings_v1") \
                .select("stars") \
                .eq("rated_user_id", u["id"]).execute()
            if ratings.data:
                stars = [r["stars"] for r in ratings.data]
                u["rating_avg"]   = round(sum(stars)/len(stars), 1)
                u["rating_count"] = len(stars)
            else:
                u["rating_avg"]   = 0
                u["rating_count"] = 0
        except Exception:
            u["rating_avg"]   = 0
            u["rating_count"] = 0

        return jsonify({"ok": True, "profile": u})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Profile: toggle account visibility ────────────────────────────────────
@app.route('/api/profile/toggle_visibility', methods=['POST'])
@limiter.limit("10 per minute")
def api_toggle_visibility():
    try:
        from database import supabase
        data = request.get_json(force=True)
        uid  = int(data.get("uid", 0))
        me = supabase.table("users_v1").select("id,is_visible").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        new_val = not me.data[0].get("is_visible", True)
        supabase.table("users_v1").update({"is_visible": new_val}).eq("id", me.data[0]["id"]).execute()
        return jsonify({"ok": True, "is_visible": new_val})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Profile: toggle phone visibility ──────────────────────────────────────
@app.route('/api/profile/toggle_phone', methods=['POST'])
@limiter.limit("10 per minute")
def api_toggle_phone():
    try:
        from database import supabase
        data = request.get_json(force=True)
        uid  = int(data.get("uid", 0))
        me = supabase.table("users_v1").select("id,show_phone").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        new_val = not me.data[0].get("show_phone", False)
        supabase.table("users_v1").update({"show_phone": new_val}).eq("id", me.data[0]["id"]).execute()
        return jsonify({"ok": True, "show_phone": new_val})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Profile: save ─────────────────────────────────────────────────────────
@app.route('/api/profile/save', methods=['POST'])
@limiter.limit("20 per minute")
def api_profile_save():
    import logging as _log
    try:
        from database import supabase
        from datetime import datetime as _dt

        data = request.get_json(force=True)
        uid  = int(data.get("uid", 0))
        if not uid:
            return jsonify({"ok": False, "error": "no_uid"})

        # ── Fetch current row for completeness calc ────────────
        SCALAR_SELECT = ("id,bio,email,zodiac,social_status,education,profession,"
                         "country,city,hobbies,purpose,photo_url,gender,birthdate,"
                         "profile_complete")
        try:
            cur = supabase.table("users_v1").select(SCALAR_SELECT) \
                .eq("telegram_id", uid).execute()
        except Exception as e_sel:
            _log.warning(f"[profile/save] SELECT fallback: {e_sel}")
            cur = supabase.table("users_v1") \
                .select("id,bio,email,gender,birthdate,city,photo_url") \
                .eq("telegram_id", uid).execute()

        if not cur.data:
            return jsonify({"ok": False, "error": "not_found"})
        current = cur.data[0]

        # ── Scalar fields (TEXT / BOOLEAN / INTEGER) ───────────
        TEXT_COLS   = ["first_name","last_name","bio","email","zodiac",
                       "social_status","education","profession",
                       "university","school","country","city","neighborhood"]
        ARRAY_COLS  = ["hobbies","habits","personality_traits","purpose"]

        scalar = {k: data[k] for k in TEXT_COLS if k in data}

        # has_children must be a real bool
        if "has_children" in data:
            scalar["has_children"] = bool(data["has_children"])

        # gender
        if "gender" in data and data["gender"]:
            scalar["gender"] = data["gender"]

        # birthdate → age
        if "birthdate" in data and data["birthdate"]:
            try:
                bd = _dt.strptime(data["birthdate"], "%Y-%m-%d")
                today = _dt.today()
                age = (today.year - bd.year
                       - ((today.month, today.day) < (bd.month, bd.day)))
                scalar["birthdate"] = data["birthdate"]
                scalar["age"] = max(0, age)
            except Exception:
                pass

        # ── Array fields — convert empty list → None to avoid type errors ──
        arrays = {}
        for col in ARRAY_COLS:
            if col in data:
                val = data[col]
                # Must be a list; send None for empty (clears the field gracefully)
                if isinstance(val, list) and len(val) > 0:
                    arrays[col] = val
                elif isinstance(val, list) and len(val) == 0:
                    arrays[col] = None   # PostgreSQL NULL for empty array

        # ── Completeness score ─────────────────────────────────
        merged = {**current, **scalar, **arrays}
        score_map = {
            "bio":           lambda v: bool(v and len(str(v)) >= 10),
            "email":         lambda v: bool(v),
            "zodiac":        lambda v: bool(v),
            "social_status": lambda v: bool(v),
            "education":     lambda v: bool(v),
            "profession":    lambda v: bool(v),
            "country":       lambda v: bool(v),
            "city":          lambda v: bool(v),
            "hobbies":       lambda v: bool(v and len(v) >= 1),
            "purpose":       lambda v: bool(v and len(v) >= 1),
        }
        filled = sum(1 for f, fn in score_map.items() if fn(merged.get(f)))
        if merged.get("photo_url") or merged.get("gender"):
            filled = min(filled + 1, len(score_map))
        pct = min(100, int(filled / len(score_map) * 100))

        # ── Step 1: Save scalar fields ─────────────────────────
        saved_scalar = False
        scalar_err   = None
        try:
            scalar["profile_complete"] = pct
            res = supabase.table("users_v1").update(scalar) \
                .eq("telegram_id", uid).execute()
            _log.info(f"[profile/save] scalar OK → {res.data}")
            saved_scalar = True
        except Exception as e_sc:
            scalar_err = str(e_sc)
            _log.error(f"[profile/save] scalar FAILED: {e_sc}")
            # Try without profile_complete (column might not exist)
            scalar.pop("profile_complete", None)
            try:
                supabase.table("users_v1").update(scalar) \
                    .eq("telegram_id", uid).execute()
                saved_scalar = True
                _log.info("[profile/save] scalar OK (without profile_complete)")
            except Exception as e_sc2:
                scalar_err = str(e_sc2)
                _log.error(f"[profile/save] scalar 2nd attempt FAILED: {e_sc2}")

        # ── Step 2: Save array fields separately ───────────────
        saved_arrays = False
        array_err    = None
        if arrays:
            try:
                res2 = supabase.table("users_v1").update(arrays) \
                    .eq("telegram_id", uid).execute()
                _log.info(f"[profile/save] arrays OK → {res2.data}")
                saved_arrays = True
            except Exception as e_arr:
                array_err = str(e_arr)
                _log.error(f"[profile/save] arrays FAILED: {e_arr}")
                # Try each array column individually
                for col, val in arrays.items():
                    try:
                        supabase.table("users_v1").update({col: val}) \
                            .eq("telegram_id", uid).execute()
                        _log.info(f"[profile/save] array col {col} OK individually")
                        saved_arrays = True
                    except Exception as e_col:
                        _log.error(f"[profile/save] array col {col} FAILED: {e_col}")

        if saved_scalar or saved_arrays:
            return jsonify({
                "ok": True,
                "profile_complete": pct,
                "saved_scalar": saved_scalar,
                "saved_arrays": saved_arrays,
                "array_err": array_err,
                "scalar_err": scalar_err,
            })
        else:
            return jsonify({
                "ok": False,
                "error": scalar_err or "unknown",
                "array_err": array_err,
            })

    except Exception as e:
        import logging as _log2
        _log2.error(f"[profile/save] outer exception: {e}")
        return jsonify({"ok": False, "error": str(e)})


# ── Profile: add extra photo ──────────────────────────────────────────────
@app.route('/api/profile/photo/add', methods=['POST'])
@limiter.limit('10 per minute')
def api_profile_photo_add():
    try:
        from database import supabase
        uid = int(request.form.get("uid", 0))
        f   = request.files.get("image")
        if not f:
            return jsonify({"ok": False, "error": "no_file"})

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        # Max 9 photos
        existing = supabase.table("user_photos_v1").select("id", count="exact") \
            .eq("user_id", my_id).execute()
        if (existing.count or 0) >= 9:
            return jsonify({"ok": False, "error": "max_photos"})

        os.makedirs("static/profile_photos", exist_ok=True)
        ext = (f.filename.rsplit(".", 1)[-1].lower()
               if f.filename and "." in f.filename else "jpg")
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
        import uuid as _uuid
        fname     = f"static/profile_photos/u{my_id}_{_uuid.uuid4().hex[:8]}.{ext}"
        photo_url = f"/{fname}"
        f.save(fname)

        order_num = (existing.count or 0)
        supabase.table("user_photos_v1").insert({
            "user_id": my_id, "photo_url": photo_url, "order_num": order_num
        }).execute()
        return jsonify({"ok": True, "photo_url": photo_url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Profile: delete extra photo ───────────────────────────────────────────
@app.route('/api/profile/photo/delete', methods=['POST'])
@limiter.limit('20 per minute')
def api_profile_photo_delete():
    try:
        from database import supabase
        data     = request.get_json(force=True)
        uid      = data.get("uid")
        photo_id = data.get("photo_id")
        if not uid or not photo_id:
            return jsonify({"ok": False, "error": "missing_params"})

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        row = supabase.table("user_photos_v1").select("id,photo_url,user_id") \
            .eq("id", photo_id).execute()
        if not row.data or row.data[0]["user_id"] != my_id:
            return jsonify({"ok": False, "error": "forbidden"})

        # Delete file
        path = row.data[0]["photo_url"].lstrip("/")
        if os.path.exists(path):
            os.remove(path)

        supabase.table("user_photos_v1").delete().eq("id", photo_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/notifications/<int:telegram_id>')
def api_notifications(telegram_id):
    try:
        from database import supabase
        from config import BOT_TOKEN

        me_res = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
        if not me_res.data:
            return jsonify({"ok": False, "error": "user not found"})
        my_id = me_res.data[0]["id"]

        # ── 1. Matches ─────────────────────────────────────────────
        matches_res = supabase.table("matches_v1") \
            .select("id, user1_id, user2_id, created_at") \
            .or_(f"user1_id.eq.{my_id},user2_id.eq.{my_id}") \
            .order("created_at", desc=True).execute()

        match_rows = matches_res.data or []
        match_partner_ids = []
        match_created = {}
        for m in match_rows:
            other = m["user2_id"] if m["user1_id"] == my_id else m["user1_id"]
            match_partner_ids.append(other)
            match_created[other] = m["created_at"]

        # ── 2. Likes (unmatched only) ───────────────────────────────
        likes_res = supabase.table("likes_v1") \
            .select("from_user_id, created_at") \
            .eq("to_user_id", my_id) \
            .order("created_at", desc=True).execute()

        matched_set = set(match_partner_ids)
        like_rows = [lk for lk in (likes_res.data or []) if lk["from_user_id"] not in matched_set]
        like_ids = [lk["from_user_id"] for lk in like_rows]
        like_created = {lk["from_user_id"]: lk["created_at"] for lk in like_rows}

        # ── 3. Room joins (people who joined MY rooms) ──────────────
        my_rooms_res = supabase.table("rooms_v1").select("id, name").eq("creator_id", my_id).execute()
        my_rooms = {r["id"]: r["name"] for r in (my_rooms_res.data or [])}

        room_join_rows = []
        for room_id, room_name in my_rooms.items():
            rm = supabase.table("room_members_v1") \
                .select("user_id, created_at") \
                .eq("room_id", room_id) \
                .order("created_at", desc=True).execute()
            for m in (rm.data or []):
                if m["user_id"] != my_id:
                    room_join_rows.append({**m, "room_id": room_id, "room_name": room_name})

        rj_user_ids = list({r["user_id"] for r in room_join_rows})

        # ── 4. Store follows (people who followed MY stores) ────────
        my_stores_res = supabase.table("stores_v1").select("id, name").eq("creator_id", my_id).execute()
        my_stores = {s["id"]: s["name"] for s in (my_stores_res.data or [])}

        store_follow_rows = []
        for store_id, store_name in my_stores.items():
            sm = supabase.table("store_members_v1") \
                .select("user_id, created_at") \
                .eq("store_id", store_id) \
                .order("created_at", desc=True).execute()
            for f in (sm.data or []):
                if f["user_id"] != my_id:
                    store_follow_rows.append({**f, "store_id": store_id, "store_name": store_name})

        sf_user_ids = list({f["user_id"] for f in store_follow_rows})

        # ── Batch-fetch all users ────────────────────────────────────
        all_user_ids = list(set(match_partner_ids + like_ids + rj_user_ids + sf_user_ids))
        user_cache = {}
        if all_user_ids:
            u_res = supabase.table("users_v1") \
                .select("id, username, gender, photo_url") \
                .in_("id", all_user_ids).execute()
            for u in (u_res.data or []):
                photo = _resolve_photo(u.get("photo_url"), BOT_TOKEN)
                user_cache[u["id"]] = {
                    "username": u.get("username"),
                    "gender":   u.get("gender"),
                    "photo_url": photo,
                }

        def _udict(uid, type_, created_at, extra=None):
            u = user_cache.get(uid, {})
            d = {"type": type_, "user_id": uid,
                 "username": u.get("username"),
                 "gender":   u.get("gender"),
                 "photo_url": u.get("photo_url"),
                 "created_at": created_at}
            if extra:
                d.update(extra)
            return d

        matches      = [_udict(uid, "match",        match_created.get(uid))
                        for uid in match_partner_ids if uid in user_cache]
        likes        = [_udict(uid, "like",         like_created.get(uid))
                        for uid in like_ids         if uid in user_cache]
        room_joins   = [_udict(r["user_id"], "room_join",    r["created_at"],
                               {"room_id": r["room_id"], "room_name": r["room_name"]})
                        for r in room_join_rows if r["user_id"] in user_cache]
        store_follows= [_udict(f["user_id"], "store_follow", f["created_at"],
                               {"store_id": f["store_id"], "store_name": f["store_name"]})
                        for f in store_follow_rows if f["user_id"] in user_cache]

        return jsonify({"ok": True,
                        "matches":       matches,
                        "likes":         likes,
                        "room_joins":    room_joins,
                        "store_follows": store_follows})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════════════════
# SEND LIKE FROM WEBAPP
# ══════════════════════════════════════════════════════════════════
@app.route('/api/send_like', methods=['POST'])
@limiter.limit("30 per minute")
def api_send_like():
    try:
        from database import supabase
        data      = request.get_json(force=True) or {}
        from_uid  = int(data.get("from_uid", 0))
        to_db_id  = int(data.get("to_user_id", 0))
        if not from_uid or not to_db_id:
            return jsonify({"ok": False, "error": "missing params"})

        # Get sender's db id
        me = supabase.table("users_v1").select("id").eq("telegram_id", from_uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "sender not found"})
        my_db_id = me.data[0]["id"]

        # Insert like (ignore duplicate)
        try:
            supabase.table("likes_v1").insert({
                "from_user_id": my_db_id,
                "to_user_id":   to_db_id
            }).execute()
        except Exception:
            pass  # duplicate — already liked

        # Check mutual like → create match
        mutual = supabase.table("likes_v1") \
            .select("id") \
            .eq("from_user_id", to_db_id) \
            .eq("to_user_id", my_db_id).execute()
        if mutual.data:
            exists = supabase.table("matches_v1") \
                .select("id") \
                .or_(f"user1_id.eq.{my_db_id},user2_id.eq.{my_db_id}") \
                .or_(f"user1_id.eq.{to_db_id},user2_id.eq.{to_db_id}").execute()
            if not exists.data:
                supabase.table("matches_v1").insert({
                    "user1_id": my_db_id, "user2_id": to_db_id
                }).execute()
            return jsonify({"ok": True, "status": "matched"})

        return jsonify({"ok": True, "status": "liked"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════════════════
# SMART MATCH API — compatibility scoring based on profile data
# ══════════════════════════════════════════════════════════════════
@app.route('/api/smart_matches/<int:telegram_id>')
def api_smart_matches(telegram_id):
    try:
        from database import supabase
        from config import BOT_TOKEN
        from datetime import date

        # ── Load my full profile ─────────────────────────────────
        try:
            me_res = supabase.table("users_v1") \
                .select("id,gender,birthdate,age,city,country,hobbies,habits,"
                        "personality_traits,purpose,zodiac,social_status") \
                .eq("telegram_id", telegram_id).execute()
        except Exception:
            me_res = supabase.table("users_v1") \
                .select("id,gender,birthdate,age,city,country") \
                .eq("telegram_id", telegram_id).execute()

        if not me_res.data:
            return jsonify({"ok": False, "error": "not_found"})
        me = me_res.data[0]
        my_id = me["id"]

        # ── Users I already liked or matched ────────────────────
        likes_sent = supabase.table("likes_v1") \
            .select("to_user_id").eq("from_user_id", my_id).execute()
        liked_ids = {r["to_user_id"] for r in (likes_sent.data or [])}

        matches_res = supabase.table("matches_v1") \
            .select("user1_id,user2_id") \
            .or_(f"user1_id.eq.{my_id},user2_id.eq.{my_id}").execute()
        matched_ids = set()
        for m in (matches_res.data or []):
            matched_ids.add(m["user1_id"])
            matched_ids.add(m["user2_id"])
        matched_ids.discard(my_id)

        exclude_ids = liked_ids | matched_ids | {my_id}

        # ── Fetch candidates (visible users with profiles) ───────
        try:
            cands_res = supabase.table("users_v1") \
                .select("id,username,gender,birthdate,age,photo_url,city,country,"
                        "hobbies,habits,personality_traits,purpose,zodiac,bio,social_status") \
                .eq("is_visible", True).execute()
        except Exception:
            cands_res = supabase.table("users_v1") \
                .select("id,username,gender,birthdate,age,photo_url,city,country,bio") \
                .eq("is_visible", True).execute()

        candidates = [u for u in (cands_res.data or []) if u["id"] not in exclude_ids]

        # ── Scoring function ─────────────────────────────────────
        def score_user(u):
            score = 0
            reasons = []

            # 1. Shared purpose (25 pts) — most important
            my_p = set(me.get("purpose") or [])
            ur_p = set(u.get("purpose") or [])
            shared_p = my_p & ur_p
            if shared_p:
                pts = min(len(shared_p), 3) * 8
                score += pts
                reasons.append(("purpose", list(shared_p)[:2]))

            # 2. Shared hobbies (25 pts)
            my_h = set(me.get("hobbies") or [])
            ur_h = set(u.get("hobbies") or [])
            shared_h = my_h & ur_h
            if shared_h:
                pts = min(len(shared_h), 5) * 5
                score += pts
                reasons.append(("hobbies", list(shared_h)[:3]))

            # 3. Shared habits (15 pts)
            my_hb = set(me.get("habits") or [])
            ur_hb = set(u.get("habits") or [])
            shared_hb = my_hb & ur_hb
            if shared_hb:
                pts = min(len(shared_hb), 3) * 5
                score += pts
                reasons.append(("habits", list(shared_hb)[:2]))

            # 4. Same city (15 pts)
            my_city = (me.get("city") or "").strip().lower()
            ur_city = (u.get("city") or "").strip().lower()
            if my_city and ur_city and my_city == ur_city:
                score += 15
                reasons.append(("city", my_city))

            # 5. Same country (5 pts)
            my_co = (me.get("country") or "").strip().lower()
            ur_co = (u.get("country") or "").strip().lower()
            if my_co and ur_co and my_co == ur_co and my_city != ur_city:
                score += 5
                reasons.append(("country", my_co))

            # 6. Age proximity (10 pts)
            my_age = me.get("age") or 0
            ur_age = u.get("age") or 0
            if my_age and ur_age:
                diff = abs(my_age - ur_age)
                if diff <= 2:   score += 10
                elif diff <= 5: score += 7
                elif diff <= 10:score += 4

            # 7. Personality compatibility (5 pts)
            my_pt = set(me.get("personality_traits") or [])
            ur_pt = set(u.get("personality_traits") or [])
            if my_pt & ur_pt:
                score += 5
                reasons.append(("personality", list(my_pt & ur_pt)[:1]))

            return score, reasons

        # ── Compute scores ───────────────────────────────────────
        results = []
        for u in candidates:
            sc, reasons = score_user(u)
            if sc < 10:  # minimum threshold
                continue
            photo = _resolve_photo(u.get("photo_url"), BOT_TOKEN)
            results.append({
                "user_id":   u["id"],
                "username":  u.get("username"),
                "gender":    u.get("gender"),
                "age":       u.get("age"),
                "photo_url": photo,
                "city":      u.get("city"),
                "bio":       (u.get("bio") or "")[:80],
                "score":     min(sc, 100),
                "reasons":   reasons,
            })

        # Sort by score descending, return top 30
        results.sort(key=lambda x: x["score"], reverse=True)
        return jsonify({"ok": True, "matches": results[:30]})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/nearby/<int:telegram_id>')
def api_nearby(telegram_id):
    try:
        from database import supabase
        from config import BOT_TOKEN

        # ── Current user ────────────────────────────────────────
        me_res = supabase.table("users_v1") \
            .select("id, username, photo_url") \
            .eq("telegram_id", telegram_id) \
            .execute()

        if not me_res.data:
            return jsonify({"error": "User not found. Please register first."})

        my_id       = me_res.data[0]["id"]
        my_name     = me_res.data[0].get("username") or "You"
        my_photo    = _resolve_photo(me_res.data[0].get("photo_url"), BOT_TOKEN)

        my_loc = supabase.table("user_locations_v1") \
            .select("latitude, longitude, recorded_at") \
            .eq("user_id", my_id) \
            .limit(1) \
            .execute()

        if not my_loc.data:
            return jsonify({"error": "Share your location first."})

        my_lat = float(my_loc.data[0]["latitude"])
        my_lng = float(my_loc.data[0]["longitude"])
        my_rec = my_loc.data[0].get("recorded_at")

        # ── Other users ─────────────────────────────────────────
        all_users = supabase.table("users_v1") \
            .select("id, telegram_id, username, age, gender, bio, photo_url") \
            .eq("is_active", True) \
            .eq("is_visible", True) \
            .neq("id", my_id) \
            .execute()

        nearby = []
        for u in all_users.data:
            loc = supabase.table("user_locations_v1") \
                .select("latitude, longitude, recorded_at") \
                .eq("user_id", u["id"]) \
                .limit(1) \
                .execute()

            if not loc.data:
                continue

            ulat = float(loc.data[0]["latitude"])
            ulng = float(loc.data[0]["longitude"])
            rec  = loc.data[0].get("recorded_at")

            dist      = _haversine(my_lat, my_lng, ulat, ulng)
            active    = _is_active(rec)
            photo_url = _resolve_photo(u.get("photo_url"), BOT_TOKEN)

            nearby.append({
                "id":          u["id"],
                "telegram_id": u.get("telegram_id"),
                "username":    u.get("username"),
                "age":         u.get("age"),
                "gender":      u.get("gender"),
                "bio":         u.get("bio"),
                "photo_url":   photo_url,
                "lat":         ulat,
                "lng":         ulng,
                "distance":    dist,
                "last_seen":   rec,
                "is_active":   active,
            })

        nearby.sort(key=lambda x: x["distance"])

        # ── Batch-fetch user ratings ──
        user_ids = [u["id"] for u in nearby]
        avg_u_ratings  = {}   # user_id → (avg, count)
        my_u_ratings   = {}   # user_id → my rating
        if user_ids:
            try:
                all_urat = supabase.table("user_ratings_v1") \
                    .select("rated_user_id, rating").execute()
                from collections import defaultdict
                ubucket = defaultdict(list)
                for row in (all_urat.data or []):
                    ubucket[row["rated_user_id"]].append(row["rating"])
                for uid2, vals in ubucket.items():
                    avg_u_ratings[uid2] = (round(sum(vals)/len(vals), 1), len(vals))
                if my_id:
                    my_urat = supabase.table("user_ratings_v1") \
                        .select("rated_user_id, rating").eq("rater_id", my_id).execute()
                    my_u_ratings = {row["rated_user_id"]: row["rating"]
                                    for row in (my_urat.data or [])}
            except Exception:
                pass

        for u in nearby:
            avg, cnt = avg_u_ratings.get(u["id"], (0, 0))
            u["avg_rating"]   = avg
            u["rating_count"] = cnt
            u["my_rating"]    = my_u_ratings.get(u["id"], 0)

        return jsonify({
            "me": {
                "lat":       my_lat,
                "lng":       my_lng,
                "name":      my_name,
                "photo_url": my_photo,
                "last_seen": my_rec,
                "is_active": _is_active(my_rec),
            },
            "my_user_id": my_id,
            "nearby": nearby,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)})


@app.route('/api/rooms/<int:telegram_id>')
def api_rooms(telegram_id):
    """Return all rooms with membership and ownership flags."""
    try:
        from database import supabase

        my_id = None
        my_lat, my_lng = None, None

        me_res = supabase.table("users_v1").select("id") \
            .eq("telegram_id", telegram_id).execute()
        if me_res.data:
            my_id = me_res.data[0]["id"]
            loc = supabase.table("user_locations_v1") \
                .select("latitude, longitude") \
                .eq("user_id", my_id).limit(1).execute()
            if loc.data:
                my_lat = float(loc.data[0]["latitude"])
                my_lng = float(loc.data[0]["longitude"])

        # Fetch rooms — try new columns gracefully
        try:
            rooms_res = supabase.table("rooms_v1") \
                .select("id, name, latitude, longitude, created_by, created_at, purpose, nature, image_url, expires_at, icon") \
                .execute()
        except Exception:
            rooms_res = supabase.table("rooms_v1") \
                .select("id, name, latitude, longitude, created_by, created_at") \
                .execute()

        # Fetch memberships for current user in one query
        my_room_ids = set()
        if my_id is not None:
            try:
                memb_res = supabase.table("room_members_v1") \
                    .select("room_id").eq("user_id", my_id).execute()
                my_room_ids = {m["room_id"] for m in (memb_res.data or [])}
            except Exception:
                pass

        rooms_out = []
        for r in (rooms_res.data or []):
            rlat = r.get("latitude")
            rlng = r.get("longitude")
            if rlat is None or rlng is None:
                continue
            dist = None
            if my_lat is not None:
                dist = round(_haversine(my_lat, my_lng, float(rlat), float(rlng)), 2)

            try:
                cnt = supabase.table("room_members_v1") \
                    .select("id", count="exact").eq("room_id", r["id"]).execute()
                members = cnt.count if cnt.count is not None else 0
            except Exception:
                members = 0

            rooms_out.append({
                "id":         r["id"],
                "name":       r.get("name", "Room"),
                "lat":        float(rlat),
                "lng":        float(rlng),
                "distance":   dist,
                "members":    members,
                "created_at": r.get("created_at"),
                "purpose":    r.get("purpose") or "",
                "nature":     r.get("nature") or "",
                "image_url":  r.get("image_url") or "",
                "expires_at": r.get("expires_at") or "",
                "icon":       r.get("icon") or "🏠",
                "is_creator": (my_id is not None and r.get("created_by") == my_id),
                "is_member":  (r["id"] in my_room_ids),
            })

        # ── Batch-fetch room ratings ──
        room_ids = [r["id"] for r in (rooms_res.data or []) if r.get("latitude")]
        avg_ratings  = {}   # room_id → (avg, count)
        my_r_ratings = {}   # room_id → my rating
        if room_ids:
            try:
                all_rat = supabase.table("room_ratings_v1") \
                    .select("room_id, rating").execute()
                from collections import defaultdict
                bucket = defaultdict(list)
                for row in (all_rat.data or []):
                    bucket[row["room_id"]].append(row["rating"])
                for rid, vals in bucket.items():
                    avg_ratings[rid] = (round(sum(vals)/len(vals), 1), len(vals))
                if my_id is not None:
                    my_rat = supabase.table("room_ratings_v1") \
                        .select("room_id, rating").eq("user_id", my_id).execute()
                    my_r_ratings = {row["room_id"]: row["rating"] for row in (my_rat.data or [])}
            except Exception:
                pass

        for entry in rooms_out:
            rid = entry["id"]
            avg, cnt = avg_ratings.get(rid, (0, 0))
            entry["avg_rating"]   = avg
            entry["rating_count"] = cnt
            entry["my_rating"]    = my_r_ratings.get(rid, 0)

        return jsonify({"rooms": rooms_out, "my_user_id": my_id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"rooms": [], "error": str(e)})


@app.route('/api/room/join', methods=['POST'])
def api_room_join():
    try:
        from database import supabase
        data    = request.get_json(force=True)
        uid     = int(data.get("uid", 0))
        room_id = int(data.get("room_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        # Check already member
        existing = supabase.table("room_members_v1") \
            .select("id").eq("room_id", room_id).eq("user_id", my_id).execute()
        if existing.data:
            return jsonify({"ok": False, "already": True})

        supabase.table("room_members_v1").insert({
            "room_id": room_id, "user_id": my_id
        }).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/room/delete', methods=['POST'])
def api_room_delete():
    try:
        from database import supabase
        data    = request.get_json(force=True)
        uid     = int(data.get("uid", 0))
        room_id = int(data.get("room_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        # Must be creator
        room = supabase.table("rooms_v1").select("created_by").eq("id", room_id).execute()
        if not room.data or room.data[0]["created_by"] != my_id:
            return jsonify({"ok": False, "error": "not_creator"})

        # Must be alone (only 1 member = self)
        cnt = supabase.table("room_members_v1").select("id", count="exact") \
            .eq("room_id", room_id).execute()
        member_count = cnt.count if cnt.count is not None else 0
        if member_count > 1:
            return jsonify({"ok": False, "error": "has_members"})

        # Delete members then room
        supabase.table("room_members_v1").delete().eq("room_id", room_id).execute()
        supabase.table("rooms_v1").delete().eq("id", room_id).execute()

        # Delete image file if exists
        for ext in ["jpg", "jpeg", "png", "webp"]:
            path = f"static/room_images/room_{room_id}.{ext}"
            if os.path.exists(path):
                os.remove(path)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/room/image/upload', methods=['POST'])
def api_room_image_upload():
    try:
        from database import supabase
        uid     = int(request.form.get("uid", 0))
        room_id = int(request.form.get("room_id", 0))
        f       = request.files.get("image")
        if not f:
            return jsonify({"ok": False, "error": "no_file"})

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        room = supabase.table("rooms_v1").select("created_by").eq("id", room_id).execute()
        if not room.data or room.data[0]["created_by"] != my_id:
            return jsonify({"ok": False, "error": "not_creator"})

        os.makedirs("static/room_images", exist_ok=True)
        ext = (f.filename.rsplit(".", 1)[-1].lower()
               if f.filename and "." in f.filename else "jpg")
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
        filename  = f"static/room_images/room_{room_id}.{ext}"
        image_url = f"/static/room_images/room_{room_id}.{ext}"

        # Remove old files with other extensions
        for old_ext in ("jpg", "jpeg", "png", "webp"):
            old = f"static/room_images/room_{room_id}.{old_ext}"
            if os.path.exists(old) and old != filename:
                os.remove(old)

        f.save(filename)
        supabase.table("rooms_v1").update({"image_url": image_url}) \
            .eq("id", room_id).execute()
        return jsonify({"ok": True, "image_url": image_url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/room/image/delete', methods=['POST'])
def api_room_image_delete():
    try:
        from database import supabase
        data    = request.get_json(force=True)
        uid     = int(data.get("uid", 0))
        room_id = int(data.get("room_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        room = supabase.table("rooms_v1").select("created_by").eq("id", room_id).execute()
        if not room.data or room.data[0]["created_by"] != my_id:
            return jsonify({"ok": False, "error": "not_creator"})

        for ext in ("jpg", "jpeg", "png", "webp"):
            path = f"static/room_images/room_{room_id}.{ext}"
            if os.path.exists(path):
                os.remove(path)

        supabase.table("rooms_v1").update({"image_url": None}) \
            .eq("id", room_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/room/rate', methods=['POST'])
@limiter.limit('20 per minute')
def api_room_rate():
    try:
        from database import supabase
        data    = request.get_json(force=True)
        uid     = int(data.get("uid", 0))
        room_id = int(data.get("room_id", 0))
        rating  = int(data.get("rating", 0))
        if not 1 <= rating <= 5:
            return jsonify({"ok": False, "error": "invalid_rating"})

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        # Upsert (insert or update)
        existing = supabase.table("room_ratings_v1") \
            .select("id").eq("room_id", room_id).eq("user_id", my_id).execute()
        if existing.data:
            supabase.table("room_ratings_v1") \
                .update({"rating": rating}) \
                .eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("room_ratings_v1").insert({
                "room_id": room_id, "user_id": my_id, "rating": rating
            }).execute()

        # Return new avg
        all_rat = supabase.table("room_ratings_v1") \
            .select("rating").eq("room_id", room_id).execute()
        vals = [r["rating"] for r in (all_rat.data or [])]
        avg  = round(sum(vals) / len(vals), 1) if vals else 0
        return jsonify({"ok": True, "avg_rating": avg, "rating_count": len(vals)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/user/rate', methods=['POST'])
@limiter.limit('20 per minute')
def api_user_rate():
    try:
        from database import supabase
        data          = request.get_json(force=True)
        uid           = int(data.get("uid", 0))
        target_user_id = int(data.get("target_id", 0))
        rating        = int(data.get("rating", 0))
        if not 1 <= rating <= 5:
            return jsonify({"ok": False, "error": "invalid_rating"})

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        if my_id == target_user_id:
            return jsonify({"ok": False, "error": "self_rate"})

        existing = supabase.table("user_ratings_v1") \
            .select("id").eq("rated_user_id", target_user_id).eq("rater_id", my_id).execute()
        if existing.data:
            supabase.table("user_ratings_v1") \
                .update({"rating": rating}) \
                .eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("user_ratings_v1").insert({
                "rated_user_id": target_user_id, "rater_id": my_id, "rating": rating
            }).execute()

        # Return new avg
        all_rat = supabase.table("user_ratings_v1") \
            .select("rating").eq("rated_user_id", target_user_id).execute()
        vals = [r["rating"] for r in (all_rat.data or [])]
        avg  = round(sum(vals) / len(vals), 1) if vals else 0
        return jsonify({"ok": True, "avg_rating": avg, "rating_count": len(vals)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/room/<int:room_id>/members/<int:telegram_id>')
def api_room_members(room_id, telegram_id):
    """Get room members with their user info and creator's ratings of them."""
    try:
        from database import supabase
        from config import BOT_TOKEN

        me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
        if not me.data:
            return jsonify({"ok": False, "members": []})
        my_id = me.data[0]["id"]

        # Get members
        memb_res = supabase.table("room_members_v1") \
            .select("user_id").eq("room_id", room_id).execute()
        member_ids = [m["user_id"] for m in (memb_res.data or []) if m["user_id"] != my_id]

        if not member_ids:
            return jsonify({"ok": True, "members": []})

        # Fetch user info for each member
        members_out = []
        for uid2 in member_ids:
            try:
                u = supabase.table("users_v1") \
                    .select("id, username, photo_url") \
                    .eq("id", uid2).single().execute()
                if not u.data:
                    continue
                photo = _resolve_photo(u.data.get("photo_url"), BOT_TOKEN)
                # My existing rating for this user
                my_rat = supabase.table("user_ratings_v1") \
                    .select("rating").eq("rated_user_id", uid2).eq("rater_id", my_id).execute()
                my_rating = my_rat.data[0]["rating"] if my_rat.data else 0
                # Avg rating for this user
                all_rat = supabase.table("user_ratings_v1") \
                    .select("rating").eq("rated_user_id", uid2).execute()
                vals = [r["rating"] for r in (all_rat.data or [])]
                avg  = round(sum(vals)/len(vals), 1) if vals else 0
                members_out.append({
                    "user_id":     uid2,
                    "username":    u.data.get("username") or f"User#{uid2}",
                    "photo_url":   photo,
                    "my_rating":   my_rating,
                    "avg_rating":  avg,
                    "rating_count": len(vals),
                })
            except Exception:
                continue

        return jsonify({"ok": True, "members": members_out})
    except Exception as e:
        return jsonify({"ok": False, "members": [], "error": str(e)})


@app.route('/api/stores/<int:telegram_id>')
def api_stores(telegram_id):
    """Return all stores with membership and ownership flags."""
    try:
        from database import supabase
        from collections import defaultdict

        my_id = None
        my_lat, my_lng = None, None

        me_res = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
        if me_res.data:
            my_id = me_res.data[0]["id"]
            loc = supabase.table("user_locations_v1") \
                .select("latitude, longitude").eq("user_id", my_id).limit(1).execute()
            if loc.data:
                my_lat = float(loc.data[0]["latitude"])
                my_lng = float(loc.data[0]["longitude"])

        # Fetch stores
        try:
            stores_res = supabase.table("stores_v1") \
                .select("id, name, latitude, longitude, created_by, created_at, purpose, nature, image_url, expires_at, icon") \
                .execute()
        except Exception:
            stores_res = supabase.table("stores_v1") \
                .select("id, name, latitude, longitude, created_by, created_at") \
                .execute()

        # My memberships
        my_store_ids = set()
        if my_id is not None:
            try:
                memb_res = supabase.table("store_members_v1") \
                    .select("store_id").eq("user_id", my_id).execute()
                my_store_ids = {m["store_id"] for m in (memb_res.data or [])}
            except Exception:
                pass

        stores_out = []
        for s in (stores_res.data or []):
            slat = s.get("latitude")
            slng = s.get("longitude")
            if slat is None or slng is None:
                continue
            dist = None
            if my_lat is not None:
                dist = round(_haversine(my_lat, my_lng, float(slat), float(slng)), 2)

            try:
                cnt = supabase.table("store_members_v1") \
                    .select("id", count="exact").eq("store_id", s["id"]).execute()
                members = cnt.count if cnt.count is not None else 0
            except Exception:
                members = 0

            stores_out.append({
                "id":         s["id"],
                "name":       s.get("name", "Store"),
                "lat":        float(slat),
                "lng":        float(slng),
                "distance":   dist,
                "members":    members,
                "created_at": s.get("created_at"),
                "purpose":    s.get("purpose") or "",
                "nature":     s.get("nature") or "",
                "image_url":  s.get("image_url") or "",
                "expires_at": s.get("expires_at") or "",
                "icon":       s.get("icon") or "🏪",
                "is_creator": (my_id is not None and s.get("created_by") == my_id),
                "is_member":  (s["id"] in my_store_ids),
            })

        # Batch-fetch store ratings
        store_ids = [s["id"] for s in (stores_res.data or []) if s.get("latitude")]
        avg_ratings  = {}
        my_s_ratings = {}
        if store_ids:
            try:
                all_rat = supabase.table("store_ratings_v1").select("store_id, rating").execute()
                bucket = defaultdict(list)
                for row in (all_rat.data or []):
                    bucket[row["store_id"]].append(row["rating"])
                for sid, vals in bucket.items():
                    avg_ratings[sid] = (round(sum(vals)/len(vals), 1), len(vals))
                if my_id is not None:
                    my_rat = supabase.table("store_ratings_v1") \
                        .select("store_id, rating").eq("user_id", my_id).execute()
                    my_s_ratings = {row["store_id"]: row["rating"] for row in (my_rat.data or [])}
            except Exception:
                pass

        for entry in stores_out:
            sid = entry["id"]
            avg, cnt = avg_ratings.get(sid, (0, 0))
            entry["avg_rating"]   = avg
            entry["rating_count"] = cnt
            entry["my_rating"]    = my_s_ratings.get(sid, 0)

        return jsonify({"stores": stores_out, "my_user_id": my_id})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)})


@app.route('/api/store/join', methods=['POST'])
def api_store_join():
    try:
        from database import supabase
        data     = request.get_json(force=True)
        uid      = int(data.get("uid", 0))
        store_id = int(data.get("store_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        existing = supabase.table("store_members_v1") \
            .select("id").eq("store_id", store_id).eq("user_id", my_id).execute()
        if existing.data:
            return jsonify({"ok": True, "already": True})

        supabase.table("store_members_v1").insert({"store_id": store_id, "user_id": my_id}).execute()
        return jsonify({"ok": True, "already": False})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/store/delete', methods=['POST'])
def api_store_delete():
    try:
        from database import supabase
        data     = request.get_json(force=True)
        uid      = int(data.get("uid", 0))
        store_id = int(data.get("store_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        store = supabase.table("stores_v1").select("created_by").eq("id", store_id).single().execute()
        if not store.data or store.data["created_by"] != my_id:
            return jsonify({"ok": False, "error": "not_creator"})

        cnt = supabase.table("store_members_v1") \
            .select("id", count="exact").eq("store_id", store_id).execute()
        if (cnt.count or 0) > 1:
            return jsonify({"ok": False, "error": "has_members"})

        supabase.table("store_members_v1").delete().eq("store_id", store_id).execute()
        supabase.table("stores_v1").delete().eq("id", store_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/store/image/upload', methods=['POST'])
def api_store_image_upload():
    try:
        from database import supabase
        uid      = int(request.form.get("uid", 0))
        store_id = int(request.form.get("store_id", 0))
        file     = request.files.get("image")
        if not file:
            return jsonify({"ok": False, "error": "no_file"})

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        store = supabase.table("stores_v1").select("created_by").eq("id", store_id).single().execute()
        if not store.data or store.data["created_by"] != my_id:
            return jsonify({"ok": False, "error": "not_creator"})

        import os
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
        folder = "static/store_images"
        os.makedirs(folder, exist_ok=True)
        filename = f"store_{store_id}.{ext}"
        path     = f"{folder}/{filename}"
        file.save(path)

        image_url = f"/static/store_images/{filename}"
        supabase.table("stores_v1").update({"image_url": image_url}).eq("id", store_id).execute()
        return jsonify({"ok": True, "image_url": image_url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/store/image/delete', methods=['POST'])
def api_store_image_delete():
    try:
        from database import supabase
        data     = request.get_json(force=True)
        uid      = int(data.get("uid", 0))
        store_id = int(data.get("store_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        store = supabase.table("stores_v1").select("created_by, image_url").eq("id", store_id).single().execute()
        if not store.data or store.data["created_by"] != my_id:
            return jsonify({"ok": False, "error": "not_creator"})

        img_url = store.data.get("image_url") or ""
        if img_url.startswith("/static/"):
            try:
                import os
                os.remove(img_url.lstrip("/"))
            except Exception:
                pass
        supabase.table("stores_v1").update({"image_url": None}).eq("id", store_id).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/store/rate', methods=['POST'])
@limiter.limit('20 per minute')
def api_store_rate():
    try:
        from database import supabase
        data     = request.get_json(force=True)
        uid      = int(data.get("uid", 0))
        store_id = int(data.get("store_id", 0))
        rating   = int(data.get("rating", 0))
        if not 1 <= rating <= 5:
            return jsonify({"ok": False, "error": "invalid_rating"})

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        existing = supabase.table("store_ratings_v1") \
            .select("id").eq("store_id", store_id).eq("user_id", my_id).execute()
        if existing.data:
            supabase.table("store_ratings_v1") \
                .update({"rating": rating}).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("store_ratings_v1").insert({
                "store_id": store_id, "user_id": my_id, "rating": rating
            }).execute()

        all_rat = supabase.table("store_ratings_v1") \
            .select("rating").eq("store_id", store_id).execute()
        vals = [r["rating"] for r in (all_rat.data or [])]
        avg  = round(sum(vals) / len(vals), 1) if vals else 0
        return jsonify({"ok": True, "avg_rating": avg, "rating_count": len(vals)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/store/<int:store_id>/members/<int:telegram_id>')
def api_store_members(store_id, telegram_id):
    try:
        from database import supabase
        from config import BOT_TOKEN

        me = supabase.table("users_v1").select("id").eq("telegram_id", telegram_id).execute()
        if not me.data:
            return jsonify({"ok": False, "members": []})
        my_id = me.data[0]["id"]

        memb_res = supabase.table("store_members_v1") \
            .select("user_id").eq("store_id", store_id).execute()
        member_ids = [m["user_id"] for m in (memb_res.data or []) if m["user_id"] != my_id]

        if not member_ids:
            return jsonify({"ok": True, "members": []})

        members_out = []
        for uid2 in member_ids:
            try:
                u = supabase.table("users_v1") \
                    .select("id, username, photo_url") \
                    .eq("id", uid2).single().execute()
                if not u.data:
                    continue
                photo = _resolve_photo(u.data.get("photo_url"), BOT_TOKEN)
                my_rat = supabase.table("user_ratings_v1") \
                    .select("rating").eq("rated_user_id", uid2).eq("rater_id", my_id).execute()
                my_rating = my_rat.data[0]["rating"] if my_rat.data else 0
                all_rat = supabase.table("user_ratings_v1") \
                    .select("rating").eq("rated_user_id", uid2).execute()
                vals = [r["rating"] for r in (all_rat.data or [])]
                avg  = round(sum(vals)/len(vals), 1) if vals else 0
                members_out.append({
                    "user_id":      uid2,
                    "username":     u.data.get("username") or f"User#{uid2}",
                    "photo_url":    photo,
                    "my_rating":    my_rating,
                    "avg_rating":   avg,
                    "rating_count": len(vals),
                })
            except Exception:
                continue

        return jsonify({"ok": True, "members": members_out})
    except Exception as e:
        return jsonify({"ok": False, "members": [], "error": str(e)})


# ══════════════════════════════════════════════════════════════════════════
#  CATALOG ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════

CATALOG_CATS_STORE = ['product','menu_food','menu_drink','clothing',
                      'accessory','other','contact','hours']
CATALOG_CATS_ROOM  = ['service','event','meeting','offer','info','contact']


@app.route('/api/catalog/<entity_type>/<int:entity_id>')
def api_catalog_get(entity_type, entity_id):
    try:
        rows = (supabase.table('catalogs_v1')
                .select('*')
                .eq('entity_type', entity_type)
                .eq('entity_id',   entity_id)
                .order('sort_order')
                .order('created_at')
                .execute().data or [])
        return jsonify({'ok': True, 'items': rows})
    except Exception as e:
        return jsonify({'ok': False, 'items': [], 'error': str(e)})


@app.route('/api/catalog/add', methods=['POST'])
def api_catalog_add():
    try:
        d = request.get_json(force=True) or {}
        uid         = int(d.get('uid', 0))
        entity_type = d.get('entity_type', '')
        entity_id   = int(d.get('entity_id', 0))
        if not uid or entity_type not in ('room','store') or not entity_id:
            return jsonify({'ok': False, 'error': 'invalid params'}), 400

        # ownership check
        tbl = 'rooms_v1' if entity_type == 'room' else 'stores_v1'
        owner = supabase.table(tbl).select('created_by').eq('id', entity_id).execute().data
        if not owner or int(owner[0]['created_by']) != uid:
            return jsonify({'ok': False, 'error': 'not owner'}), 403

        row = {
            'entity_type': entity_type,
            'entity_id':   entity_id,
            'category':    d.get('category', 'general'),
            'title':       (d.get('title') or '').strip()[:120],
            'description': (d.get('description') or '').strip()[:400],
            'price':       float(d['price']) if d.get('price') not in (None,'') else None,
            'currency':    d.get('currency', 'SAR'),
            'phone':       (d.get('phone') or '').strip()[:40],
            'website':     (d.get('website') or '').strip()[:200],
            'hours':       (d.get('hours') or '').strip()[:200],
            'sort_order':  int(d.get('sort_order', 0)),
            'created_by':  uid,
        }
        if not row['title']:
            return jsonify({'ok': False, 'error': 'title required'}), 400

        res = supabase.table('catalogs_v1').insert(row).execute()
        return jsonify({'ok': True, 'item': res.data[0] if res.data else {}})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/catalog/delete', methods=['POST'])
def api_catalog_delete():
    try:
        d   = request.get_json(force=True) or {}
        uid = int(d.get('uid', 0))
        cid = int(d.get('id', 0))
        if not uid or not cid:
            return jsonify({'ok': False, 'error': 'invalid params'}), 400

        row = supabase.table('catalogs_v1').select('created_by,image_url').eq('id', cid).execute().data
        if not row:
            return jsonify({'ok': False, 'error': 'not found'}), 404
        if int(row[0]['created_by']) != uid:
            return jsonify({'ok': False, 'error': 'not owner'}), 403

        # delete image file if present
        img = row[0].get('image_url', '')
        if img:
            path = img.lstrip('/')
            try:
                import os as _os
                if _os.path.exists(path):
                    _os.remove(path)
            except Exception:
                pass

        supabase.table('catalogs_v1').delete().eq('id', cid).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/catalog/image/upload', methods=['POST'])
def api_catalog_image_upload():
    try:
        uid = int(request.form.get('uid', 0))
        cid = int(request.form.get('id', 0))
        f   = request.files.get('image')
        if not uid or not cid or not f:
            return jsonify({'ok': False, 'error': 'missing fields'}), 400

        row = supabase.table('catalogs_v1').select('created_by').eq('id', cid).execute().data
        if not row or int(row[0]['created_by']) != uid:
            return jsonify({'ok': False, 'error': 'not owner'}), 403

        import os as _os
        ext = (f.filename or 'jpg').rsplit('.', 1)[-1].lower()
        if ext not in ('jpg','jpeg','png','webp','gif'):
            ext = 'jpg'
        folder = 'static/catalog_images'
        _os.makedirs(folder, exist_ok=True)
        path = f'{folder}/cat_{cid}.{ext}'
        f.save(path)
        url  = '/' + path

        supabase.table('catalogs_v1').update({'image_url': url}).eq('id', cid).execute()
        return jsonify({'ok': True, 'url': url})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/entity/edit', methods=['POST'])
def api_entity_edit():
    """Update name, purpose, and nature of a room or store (creator only)."""
    try:
        data        = request.get_json(force=True) or {}
        uid         = int(data.get('uid', 0))
        entity_type = data.get('entity_type', '')   # 'room' | 'store'
        entity_id   = int(data.get('entity_id', 0))
        new_name    = (data.get('name') or '').strip()
        new_purpose = (data.get('purpose') or '').strip()
        new_nature  = (data.get('nature') or '').strip()

        if not uid or entity_type not in ('room', 'store') or not entity_id:
            return jsonify({'ok': False, 'error': 'invalid params'}), 400
        if not new_name:
            return jsonify({'ok': False, 'error': 'name required'}), 400
        if len(new_name) > 60:
            return jsonify({'ok': False, 'error': 'name too long'}), 400

        tbl = 'rooms_v1' if entity_type == 'room' else 'stores_v1'

        # Verify ownership
        user_res = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not user_res.data:
            return jsonify({'ok': False, 'error': 'user not found'}), 404
        user_db_id = user_res.data[0]["id"]

        entity_res = supabase.table(tbl).select("created_by").eq("id", entity_id).execute()
        if not entity_res.data:
            return jsonify({'ok': False, 'error': 'entity not found'}), 404
        if entity_res.data[0].get("created_by") != user_db_id:
            return jsonify({'ok': False, 'error': 'not creator'}), 403

        supabase.table(tbl).update({
            "name":    new_name,
            "purpose": new_purpose or None,
            "nature":  new_nature  or None,
        }).eq("id", entity_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/entity/set_icon', methods=['POST'])
def api_set_entity_icon():
    """Update the emoji icon of a room or store (creator only)."""
    try:
        data        = request.get_json(force=True) or {}
        uid         = int(data.get('uid', 0))
        entity_type = data.get('entity_type', '')   # 'room' | 'store'
        entity_id   = int(data.get('entity_id', 0))
        icon        = (data.get('icon') or '').strip()

        if not uid or entity_type not in ('room', 'store') or not entity_id or not icon:
            return jsonify({'ok': False, 'error': 'invalid params'}), 400

        # Validate emoji is single grapheme cluster (cheap sanity check)
        if len(icon) > 8:
            return jsonify({'ok': False, 'error': 'invalid icon'}), 400

        tbl = 'rooms_v1' if entity_type == 'room' else 'stores_v1'

        # Verify ownership
        user_res = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not user_res.data:
            return jsonify({'ok': False, 'error': 'user not found'}), 404
        user_db_id = user_res.data[0]["id"]

        entity_res = supabase.table(tbl).select("created_by").eq("id", entity_id).execute()
        if not entity_res.data:
            return jsonify({'ok': False, 'error': 'entity not found'}), 404
        if entity_res.data[0].get("created_by") != user_db_id:
            return jsonify({'ok': False, 'error': 'not creator'}), 403

        supabase.table(tbl).update({"icon": icon}).eq("id", entity_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/update_location', methods=['POST'])
def api_update_location():
    """Receive live GPS from the browser and persist it to Supabase."""
    try:
        data = request.get_json(force=True) or {}
        uid  = int(data.get('uid', 0))
        lat  = float(data.get('lat', 0))
        lng  = float(data.get('lng', 0))
        acc  = float(data.get('accuracy', 999))
        if not uid:
            return jsonify({"ok": False, "error": "missing uid"}), 400
        # Only accept fixes better than 200 m accuracy
        if acc > 200:
            return jsonify({"ok": False, "error": "accuracy too low"}), 200
        supabase.table("users_v1").update({
            "latitude":    lat,
            "longitude":   lng,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }).eq("telegram_id", uid).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# CHAT SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/public-chat')
def public_chat_page():
    return render_template("public_chat.html")

@app.route('/private-chat')
def private_chat_page():
    return render_template("private_chat.html")

@app.route('/group-chat')
def group_chat_page():
    return render_template("group_chat.html")


# ── Chat: upload file / image / voice ──────────────────────────────────────
@app.route('/api/chat/upload', methods=['POST'])
def api_chat_upload():
    try:
        import uuid as _uuid
        uid       = int(request.form.get("uid", 0))
        file_type = request.form.get("file_type", "file")
        f         = request.files.get("file")
        if not f:
            return jsonify({"ok": False, "error": "no_file"})

        if file_type == "voice":
            folder, ext = "static/voice_msgs", "webm"
        elif file_type == "image":
            raw = (f.filename.rsplit(".", 1)[-1].lower()
                   if f.filename and "." in f.filename else "jpg")
            ext    = raw if raw in ("jpg","jpeg","png","webp","gif") else "jpg"
            folder = "static/chat_imgs"
        else:
            raw    = (f.filename.rsplit(".", 1)[-1].lower()
                      if f.filename and "." in f.filename else "bin")
            ext    = raw[:8]
            folder = "static/chat_files"

        os.makedirs(folder, exist_ok=True)
        fname    = f"{folder}/u{uid}_{_uuid.uuid4().hex[:8]}.{ext}"
        file_url = f"/{fname}"
        f.save(fname)
        return jsonify({"ok": True, "file_url": file_url,
                        "file_name": f.filename or f"file.{ext}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Room chat: join via WebApp button ─────────────────────────────────────
@app.route('/api/chat/room/join', methods=['POST'])
def api_room_chat_join():
    """Send a Telegram bot message to start a room chat session."""
    try:
        from database import supabase
        from config import BOT_TOKEN
        import httpx
        data    = request.get_json(force=True)
        uid     = int(data.get("uid", 0))
        room_id = int(data.get("room_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})

        room = supabase.table("rooms_v1").select("name").eq("id", room_id).execute()
        room_name = room.data[0]["name"] if room.data else "?"

        lang_row = supabase.table("users_v1").select("language").eq("telegram_id", uid).execute()
        lang = (lang_row.data[0].get("language") or "ar") if lang_row.data else "ar"

        text = (f"🏠 اضغط الزر للدخول إلى دردشة غرفة «{room_name}»"
                if lang == "ar" else
                f"🏠 Tap the button to join the group chat of room «{room_name}»")
        btn_label = ("💬 دخول الدردشة" if lang == "ar" else "💬 Join Room Chat")

        payload = {
            "chat_id": uid,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": btn_label, "callback_data": f"room_chat_sel:{room_id}"}
                ]]
            }
        }
        resp = httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload, timeout=10
        )
        return jsonify({"ok": resp.json().get("ok", False)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Store chat: join via WebApp button ─────────────────────────────────────
@app.route('/api/chat/store/join', methods=['POST'])
def api_store_chat_join():
    """Send a Telegram bot message to start a store chat session."""
    try:
        from database import supabase
        from config import BOT_TOKEN
        import httpx
        data     = request.get_json(force=True)
        uid      = int(data.get("uid", 0))
        store_id = int(data.get("store_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})

        store = supabase.table("stores_v1").select("name").eq("id", store_id).execute()
        store_name = store.data[0]["name"] if store.data else "?"

        lang_row = supabase.table("users_v1").select("language").eq("telegram_id", uid).execute()
        lang = (lang_row.data[0].get("language") or "ar") if lang_row.data else "ar"

        text = (f"🏪 اضغط الزر للدخول إلى دردشة متجر «{store_name}»"
                if lang == "ar" else
                f"🏪 Tap the button to join the group chat of store «{store_name}»")
        btn_label = ("💬 دخول الدردشة" if lang == "ar" else "💬 Join Store Chat")

        payload = {
            "chat_id": uid,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": btn_label, "callback_data": f"store_chat_sel:{store_id}"}
                ]]
            }
        }
        resp = httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload, timeout=10
        )
        return jsonify({"ok": resp.json().get("ok", False)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Public chat: send message ──────────────────────────────────────────────
@app.route('/api/chat/public/send', methods=['POST'])
@limiter.limit('30 per minute')
def api_public_send():
    try:
        from database import supabase
        data = request.get_json(force=True)
        uid  = int(data.get("uid", 0))

        me = supabase.table("users_v1") \
            .select("id,city,country") \
            .eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my = me.data[0]

        content = (data.get("content") or "").strip()
        if not content and not data.get("file_url"):
            return jsonify({"ok": False, "error": "empty"})

        # Get location from user_locations_v1
        my_lat, my_lng = None, None
        try:
            loc = supabase.table("user_locations_v1") \
                .select("latitude,longitude") \
                .eq("user_id", my["id"]).limit(1).execute()
            if loc.data:
                my_lat = float(loc.data[0]["latitude"])
                my_lng = float(loc.data[0]["longitude"])
        except Exception:
            pass

        row = {
            "sender_id": my["id"],
            "content":   content,
            "msg_type":  data.get("msg_type", "text"),
            "file_url":  data.get("file_url"),
            "file_name": data.get("file_name"),
            "duration":  data.get("duration"),
            "lat":       my_lat,
            "lng":       my_lng,
            "city":      my.get("city"),
            "country":   my.get("country"),
        }
        res = supabase.table("public_messages_v1").insert(row).execute()
        new_id = res.data[0]["id"] if res.data else None
        return jsonify({"ok": True, "id": new_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Public chat: fetch messages ────────────────────────────────────────────
@app.route('/api/chat/public/messages')
def api_public_messages():
    try:
        from database import supabase
        from config import BOT_TOKEN

        uid     = int(request.args.get("uid", 0))
        radius  = request.args.get("radius", "all")   # 100m|500m|1km|10km|city|country|all
        last_id = int(request.args.get("last_id", 0))

        # Viewer info
        me = supabase.table("users_v1") \
            .select("id,city,country") \
            .eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my     = me.data[0]

        # Get viewer location from user_locations_v1
        my_lat, my_lng = None, None
        try:
            loc = supabase.table("user_locations_v1") \
                .select("latitude,longitude") \
                .eq("user_id", my["id"]).limit(1).execute()
            if loc.data:
                my_lat = float(loc.data[0]["latitude"])
                my_lng = float(loc.data[0]["longitude"])
        except Exception:
            pass

        # Build query
        q = supabase.table("public_messages_v1").select(
            "id,sender_id,content,msg_type,file_url,file_name,duration,"
            "lat,lng,city,country,created_at"
        ).order("created_at", desc=True).limit(200)

        if last_id:
            q = q.gt("id", last_id)

        # Server-side city/country filter
        if radius == "city" and my.get("city"):
            q = q.eq("city", my["city"])
        elif radius == "country" and my.get("country"):
            q = q.eq("country", my["country"])

        msgs = q.execute()

        # km radius mapping
        radius_km = {"100m": 0.1, "500m": 0.5, "1km": 1.0, "10km": 10.0}.get(radius)

        sender_cache = {}
        result = []
        for m in msgs.data:
            if radius_km and my_lat and my_lng:
                mlat = m.get("lat")
                mlng = m.get("lng")
                if not mlat or not mlng:
                    continue
                if _haversine(float(my_lat), float(my_lng),
                               float(mlat), float(mlng)) > radius_km:
                    continue

            sid = m["sender_id"]
            if sid not in sender_cache:
                u = supabase.table("users_v1") \
                    .select("id,telegram_id,username,first_name,photo_url") \
                    .eq("id", sid).execute()
                if u.data:
                    d = u.data[0]
                    sender_cache[sid] = {
                        "tg_id":   d.get("telegram_id"),
                        "name":    d.get("first_name") or d.get("username") or "مستخدم",
                        "photo":   _resolve_photo(d.get("photo_url"), BOT_TOKEN),
                    }
                else:
                    sender_cache[sid] = {"tg_id": None, "name": "مستخدم", "photo": None}
            s = sender_cache[sid]

            dist_str = None
            if my_lat and my_lng and m.get("lat") and m.get("lng"):
                d = _haversine(float(my_lat), float(my_lng),
                                float(m["lat"]), float(m["lng"]))
                dist_str = f"{int(d*1000)} م" if d < 1 else f"{round(d,1)} كم"

            result.append({
                "id":           m["id"],
                "sender_id":    sid,
                "sender_tg_id": s["tg_id"],
                "sender_name":  s["name"],
                "sender_photo": s["photo"],
                "content":      m.get("content") or "",
                "msg_type":     m.get("msg_type") or "text",
                "file_url":     m.get("file_url"),
                "file_name":    m.get("file_name"),
                "duration":     m.get("duration"),
                "distance":     dist_str,
                "city":         m.get("city"),
                "created_at":   m["created_at"],
                "is_mine":      sid == my["id"],
            })

        result.sort(key=lambda x: x["created_at"])
        return jsonify({"ok": True, "messages": result, "my_db_id": my["id"]})
    except Exception as e:
        err = str(e)
        # Table doesn't exist yet — return empty gracefully
        if "PGRST205" in err or "Could not find the table" in err:
            return jsonify({"ok": True, "messages": [], "my_db_id": None,
                            "_hint": "run_sql_migration"})
        return jsonify({"ok": False, "error": err})


# ── Private chat: send message ─────────────────────────────────────────────
@app.route('/api/chat/private/send', methods=['POST'])
@limiter.limit('30 per minute')
def api_private_send():
    try:
        from database import supabase
        data      = request.get_json(force=True)
        uid       = int(data.get("uid", 0))
        other_uid = int(data.get("other_uid", 0))

        me    = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        other = supabase.table("users_v1").select("id").eq("telegram_id", other_uid).execute()
        if not me.data or not other.data:
            return jsonify({"ok": False, "error": "not_found"})

        content = (data.get("content") or "").strip()
        if not content and not data.get("file_url"):
            return jsonify({"ok": False, "error": "empty"})

        row = {
            "sender_id":   me.data[0]["id"],
            "receiver_id": other.data[0]["id"],
            "content":     content,
            "msg_type":    data.get("msg_type", "text"),
            "file_url":    data.get("file_url"),
            "file_name":   data.get("file_name"),
            "duration":    data.get("duration"),
        }
        res = supabase.table("private_messages_v1").insert(row).execute()
        return jsonify({"ok": True, "id": res.data[0]["id"] if res.data else None})
    except Exception as e:
        err = str(e)
        if "PGRST205" in err or "Could not find the table" in err:
            return jsonify({"ok": False, "error": "table_missing",
                            "_hint": "run_sql_migration"})
        return jsonify({"ok": False, "error": err})


# ── Private chat: fetch messages ───────────────────────────────────────────
@app.route('/api/chat/private/messages')
def api_private_messages():
    try:
        from database import supabase
        from config import BOT_TOKEN

        uid       = int(request.args.get("uid", 0))
        other_uid = int(request.args.get("other_uid", 0))
        last_id   = int(request.args.get("last_id", 0))

        me    = supabase.table("users_v1") \
            .select("id,username,first_name,photo_url").eq("telegram_id", uid).execute()
        other = supabase.table("users_v1") \
            .select("id,username,first_name,photo_url").eq("telegram_id", other_uid).execute()
        if not me.data or not other.data:
            return jsonify({"ok": False, "error": "not_found"})

        my_id    = me.data[0]["id"]
        other_id = other.data[0]["id"]

        # Mark incoming as read
        try:
            supabase.table("private_messages_v1") \
                .update({"read_at": datetime.now(timezone.utc).isoformat()}) \
                .eq("sender_id", other_id).eq("receiver_id", my_id) \
                .is_("read_at", "null").execute()
        except Exception:
            pass

        q = supabase.table("private_messages_v1").select(
            "id,sender_id,receiver_id,content,msg_type,file_url,file_name,duration,read_at,created_at"
        ).or_(
            f"and(sender_id.eq.{my_id},receiver_id.eq.{other_id}),"
            f"and(sender_id.eq.{other_id},receiver_id.eq.{my_id})"
        ).order("created_at", desc=False).limit(100)

        if last_id:
            q = q.gt("id", last_id)

        msgs = q.execute()
        od   = other.data[0]
        other_info = {
            "telegram_id": other_uid,
            "name":  od.get("first_name") or od.get("username") or "مستخدم",
            "photo": _resolve_photo(od.get("photo_url"), BOT_TOKEN),
        }

        result = [{
            "id":        m["id"],
            "is_mine":   m["sender_id"] == my_id,
            "content":   m.get("content") or "",
            "msg_type":  m.get("msg_type") or "text",
            "file_url":  m.get("file_url"),
            "file_name": m.get("file_name"),
            "duration":  m.get("duration"),
            "read_at":   m.get("read_at"),
            "created_at":m["created_at"],
        } for m in msgs.data]

        return jsonify({"ok": True, "messages": result,
                        "other": other_info, "my_id": my_id})
    except Exception as e:
        err = str(e)
        if "PGRST205" in err or "Could not find the table" in err:
            od = other.data[0] if 'other' in dir() and other.data else {}
            return jsonify({"ok": True, "messages": [], "other": {
                "telegram_id": other_uid,
                "name": od.get("first_name") or od.get("username") or "مستخدم",
                "photo": None,
            }, "my_id": None, "_hint": "run_sql_migration"})
        return jsonify({"ok": False, "error": err})


# ── Private chat: list conversations ──────────────────────────────────────
@app.route('/api/chat/private/conversations')
def api_private_conversations():
    try:
        from database import supabase
        from config import BOT_TOKEN
        uid = int(request.args.get("uid", 0))
        me  = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "not_found"})
        my_id = me.data[0]["id"]

        # Get all messages involving me, pick latest per partner
        sent = supabase.table("private_messages_v1") \
            .select("id,sender_id,receiver_id,content,msg_type,created_at,read_at") \
            .or_(f"sender_id.eq.{my_id},receiver_id.eq.{my_id}") \
            .order("created_at", desc=True).limit(500).execute()

        seen = {}
        for m in sent.data:
            partner = m["receiver_id"] if m["sender_id"] == my_id else m["sender_id"]
            if partner not in seen:
                seen[partner] = m

        result = []
        for partner_id, last_msg in seen.items():
            u = supabase.table("users_v1") \
                .select("id,telegram_id,username,first_name,photo_url") \
                .eq("id", partner_id).execute()
            if not u.data:
                continue
            d = u.data[0]
            unread = supabase.table("private_messages_v1") \
                .select("id", count="exact") \
                .eq("sender_id", partner_id).eq("receiver_id", my_id) \
                .is_("read_at", "null").execute()
            result.append({
                "partner_tg_id": d.get("telegram_id"),
                "partner_name":  d.get("first_name") or d.get("username") or "مستخدم",
                "partner_photo": _resolve_photo(d.get("photo_url"), BOT_TOKEN),
                "last_content":  last_msg.get("content") or f"[{last_msg.get('msg_type','file')}]",
                "last_time":     last_msg["created_at"],
                "unread":        unread.count or 0,
                "is_mine":       last_msg["sender_id"] == my_id,
            })
        result.sort(key=lambda x: x["last_time"], reverse=True)
        return jsonify({"ok": True, "conversations": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ══════════════════════════════════════════════════════════════════════════
#  GROUP CHAT  (rooms & stores web-based chat)
# ══════════════════════════════════════════════════════════════════════════

@app.route('/api/chat/group/info')
def api_group_chat_info():
    """Return group name, member count, and membership status."""
    try:
        from database import supabase
        from config import BOT_TOKEN

        uid   = int(request.args.get("uid", 0))
        gtype = request.args.get("type", "room")
        gid   = int(request.args.get("id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "user_not_found"})
        my_id = me.data[0]["id"]

        if gtype == "room":
            grp = supabase.table("rooms_v1").select("id,name,created_by").eq("id", gid).execute()
            if not grp.data:
                return jsonify({"ok": False, "error": "room_not_found"})
            grp_data = grp.data[0]
            memb = supabase.table("room_members_v1").select("user_id").eq("room_id", gid).execute()
            member_ids = [m["user_id"] for m in (memb.data or [])]
            is_member = my_id in member_ids or grp_data.get("created_by") == my_id
            count = len(member_ids)
        else:
            grp = supabase.table("stores_v1").select("id,name,created_by").eq("id", gid).execute()
            if not grp.data:
                return jsonify({"ok": False, "error": "store_not_found"})
            grp_data = grp.data[0]
            memb = supabase.table("store_members_v1").select("user_id").eq("store_id", gid).execute()
            member_ids = [m["user_id"] for m in (memb.data or [])]
            is_member = my_id in member_ids or grp_data.get("created_by") == my_id
            count = len(member_ids)

        return jsonify({
            "ok": True,
            "name": grp_data.get("name", ""),
            "member_count": count,
            "is_member": is_member,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/chat/group/messages')
def api_group_chat_messages():
    """Return messages for a room or store chat."""
    try:
        from database import supabase
        from config import BOT_TOKEN

        uid     = int(request.args.get("uid", 0))
        gtype   = request.args.get("type", "room")
        gid     = int(request.args.get("id", 0))
        last_id = int(request.args.get("last_id", 0))

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "user_not_found"})
        my_id = me.data[0]["id"]

        table = "room_messages_v1" if gtype == "room" else "store_messages_v1"
        fk    = "room_id"           if gtype == "room" else "store_id"

        try:
            msgs = supabase.table(table) \
                .select("id,sender_id,content,msg_type,file_url,file_name,duration,created_at") \
                .eq(fk, gid) \
                .gt("id", last_id) \
                .order("id", desc=False) \
                .limit(100).execute()
        except Exception as ex:
            if "PGRST205" in str(ex) or "does not exist" in str(ex).lower():
                return jsonify({"ok": True, "messages": [], "my_db_id": my_id})
            raise

        result = []
        for m in (msgs.data or []):
            sender_id = m["sender_id"]
            u = supabase.table("users_v1") \
                .select("telegram_id,username,first_name,photo_url") \
                .eq("id", sender_id).execute()
            if not u.data:
                continue
            ud = u.data[0]
            photo = _resolve_photo(ud.get("photo_url"), BOT_TOKEN)
            result.append({
                "id":           m["id"],
                "sender_tg_id": str(ud.get("telegram_id", "")),
                "sender_name":  ud.get("first_name") or ud.get("username") or "مستخدم",
                "sender_photo": photo,
                "content":      m.get("content") or "",
                "msg_type":     m.get("msg_type") or "text",
                "file_url":     m.get("file_url") or "",
                "file_name":    m.get("file_name") or "",
                "duration":     m.get("duration") or 0,
                "created_at":   m["created_at"],
                "is_mine":      sender_id == my_id,
            })

        return jsonify({"ok": True, "messages": result, "my_db_id": my_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/api/chat/group/send', methods=['POST'])
@limiter.limit('30 per minute')
def api_group_chat_send():
    """Send a message to a room or store group chat."""
    try:
        from database import supabase

        data    = request.get_json(force=True)
        uid     = int(data.get("uid", 0))
        gtype   = data.get("type", "room")
        gid     = int(data.get("id", 0))
        content = (data.get("content") or "").strip()
        mtype   = data.get("msg_type", "text")
        furl    = data.get("file_url", "")
        fname   = data.get("file_name", "")
        dur     = data.get("duration", 0)

        me = supabase.table("users_v1").select("id").eq("telegram_id", uid).execute()
        if not me.data:
            return jsonify({"ok": False, "error": "user_not_found"})
        my_id = me.data[0]["id"]

        # Membership check
        if gtype == "room":
            grp = supabase.table("rooms_v1").select("created_by").eq("id", gid).execute()
            creator = grp.data[0]["created_by"] if grp.data else None
            memb = supabase.table("room_members_v1").select("user_id") \
                .eq("room_id", gid).eq("user_id", my_id).execute()
            is_member = bool(memb.data) or creator == my_id
        else:
            grp = supabase.table("stores_v1").select("created_by").eq("id", gid).execute()
            creator = grp.data[0]["created_by"] if grp.data else None
            memb = supabase.table("store_members_v1").select("user_id") \
                .eq("store_id", gid).eq("user_id", my_id).execute()
            is_member = bool(memb.data) or creator == my_id

        if not is_member:
            return jsonify({"ok": False, "error": "not_member"})

        table = "room_messages_v1" if gtype == "room" else "store_messages_v1"
        fk    = "room_id"           if gtype == "room" else "store_id"

        row = {fk: gid, "sender_id": my_id, "content": content,
               "msg_type": mtype, "file_url": furl, "file_name": fname, "duration": dur}
        supabase.table(table).insert(row).execute()

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route('/health')
def health():
    _raw = os.environ.get("REPLIT_DOMAINS", "")
    used = (
        os.environ.get("APP_DOMAIN", "").strip()
        or (_raw.split(",")[0].strip() if _raw else "")
        or os.environ.get("REPLIT_DEV_DOMAIN", "")
    )
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "domain": used,
        "REPLIT_DOMAINS": _raw,
        "APP_DOMAIN": os.environ.get("APP_DOMAIN", ""),
        "REPLIT_DEV_DOMAIN": os.environ.get("REPLIT_DEV_DOMAIN", ""),
        "REPLIT_DEPLOYMENT": os.environ.get("REPLIT_DEPLOYMENT", ""),
    })


def _self_ping_loop():
    """Ping our own /health every 4 minutes to prevent Replit from sleeping."""
    _raw = os.environ.get("REPLIT_DOMAINS", "")
    domain = (
        os.environ.get("APP_DOMAIN", "").strip()
        or (_raw.split(",")[0].strip() if _raw else "")
        or os.environ.get("REPLIT_DEV_DOMAIN", "")
    )
    if not domain:
        _ka_logger.warning("No domain env var set — self-ping disabled.")
        return
    url = f"https://{domain}/health"
    _ka_logger.info(f"Self-ping started → {url}")
    while True:
        time.sleep(240)   # every 4 minutes
        try:
            r = httpx.get(url, timeout=10)
            _ka_logger.debug(f"Self-ping OK: {r.status_code}")
        except Exception as e:
            _ka_logger.warning(f"Self-ping failed: {e}")


def run():
    app.run(host='0.0.0.0', port=5000, threaded=True)


def keep_alive():
    # Flask server thread
    flask_thread = Thread(target=run, name="flask-server")
    flask_thread.daemon = True
    flask_thread.start()

    # Self-ping thread to keep Replit awake
    ping_thread = Thread(target=_self_ping_loop, name="self-pinger")
    ping_thread.daemon = True
    ping_thread.start()
