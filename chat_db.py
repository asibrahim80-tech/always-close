"""
chat_db.py — Supabase client access for chat tables.
All chat data: conversations, participants, messages lives in Supabase.
"""
import logging

log = logging.getLogger(__name__)


def _sb():
    from database import supabase
    return supabase


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_user_conversations(user_id: str) -> list[dict]:
    """
    Return all conversations the user participates in,
    enriched with last message and unread count, ordered by latest activity.
    """
    sb = _sb()
    uid = str(user_id)

    # Step 1: Get all conversation IDs this user belongs to
    p_res = sb.table("participants") \
              .select("conversation_id") \
              .eq("user_id", uid) \
              .execute()

    if not p_res.data:
        return []

    conv_ids = [r["conversation_id"] for r in p_res.data]

    # Step 2: Get conversation metadata
    c_res = sb.table("conversations") \
              .select("id,type,name,created_by,created_at") \
              .in_("id", conv_ids) \
              .execute()

    convs = {c["id"]: c for c in (c_res.data or [])}

    # Step 3: Get last message per conversation
    last_msgs = {}
    for cid in conv_ids:
        m = sb.table("messages") \
              .select("content,created_at,sender_id") \
              .eq("conversation_id", cid) \
              .order("created_at", desc=True) \
              .limit(1) \
              .execute()
        if m.data:
            last_msgs[cid] = m.data[0]

    # Step 4: Count unread per conversation
    unread_counts = {}
    for cid in conv_ids:
        u = sb.table("messages") \
              .select("id", count="exact") \
              .eq("conversation_id", cid) \
              .neq("sender_id", uid) \
              .neq("status", "seen") \
              .execute()
        unread_counts[cid] = u.count or 0

    # Step 5: Assemble result
    result = []
    for cid in conv_ids:
        c = convs.get(cid)
        if not c:
            continue
        lm = last_msgs.get(cid, {})
        result.append({
            "conversation_id": cid,
            "type":            c.get("type"),
            "name":            c.get("name"),
            "created_at":      c.get("created_at"),
            "last_message":    lm.get("content"),
            "last_message_at": lm.get("created_at"),
            "last_sender_id":  lm.get("sender_id"),
            "unread_count":    unread_counts.get(cid, 0),
        })

    # Sort by latest activity
    result.sort(
        key=lambda x: x.get("last_message_at") or x.get("created_at") or "",
        reverse=True
    )
    return result


def get_unread_counts(user_id: str) -> list[dict]:
    """Return [{conv_id, count}] for conversations with unread messages."""
    sb  = _sb()
    uid = str(user_id)

    p_res = sb.table("participants") \
              .select("conversation_id") \
              .eq("user_id", uid) \
              .execute()
    if not p_res.data:
        return []

    result = []
    for row in p_res.data:
        cid = row["conversation_id"]
        u   = sb.table("messages") \
                .select("id", count="exact") \
                .eq("conversation_id", cid) \
                .neq("sender_id", uid) \
                .neq("status", "seen") \
                .execute()
        if u.count:
            result.append({"conv_id": cid, "count": u.count})
    return result


def start_private_conversation(user_a: str, user_b: str) -> dict:
    """Return (or create) a private conversation between two users."""
    sb = _sb()
    ua, ub = str(user_a), str(user_b)

    # Find all convs user_a is in
    a_res = sb.table("participants").select("conversation_id").eq("user_id", ua).execute()
    a_ids = {r["conversation_id"] for r in (a_res.data or [])}

    # Find all convs user_b is in
    b_res = sb.table("participants").select("conversation_id").eq("user_id", ub).execute()
    b_ids = {r["conversation_id"] for r in (b_res.data or [])}

    # Intersection = shared conversations
    shared = a_ids & b_ids
    if shared:
        # Pick the first private conversation
        for cid in shared:
            c = sb.table("conversations").select("id,type,name,created_at") \
                  .eq("id", cid).eq("type", "private").execute()
            if c.data:
                d = c.data[0]
                d["conversation_id"] = d["id"]
                return d

    # Create new private conversation
    c_res = sb.table("conversations") \
              .insert({"type": "private", "created_by": ua}) \
              .execute()
    conv  = c_res.data[0]
    cid   = conv["id"]

    # Add both participants
    sb.table("participants").insert([
        {"conversation_id": cid, "user_id": ua},
        {"conversation_id": cid, "user_id": ub},
    ]).execute()

    conv["conversation_id"] = cid
    return conv


