import sqlite3
import os
import datetime

# ─────────────────────────────────────────────
#  Path: ip_messenger.db  (same folder as script)
# ─────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ip_messenger.db")


def _get_connection():
    """Return a new SQLite connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # lets us access columns by name
    return conn


# ══════════════════════════════════════════════
#  TABLE SETUP
# ══════════════════════════════════════════════
def init_db():
    """
    Create the messages table if it does not exist yet.
    Call this once when the application starts.

    Schema
    ──────
    id          – auto-increment primary key
    timestamp   – ISO-8601 string  e.g. "2025-12-31 19:34:00"
    direction   – "sent" | "received"
    sender      – username of the person who sent the message
    recipient   – username of the person who received the message  (or "All")
    message     – the actual message text
    ip          – IP address of the remote party
    has_attach  – 1 if files were attached, 0 otherwise
    starred     – 1 if the message is starred/bookmarked, 0 otherwise
    """
    conn = _get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                direction   TEXT    NOT NULL CHECK(direction IN ('sent', 'received')),
                sender      TEXT    NOT NULL DEFAULT '',
                recipient   TEXT    NOT NULL DEFAULT '',
                message     TEXT    NOT NULL DEFAULT '',
                ip          TEXT    NOT NULL DEFAULT '',
                has_attach  INTEGER NOT NULL DEFAULT 0,
                starred     INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
        print(f"[DB] Database ready → {DB_PATH}")
    finally:
        conn.close()


# ══════════════════════════════════════════════
#  WRITE
# ══════════════════════════════════════════════
def save_message(
    direction: str,          # "sent" | "received"
    sender: str,
    recipient: str,
    message: str,
    ip: str = "",
    has_attach: bool = False,
    timestamp: str = None,   # if None, current local time is used
) -> int:
    """
    Insert one message row and return its new row id.

    Example
    ───────
    save_message("sent", "Admin", "Bob", "Hello!", ip="192.168.1.5")
    save_message("received", "Bob", "Admin", "Hi back!", ip="192.168.1.5")
    """
    if timestamp is None:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO messages
                (timestamp, direction, sender, recipient, message, ip, has_attach, starred)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (timestamp, direction, sender, recipient, message, ip, int(has_attach)),
        )
        conn.commit()
        row_id = cursor.lastrowid
        print(f"[DB] Saved message id={row_id}  [{direction}] {sender} → {recipient}")
        return row_id
    finally:
        conn.close()


# ══════════════════════════════════════════════
#  READ / QUERY
# ══════════════════════════════════════════════
def get_all_messages(limit: int = 500) -> list[dict]:
    """
    Return up to `limit` messages ordered by timestamp ascending.
    Each item is a plain dict with keys matching the table columns.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY timestamp ASC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_messages_by_user(username: str, limit: int = 200) -> list[dict]:
    """
    Return messages where sender OR recipient matches `username`.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE sender = ? OR recipient = ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (username, username, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_messages_by_ip(ip: str, limit: int = 200) -> list[dict]:
    """Return messages involving a specific IP address."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE ip = ? ORDER BY timestamp ASC LIMIT ?",
            (ip, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_messages_by_date_range(start: str, end: str, limit: int = 500) -> list[dict]:
    """
    Return messages between two ISO date strings (inclusive).

    start / end format: "YYYY-MM-DD"   e.g. "2025-12-01"
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (start + " 00:00:00", end + " 23:59:59", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_messages(keyword: str, limit: int = 200) -> list[dict]:
    """Full-text search inside the message column (case-insensitive)."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE message LIKE ? ORDER BY timestamp ASC LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_starred_messages(limit: int = 200) -> list[dict]:
    """Return only starred/bookmarked messages."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE starred = 1 ORDER BY timestamp ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ══════════════════════════════════════════════
#  UPDATE
# ══════════════════════════════════════════════
def toggle_star(message_id: int) -> bool:
    """
    Toggle the starred flag for a message.
    Returns the NEW starred state (True = starred).
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT starred FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if row is None:
            return False
        new_state = 0 if row["starred"] else 1
        conn.execute(
            "UPDATE messages SET starred = ? WHERE id = ?", (new_state, message_id)
        )
        conn.commit()
        return bool(new_state)
    finally:
        conn.close()


# ══════════════════════════════════════════════
#  DELETE
# ══════════════════════════════════════════════
def delete_message(message_id: int) -> bool:
    """Delete a single message by its id. Returns True if a row was deleted."""
    conn = _get_connection()
    try:
        cursor = conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_all_messages() -> int:
    """Delete every message. Returns the number of rows deleted."""
    conn = _get_connection()
    try:
        cursor = conn.execute("DELETE FROM messages")
        conn.commit()
        print(f"[DB] Cleared all messages ({cursor.rowcount} rows removed)")
        return cursor.rowcount
    finally:
        conn.close()


# ══════════════════════════════════════════════
#  HELPER – format a db row like the LogViewer
# ══════════════════════════════════════════════
def format_log_header(row: dict) -> str:
    """
    Convert a message dict to a LogViewer-style header string.

    Output example:
        2025/12/31 19:34 (Wed) → Admin
    """
    try:
        dt = datetime.datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt = datetime.datetime.now()

    weekday  = dt.strftime("%a")                   # Mon, Tue … Sun
    date_str = dt.strftime(f"%Y/%m/%d {dt.hour:02d}:{dt.minute:02d} ({weekday})")

    arrow    = "→" if row["direction"] == "sent" else "←"
    name     = row["recipient"] if row["direction"] == "sent" else row["sender"]

    return f"{date_str}  {arrow} {name}"


# ══════════════════════════════════════════════
#  Run directly → just initialise the database
# ══════════════════════════════════════════════
if __name__ == "__main__":
    init_db()
    print(f"Database initialised at: {DB_PATH}")
    print(f"Total messages stored  : {len(get_all_messages(limit=9999))}")
