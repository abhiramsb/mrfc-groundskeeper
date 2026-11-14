"""SQLite storage. Uses the stdlib sqlite3 behind a lock; queries are tiny."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    message_id  INTEGER,
    creator_id  INTEGER NOT NULL,
    title       TEXT NOT NULL,
    formation   TEXT NOT NULL,
    start_ts    INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | closed | cancelled
    reminded    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rsvps (
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,                  -- in | sub | out
    slot        TEXT,                           -- slot key when status = 'in'
    avatar_url  TEXT,
    PRIMARY KEY (session_id, user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_player_per_slot
    ON rsvps(session_id, slot) WHERE status = 'in';
CREATE TABLE IF NOT EXISTS user_tz (
    user_id INTEGER PRIMARY KEY,
    tz      TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.Lock()
        with self._tx() as c:
            c.executescript(SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(rsvps)")}
            if "avatar_url" not in cols:  # migrate DBs created before avatars
                c.execute("ALTER TABLE rsvps ADD COLUMN avatar_url TEXT")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- sessions -------------------------------------------------------
    def create_session(self, guild_id, channel_id, creator_id, title, formation, start_ts) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO sessions(guild_id, channel_id, creator_id, title, formation, start_ts)"
                " VALUES (?,?,?,?,?,?)",
                (guild_id, channel_id, creator_id, title, formation, start_ts),
            )
            return cur.lastrowid

    def set_message(self, session_id: int, message_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE sessions SET message_id=? WHERE id=?", (message_id, session_id))

    def get_session(self, session_id: int):
        with self._tx() as c:
            return c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()

    def set_status(self, session_id: int, status: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE sessions SET status=? WHERE id=?", (status, session_id))

    def mark_reminded(self, session_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE sessions SET reminded=1 WHERE id=?", (session_id,))

    def open_sessions(self, guild_id: int | None = None):
        q = "SELECT * FROM sessions WHERE status='open'"
        args: tuple = ()
        if guild_id is not None:
            q += " AND guild_id=?"
            args = (guild_id,)
        with self._tx() as c:
            return c.execute(q + " ORDER BY start_ts", args).fetchall()

    # ---- rsvps ----------------------------------------------------------
    def claim_slot(self, session_id: int, user_id: int, name: str, slot: str, avatar_url: str | None = None) -> str | None:
        """Returns None on success, or the name of the player holding the slot."""
        with self._tx() as c:
            row = c.execute(
                "SELECT user_id, name FROM rsvps WHERE session_id=? AND slot=? AND status='in'",
                (session_id, slot),
            ).fetchone()
            if row and row["user_id"] != user_id:
                return row["name"]
            c.execute(
                "INSERT INTO rsvps(session_id,user_id,name,status,slot,avatar_url) VALUES (?,?,?,'in',?,?)"
                " ON CONFLICT(session_id,user_id) DO UPDATE SET name=excluded.name,"
                " status='in', slot=excluded.slot, avatar_url=excluded.avatar_url",
                (session_id, user_id, name, slot, avatar_url),
            )
            return None

    def set_status_for_user(self, session_id: int, user_id: int, name: str, status: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO rsvps(session_id,user_id,name,status,slot) VALUES (?,?,?,?,NULL)"
                " ON CONFLICT(session_id,user_id) DO UPDATE SET name=excluded.name,"
                " status=excluded.status, slot=NULL",
                (session_id, user_id, name, status),
            )

    def clear_user(self, session_id: int, user_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM rsvps WHERE session_id=? AND user_id=?", (session_id, user_id))

    def remove_slot(self, session_id: int, slot: str) -> bool:
        with self._tx() as c:
            cur = c.execute(
                "DELETE FROM rsvps WHERE session_id=? AND slot=? AND status='in'", (session_id, slot)
            )
            return cur.rowcount > 0

    def rsvps(self, session_id: int):
        with self._tx() as c:
            return c.execute(
                "SELECT * FROM rsvps WHERE session_id=? ORDER BY rowid", (session_id,)
            ).fetchall()

    # ---- user tz --------------------------------------------------------
    def get_tz(self, user_id: int) -> str | None:
        with self._tx() as c:
            row = c.execute("SELECT tz FROM user_tz WHERE user_id=?", (user_id,)).fetchone()
            return row["tz"] if row else None

    def set_tz(self, user_id: int, tz: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO user_tz(user_id,tz) VALUES (?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET tz=excluded.tz",
                (user_id, tz),
            )
