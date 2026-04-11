from flask import Flask, render_template, jsonify, request
from threading import Thread
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime, timezone
import httpx
import os

app = Flask(__name__)

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
                .select("id, name, latitude, longitude, created_by, created_at, purpose, nature, image_url") \
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


def run():
    app.run(host='0.0.0.0', port=5000, threaded=True)


def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