def create_group_conversation(name: str, creator_id: str) -> dict:
    """Create a new group conversation and add the creator."""
    sb  = _sb()
    uid = str(creator_id)

    c_res = sb.table("conversations") \
              .insert({"type": "group", "name": name, "created_by": uid}) \
              .execute()
    conv  = c_res.data[0]
    cid   = conv["id"]

    sb.table("participants") \
      .insert({"conversation_id": cid, "user_id": uid}) \
      .execute()

    conv["conversation_id"] = cid
    return conv


def add_participant(conv_id: str, user_id: str) -> bool:
    """Add a user to a group conversation (idempotent)."""
    try:
        _sb().table("participants") \
             .upsert({"conversation_id": conv_id, "user_id": str(user_id)},
                     on_conflict="conversation_id,user_id") \
             .execute()
        return True
    except Exception as e:
        log.warning(f"add_participant error: {e}")
        return False


def is_participant(conv_id: str, user_id: str) -> bool:
    r = _sb().table("participants") \
             .select("id") \
             .eq("conversation_id", conv_id) \
             .eq("user_id", str(user_id)) \
             .limit(1) \
             .execute()
    return bool(r.data)


def get_conv_info(conv_id: str) -> dict | None:
    r = _sb().table("conversations") \
             .select("id,type,name,created_by,created_at") \
             .eq("id", conv_id) \
             .limit(1) \
             .execute()
    if not r.data:
        return None
    d = r.data[0]
    d["conversation_id"] = d["id"]
    return d


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

def get_messages(conv_id: str, limit: int = 50, before: str | None = None) -> list[dict]:
    """Return messages for a conversation in chronological order."""
    sb = _sb()
    q  = sb.table("messages") \
           .select("id,conversation_id,sender_id,content,status,created_at") \
           .eq("conversation_id", conv_id) \
           .order("created_at", desc=True) \
           .limit(limit)

    if before:
        q = q.lt("created_at", before)

    res  = q.execute()
    msgs = list(reversed(res.data or []))   # chronological order
    return msgs


def insert_message(conv_id: str, sender_id: str, content: str) -> dict | None:
    """Insert a new message and return it."""
    try:
        res = _sb().table("messages") \
                   .insert({
                       "conversation_id": conv_id,
                       "sender_id":       str(sender_id),
                       "content":         content,
                       "status":          "sent",
                   }) \
                   .execute()
        return res.data[0] if res.data else None
    except Exception as e:
        log.error(f"insert_message error: {e}")
        return None


def mark_delivered(conv_id: str, user_id: str):
    """Mark sent messages (from others) in this conversation as delivered."""
    try:
        _sb().table("messages") \
             .update({"status": "delivered"}) \
             .eq("conversation_id", conv_id) \
             .eq("status", "sent") \
             .neq("sender_id", str(user_id)) \
             .execute()
    except Exception as e:
        log.warning(f"mark_delivered error: {e}")


def mark_seen(conv_id: str, user_id: str):
    """Mark all messages from others in this conversation as seen."""
    try:
        _sb().table("messages") \
             .update({"status": "seen"}) \
             .eq("conversation_id", conv_id) \
             .neq("sender_id", str(user_id)) \
             .in_("status", ["sent", "delivered"]) \
             .execute()
    except Exception as e:
        log.warning(f"mark_seen error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SERIALIZATION HELPER
# ─────────────────────────────────────────────────────────────────────────────

def serialize_convs(convs: list[dict]) -> list[dict]:
    """Ensure all fields are JSON-serializable (Supabase already returns strings)."""
    result = []
    for c in convs:
        d = dict(c)
        d["unread_count"] = int(d.get("unread_count") or 0)
        result.append(d)
    return result
