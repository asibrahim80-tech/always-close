"""
Real-time chat event handlers (Flask-SocketIO).
All socket events for the messaging system live here.
Protocol:
  Client → Server : join_conv, send_msg, typing, stop_typing, mark_seen, connect_user
  Server → Client : new_msg, msg_seen, user_typing, user_stop_typing, user_online, user_offline
"""
import logging
from datetime import datetime, timezone

from flask import request
from flask_socketio import emit, join_room, leave_room

from socketio_init import socketio

log = logging.getLogger(__name__)

# ── In-memory state ───────────────────────────────────────────────────────────
# { user_id (str) : socket_id }
online_users: dict[str, str] = {}

# { conv_id (str) : { user_id (str) : username (str) } }
typing_in_conv: dict[str, dict[str, str]] = {}

# { socket_id : { user_id, username } }
sid_meta: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# CONNECT / DISCONNECT
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    log.debug(f"[socket] connect sid={request.sid}")


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    meta = sid_meta.pop(sid, None)
    if not meta:
        return
    uid = meta.get("user_id")
    if uid:
        online_users.pop(uid, None)
        # Remove from all typing states
        for conv_typers in typing_in_conv.values():
            conv_typers.pop(uid, None)
        # Broadcast offline status to all rooms this user was in
        socketio.emit("user_offline", {"user_id": uid}, broadcast=True)
    log.debug(f"[socket] disconnect uid={uid}")


# ─────────────────────────────────────────────────────────────────────────────
# ANNOUNCE ONLINE
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("connect_user")
def on_connect_user(data):
    """Client sends this immediately after socket connection with their user_id."""
    uid      = str(data.get("user_id", ""))
    username = str(data.get("username", "?"))
    if not uid:
        return
    sid_meta[request.sid] = {"user_id": uid, "username": username}
    online_users[uid]     = request.sid
    socketio.emit("user_online", {"user_id": uid}, broadcast=True)
    log.debug(f"[socket] online uid={uid}")


# ─────────────────────────────────────────────────────────────────────────────
# JOIN / LEAVE CONVERSATION ROOM
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("join_conv")
def on_join_conv(data):
    conv_id  = str(data.get("conv_id", ""))
    user_id  = str(data.get("user_id", ""))
    if not conv_id or not user_id:
        return
    join_room(conv_id)
    # Mark all undelivered messages as delivered for this user
    _mark_delivered(conv_id, user_id)
    log.debug(f"[socket] join room={conv_id} uid={user_id}")


@socketio.on("leave_conv")
def on_leave_conv(data):
    conv_id = str(data.get("conv_id", ""))
    if conv_id:
        leave_room(conv_id)


# ─────────────────────────────────────────────────────────────────────────────
# SEND MESSAGE
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("send_msg")
def on_send_msg(data):
    conv_id   = str(data.get("conv_id", ""))
    sender_id = str(data.get("sender_id", ""))
    content   = str(data.get("content", "")).strip()
    temp_id   = data.get("temp_id")          # client-side temp ID for dedup

    if not conv_id or not sender_id or not content:
        return

    # Persist to DB
    msg = _insert_message(conv_id, sender_id, content)
    if not msg:
        emit("error", {"msg": "DB write failed"})
        return

    payload = {
        "message_id":      msg["id"],
        "conv_id":         conv_id,
        "sender_id":       sender_id,
        "content":         content,
        "created_at":      msg["created_at"],
        "status":          "sent",
        "temp_id":         temp_id,
    }
    # Broadcast to everyone in the room (including sender for confirmation)
    socketio.emit("new_msg", payload, room=conv_id)
    log.debug(f"[socket] msg room={conv_id} sender={sender_id}")


# ─────────────────────────────────────────────────────────────────────────────
# TYPING INDICATORS
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("typing")
def on_typing(data):
    conv_id  = str(data.get("conv_id", ""))
    user_id  = str(data.get("user_id", ""))
    username = str(data.get("username", "?"))
    if not conv_id or not user_id:
        return
    typing_in_conv.setdefault(conv_id, {})[user_id] = username
    emit("user_typing", {"conv_id": conv_id, "user_id": user_id, "username": username},
         room=conv_id, include_self=False)


@socketio.on("stop_typing")
def on_stop_typing(data):
    conv_id = str(data.get("conv_id", ""))
    user_id = str(data.get("user_id", ""))
    if conv_id and user_id:
        typing_in_conv.get(conv_id, {}).pop(user_id, None)
    emit("user_stop_typing", {"conv_id": conv_id, "user_id": user_id},
         room=conv_id, include_self=False)


# ─────────────────────────────────────────────────────────────────────────────
# MARK SEEN
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("mark_seen")
def on_mark_seen(data):
    conv_id = str(data.get("conv_id", ""))
    user_id = str(data.get("user_id", ""))
    if not conv_id or not user_id:
        return
    _mark_seen(conv_id, user_id)
    socketio.emit("msg_seen", {"conv_id": conv_id, "seen_by": user_id}, room=conv_id)


# ─────────────────────────────────────────────────────────────────────────────
# ONLINE STATUS QUERY
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("who_is_online")
def on_who_is_online(data):
    """Returns list of currently online user IDs."""
    emit("online_list", {"online": list(online_users.keys())})


# ─────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _insert_message(conv_id: str, sender_id: str, content: str) -> dict | None:
    try:
        from database import supabase
        res = supabase.table("messages").insert({
            "conversation_id": conv_id,
            "sender_id":       sender_id,
            "content":         content,
            "status":          "sent",
        }).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        log.error(f"_insert_message error: {e}")
        return None


def _mark_delivered(conv_id: str, user_id: str):
    """Mark all 'sent' messages in this conv (not from this user) as 'delivered'."""
    try:
        from database import supabase
        supabase.table("messages") \
            .update({"status": "delivered"}) \
            .eq("conversation_id", conv_id) \
            .eq("status", "sent") \
            .neq("sender_id", user_id) \
            .execute()
    except Exception as e:
        log.warning(f"_mark_delivered error: {e}")


def _mark_seen(conv_id: str, user_id: str):
    """Mark all messages in this conv (not from this user) as 'seen'."""
    try:
        from database import supabase
        supabase.table("messages") \
            .update({"status": "seen"}) \
            .eq("conversation_id", conv_id) \
            .neq("sender_id", user_id) \
            .in_("status", ["sent", "delivered"]) \
            .execute()
    except Exception as e:
        log.warning(f"_mark_seen error: {e}")
