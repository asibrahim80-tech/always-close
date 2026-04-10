# Always Close — Telegram Matchmaking Bot

## Overview
A Telegram bot that lets users register profiles, share their location, find nearby people, and like/match with them. It also features an interactive map via a Flask web interface.

## Project Structure
- `main.py` — Entry point; sets up the Telegram bot and registers all handlers
- `handlers.py` — Core business logic: profile creation, location, likes, matching
- `database.py` — Supabase client initialization
- `config.py` — Loads environment variables (BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY)
- `lang.py` — Multi-language support (English + Arabic)
- `keep_alive.py` — Flask web server (runs in background thread on port 5000)
  - Serves `index.html` and `map.html` templates
  - `/api/nearby/<telegram_id>` — JSON API for the interactive map
- `helpers.py` — Haversine distance calculation utilities
- `templates/` — HTML templates for the web UI (index.html, map.html)

## Required Secrets
Set these in the Replit Secrets tab:
- `BOT_TOKEN` — Telegram bot token from @BotFather
- `SUPABASE_URL` — Your Supabase project URL
- `SUPABASE_KEY` — Your Supabase anon or service role key

## Running
The app runs via `python main.py`. This starts:
1. A Flask web server on port 5000 (background thread) — for the web map UI
2. The Telegram bot using long-polling

## Key Dependencies
- `python-telegram-bot>=20.0` — Telegram bot framework
- `flask` — Web server for the map interface
- `supabase` — Database client
- `geohash2` — Geospatial indexing for nearby user search
- `httpx` — Async HTTP (resolving Telegram photo URLs)

## Database (Supabase)
Tables used:
- `users_v1` — User profiles (telegram_id, username, age, gender, bio, photo_url, is_active, is_visible)
- `user_locations_v1` — Latest lat/lng + geohash per user
- `likes_v1` — Like records between users
- `matches_v1` — Mutual match records
