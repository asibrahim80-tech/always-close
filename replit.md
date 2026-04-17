# Always Close — Telegram Matchmaking Mini App

## Overview
A Telegram Mini App (and Bot) that lets users register profiles, share their location, find nearby people, join rooms/stores, and like/match with others. The backend is a Flask web server, the database is Supabase, and all bot interactions use `python-telegram-bot`.

## Project Structure
- `main.py` — Entry point; starts Flask server and (in production) the Telegram bot polling
- `handlers.py` — Core bot logic: profile creation, location, likes, matching, relay chat
- `database.py` — Supabase client initialization (graceful if credentials missing)
- `config.py` — Loads environment variables; warns (does not crash) if any are missing
- `lang.py` — Multi-language support (English + Arabic)
- `keep_alive.py` — Flask web server (runs in background thread on port 5000); all API routes
- `security.py` — Telegram WebApp initData validation and input sanitization
- `helpers.py` — Haversine distance calculation utilities
- `templates/` — HTML templates for the Mini App UI
- `static/` — Static assets (service worker, profile photos)

## Required Secrets
Set these in the Replit Secrets tab before the bot and database features will work:
- `BOT_TOKEN` — Telegram bot token from @BotFather
- `SUPABASE_URL` — Your Supabase project URL
- `SUPABASE_KEY` — Your Supabase anon or service role key

## Running
The app runs via `python main.py`. This starts:
1. A Flask web server on port 5000 (background thread) — always runs
2. The Telegram bot using long-polling — only in production (when `APP_DOMAIN` or `REPLIT_DEPLOYMENT` env var is set)

## Key Dependencies
- `python-telegram-bot>=20.0` — Telegram bot framework
- `flask` — Web server for the Mini App
- `flask-socketio` + `simple-websocket` — Real-time WebSocket server (threading mode)
- `flask-limiter` — Rate limiting for API endpoints
- `supabase` — Database client (for users, locations, photos, etc.)
- `psycopg2-binary` — Available but no longer used for chat (chat migrated to Supabase)
- `geohash2` — Geospatial indexing for nearby user/room/store search
- `httpx` — HTTP client (resolving Telegram photo URLs)
- `openai` — AI features
- `gunicorn` — Production WSGI server

## Database (Supabase)
Tables used:
- `users_v1` — User profiles
- `user_locations_v1` — Latest lat/lng + geohash per user
- `user_photos_v1` — Extra profile photos
- `user_ratings_v1` — Star ratings between users
- `likes_v1` — Like records between users
- `matches_v1` — Mutual match records
- `rooms_v1` / `room_members_v1` — Group rooms
- `stores_v1` / `store_members_v1` — Stores/businesses
- `objects_v1` / `object_members_v1` — Objects (item listings)

## Real-time Chat System (New)
New files:
- `socketio_init.py` — SocketIO instance (threading mode, no eventlet)
- `chat_handlers.py` — All SocketIO event handlers (join/leave room, send_msg, typing, mark_seen, online/offline)
- `chat_db.py` — Supabase client functions for chat (conversations, participants, messages)
- `templates/chat.html` — Conversation list (WhatsApp-like dark theme, RTL, real-time unread counts)
- `templates/chat_room.html` — Chat room (bubbles, typing indicator, status icons ✓/✓✓/✓✓👁, emoji picker)

Chat DB tables (Supabase — same project as all other tables):
- `conversations` — id(uuid), type(private/group/public), name, created_by, created_at
- `participants` — conversation_id, user_id(TEXT = Telegram ID), joined_at
- `messages` — conversation_id, sender_id(TEXT), content, status(sent/delivered/seen), created_at

Page routes:
- `GET /chat?uid=<tg_id>` — Chat list
- `GET /chat/<conv_id>?uid=<tg_id>` — Chat room

API routes:
- `GET /api/chat/conversations?uid=<tg_id>` — User's conversations
- `GET /api/chat/unread?uid=<tg_id>` — Unread counts
- `GET /api/chat/messages/<conv_id>` — Messages (paginated)
- `POST /api/chat/group/create` — Create group {uid, name}
- `POST /api/chat/private/start` — Start/get private conv {uid, target_uid}
- `POST /api/chat/group/join` — Join group {uid, conv_id}

SocketIO events (client → server): connect_user, join_conv, leave_conv, send_msg, typing, stop_typing, mark_seen, who_is_online
SocketIO events (server → client): new_msg, msg_seen, user_typing, user_stop_typing, user_online, user_offline, online_list

Note: `run()` in keep_alive.py uses `socketio.run(app, allow_unsafe_werkzeug=True)` instead of `app.run()`.

## Migration Notes (Replit)
- Fixed `requirements.txt`: removed conflicting dummy `telegram` package, kept `python-telegram-bot`
- `config.py` now warns instead of raising on missing secrets (graceful startup)
- `database.py` now initializes Supabase only when credentials are present
- Flask app correctly binds to `0.0.0.0:5000` for Replit's proxy
