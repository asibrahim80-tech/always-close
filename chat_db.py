"""
chat_db.py — Direct psycopg2 access to the local Replit postgres for chat tables.
Keeps chat data separate from Supabase (used for user profiles/locations).
"""
import os
import logging
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

log = logging.getLogger(__name__)

_DB_URL = os.environ.get("DATABASE_URL", "")


@contextmanager
def _conn():
    """Context-manager that yields a psycopg2 connection (auto-commit, RealDictCursor)."""
    conn = psycopg2.connect(_DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_user_conversations(user_id: str) -> list[dict]:
    """Return all conversations the user participates in, ordered by latest message."""
    sql = """
        SELECT
            c.id              AS conversation_id,
            c.type,
            c.name,
            c.created_at,
            m.content         AS last_message,
            m.created_at      AS last_message_at,
            m.sender_id       AS last_sender_id,
            (SELECT COUNT(*) FROM messages
             WHERE conversation_id = c.id
               AND sender_id != %s
               AND status != 'seen')   AS unread_count
        FROM conversations c
        JOIN participants p ON p.conversation_id = c.id AND p.user_id = %s
        LEFT JOIN LATERAL (
            SELECT content, created_at, sender_id
            FROM messages
            WHERE conversation_id = c.id
            ORDER BY created_at DESC
            LIMIT 1
        ) m ON TRUE
        ORDER BY COALESCE(m.created_at, c.created_at) DESC
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(user_id), str(user_id)))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_unread_counts(user_id: str) -> list[dict]:
    """Return {conv_id, count} for conversations with unread messages."""
    sql = """
        SELECT conversation_id AS conv_id, COUNT(*) AS count
        FROM messages m
        JOIN participants p ON p.conversation_id = m.conversation_id AND p.user_id = %s
        WHERE m.sender_id != %s AND m.status != 'seen'
        GROUP BY m.conversation_id
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (str(user_id), str(user_id)))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def start_private_conversation(user_a: str, user_b: str) -> dict:
    """
    Return (or create) a private conversation between two users.
    Returns the conversation dict.
    """
    sql_find = """
        SELECT c.id AS conversation_id, c.type, c.name, c.created_at
        FROM conversations c
        JOIN participants p1 ON p1.conversation_id = c.id AND p1.user_id = %s
        JOIN participants p2 ON p2.conversation_id = c.id AND p2.user_id = %s
        WHERE c.type = 'private'
        LIMIT 1
    """
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_find, (str(user_a), str(user_b)))
            row = cur.fetchone()
            if row:
                return dict(row)
            # Create new private conversation
            cur.execute(
                "INSERT INTO conversations (type) VALUES ('private') RETURNING id, type, name, created_at",
                ()
            )
            conv = dict(cur.fetchone())
            cid = conv["id"]
            cur.execute(
                "INSERT INTO participants (conversation_id, user_id) VALUES (%s,%s),(%s,%s)",
                (cid, str(user_a), cid, str(user_b))
            )
            conv["conversation_id"] = cid
            return conv


def create_group_conversation(name: str, creator_id: str) -> dict:
    """Create a new group conversation and add the creator as first participant."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (type,name,created_by) VALUES ('group',%s,%s) RETURNING id,type,name,created_at",
                (name, str(creator_id))
            )
            conv = dict(cur.fetchone())
            cur.execute(
                "INSERT INTO participants (conversation_id,user_id) VALUES (%s,%s)",
                (conv["id"], str(creator_id))
            )
            conv["conversation_id"] = conv["id"]
            return conv


def add_participant(conv_id: str, user_id: str) -> bool:
    """Add a user to a group conversation (idempotent)."""
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO participants (conversation_id,user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (conv_id, str(user_id))
                )
        return True
    except Exception as e:
        log.warning(f"add_participant error: {e}")
        return False


def is_participant(conv_id: str, user_id: str) -> bool:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM participants WHERE conversation_id=%s AND user_id=%s",
                (conv_id, str(user_id))
            )
            return cur.fetchone() is not None


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGES
# ─────────────────────────────────────────────────────────────────────────────

def get_messages(conv_id: str, limit: int = 50, before: str | None = None) -> list[dict]:
    """Return messages for a conversation (newest first then reversed for display)."""
    if before:
        sql = """
            SELECT id, conversation_id, sender_id, content, status, created_at
            FROM messages
            WHERE conversation_id = %s AND created_at < %s
            ORDER BY created_at DESC LIMIT %s
        """
        params = (conv_id, before, limit)
    else:
        sql = """
            SELECT id, conversation_id, sender_id, content, status, created_at
            FROM messages
            WHERE conversation_id = %s
            ORDER BY created_at DESC LIMIT %s
        """
        params = (conv_id, limit)

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    msgs = [dict(r) for r in rows]
    msgs.reverse()  # chronological order for display
    # Serialize UUIDs and datetimes
    for m in msgs:
        m["id"]              = str(m["id"])
        m["conversation_id"] = str(m["conversation_id"])
        m["created_at"]      = m["created_at"].isoformat() if hasattr(m["created_at"], "isoformat") else str(m["created_at"])
    return msgs


def insert_message(conv_id: str, sender_id: str, content: str) -> dict | None:
    """Insert a new message and return it."""
    sql = """
        INSERT INTO messages (conversation_id, sender_id, content, status)
        VALUES (%s, %s, %s, 'sent')
        RETURNING id, conversation_id, sender_id, content, status, created_at
    """
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (conv_id, str(sender_id), content))
                row = dict(cur.fetchone())
        row["id"]              = str(row["id"])
        row["conversation_id"] = str(row["conversation_id"])
        row["created_at"]      = row["created_at"].isoformat()
        return row
    except Exception as e:
        log.error(f"insert_message error: {e}")
        return None


def mark_delivered(conv_id: str, user_id: str):
    """Mark sent messages (from others) in this conversation as delivered."""
    sql = """
        UPDATE messages SET status='delivered'
        WHERE conversation_id=%s AND sender_id!=%s AND status='sent'
    """
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (conv_id, str(user_id)))
    except Exception as e:
        log.warning(f"mark_delivered error: {e}")


def mark_seen(conv_id: str, user_id: str):
    """Mark all messages from others in this conversation as seen."""
    sql = """
        UPDATE messages SET status='seen'
        WHERE conversation_id=%s AND sender_id!=%s AND status IN ('sent','delivered')
    """
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (conv_id, str(user_id)))
    except Exception as e:
        log.warning(f"mark_seen error: {e}")


def get_conv_info(conv_id: str) -> dict | None:
    """Get basic conversation metadata."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, type, name, created_by, created_at FROM conversations WHERE id=%s",
                (conv_id,)
            )
            row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    return d


def serialize_convs(convs: list[dict]) -> list[dict]:
    """Serialize UUID/datetime fields in conversation rows."""
    out = []
    for c in convs:
        d = dict(c)
        d["conversation_id"] = str(d["conversation_id"])
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat() if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
        if d.get("last_message_at"):
            d["last_message_at"] = d["last_message_at"].isoformat() if hasattr(d["last_message_at"], "isoformat") else str(d["last_message_at"])
        d["unread_count"] = int(d.get("unread_count") or 0)
        out.append(d)
    return out
