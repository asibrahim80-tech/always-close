from flask import Flask, render_template, jsonify, request
from threading import Thread
from math import radians, sin, cos, sqrt, atan2
import httpx

app = Flask(__name__)


@app.route('/')
def home():
    return render_template("index.html")


@app.route('/map')
def map_page():
    return render_template("map.html")


@app.route('/api/nearby/<int:telegram_id>')
def api_nearby(telegram_id):
    try:
        from database import supabase
        from config import BOT_TOKEN

        # Get current user
        me_res = supabase.table("users_v1") \
            .select("id, username") \
            .eq("telegram_id", telegram_id) \
            .execute()

        if not me_res.data:
            return jsonify({"error": "User not found. Please register first."})

        my_id   = me_res.data[0]["id"]
        my_name = me_res.data[0].get("username") or "You"

        # Get my location
        loc_res = supabase.table("user_locations_v1") \
            .select("latitude, longitude") \
            .eq("user_id", my_id) \
            .limit(1) \
            .execute()

        if not loc_res.data:
            return jsonify({"error": "Share your location first."})

        my_lat = float(loc_res.data[0]["latitude"])
        my_lng = float(loc_res.data[0]["longitude"])

        # Get all other visible users
        all_users = supabase.table("users_v1") \
            .select("id, username, age, gender, bio, photo_url") \
            .eq("is_active", True) \
            .eq("is_visible", True) \
            .neq("id", my_id) \
            .execute()

        nearby = []
        for u in all_users.data:
            loc = supabase.table("user_locations_v1") \
                .select("latitude, longitude") \
                .eq("user_id", u["id"]) \
                .limit(1) \
                .execute()

            if not loc.data:
                continue

            ulat = float(loc.data[0]["latitude"])
            ulng = float(loc.data[0]["longitude"])

            # Haversine distance
            dlat = radians(ulat - my_lat)
            dlng = radians(ulng - my_lng)
            a = (sin(dlat / 2) ** 2
                 + cos(radians(my_lat)) * cos(radians(ulat)) * sin(dlng / 2) ** 2)
            dist = round(6371 * 2 * atan2(sqrt(a), sqrt(1 - a)), 2)

            # Resolve file_id → real photo URL for browser display
            photo_url = None
            file_id = u.get("photo_url")
            if file_id:
                try:
                    r = httpx.get(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
                        params={"file_id": file_id},
                        timeout=5,
                    )
                    if r.status_code == 200:
                        fp = r.json()["result"]["file_path"]
                        photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}"
                except Exception:
                    pass

            nearby.append({
                "id":        u["id"],
                "username":  u.get("username"),
                "age":       u.get("age"),
                "gender":    u.get("gender"),
                "bio":       u.get("bio"),
                "photo_url": photo_url,
                "lat":       ulat,
                "lng":       ulng,
                "distance":  dist,
            })

        nearby.sort(key=lambda x: x["distance"])

        return jsonify({
            "me":     {"lat": my_lat, "lng": my_lng, "name": my_name},
            "nearby": nearby,
        })

    except Exception as e:
        return jsonify({"error": str(e)})


def run():
    app.run(host='0.0.0.0', port=5000, threaded=True)


def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
