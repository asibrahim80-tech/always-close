"""
Real-time chat event handlers (Flask-SocketIO).
Uses chat_db (local postgres) for persistence.

Protocol:
  Client → Server : connect_user, join_conv, leave_conv, send_msg,
                    typing, stop_typing, mark_seen, who_is_online
  Server → Client : new_msg, msg_seen, user_typing, user_stop_typing,
                    user_online, user_offline, online_list, error
"""
import logging
from flask import request
from flask_socketio import emit, join_room, leave_room
from socketio_init import socketio

log = logging.getLogger(__name__)

# ── In-memory state ───────────────────────────────────────────────────────────
online_users:  dict[str, str]        = {}   # { user_id : sid }
typing_in_conv: dict[str, dict]      = {}   # { conv_id : { user_id: username } }
sid_meta:      dict[str, dict]       = {}   # { sid : { user_id, username } }


# ─────────────────────────────────────────────────────────────────────────────
# CONNECT / DISCONNECT
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    log.debug(f"[socket] connect sid={request.sid}")


@socketio.on("disconnect")
def on_disconnect(reason=None):
    sid  = request.sid
    meta = sid_meta.pop(sid, None)
    if not meta:
        return
    uid = meta.get("user_id")
    if uid:
        online_users.pop(uid, None)
        for conv_typers in typing_in_conv.values():
            conv_typers.pop(uid, None)
        socketio.emit("user_offline", {"user_id": uid}, to=None)
    log.debug(f"[socket] disconnect uid={uid} reason={reason}")


# ─────────────────────────────────────────────────────────────────────────────
# ANNOUNCE ONLINE
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("connect_user")
def on_connect_user(data):
    uid      = str(data.get("user_id", ""))
    username = str(data.get("username", "?"))
    if not uid:
        return
    sid_meta[request.sid]  = {"user_id": uid, "username": username}
    online_users[uid]       = request.sid
    socketio.emit("user_online", {"user_id": uid}, to=None)
    log.debug(f"[socket] online uid={uid}")


# ─────────────────────────────────────────────────────────────────────────────
# JOIN / LEAVE CONVERSATION ROOM
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("join_conv")
def on_join_conv(data):
    conv_id = str(data.get("conv_id", ""))
    user_id = str(data.get("user_id", ""))
    if not conv_id or not user_id:
        return
    join_room(conv_id)
    try:
        import chat_db
        chat_db.mark_delivered(conv_id, user_id)
    except Exception as e:
        log.warning(f"mark_delivered error: {e}")


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
    temp_id   = data.get("temp_id")

    if not conv_id or not sender_id or not content:
        return

    try:
        import chat_db
        msg = chat_db.insert_message(conv_id, sender_id, content)
    except Exception as e:
        log.error(f"insert_message error: {e}")
        emit("error", {"msg": "DB write failed"})
        return

    if not msg:
        emit("error", {"msg": "DB write failed"})
        return

    payload = {
        "message_id": msg["id"],
        "conv_id":    conv_id,
        "sender_id":  sender_id,
        "content":    content,
        "created_at": msg["created_at"],
        "status":     "sent",
        "temp_id":    temp_id,
    }
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
    try:
        import chat_db
        chat_db.mark_seen(conv_id, user_id)
    except Exception as e:
        log.warning(f"mark_seen error: {e}")
    socketio.emit("msg_seen", {"conv_id": conv_id, "seen_by": user_id}, room=conv_id)


# ─────────────────────────────────────────────────────────────────────────────
# ONLINE STATUS QUERY
# ─────────────────────────────────────────────────────────────────────────────
@socketio.on("who_is_online")
def on_who_is_online(data):
    emit("online_list", {"online": list(online_users.keys())})
