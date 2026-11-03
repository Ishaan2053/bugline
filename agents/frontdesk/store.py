"""The front desk's memory: tickets, subscribers, drafts, requests, muted threads, rate guards.

One SQLite file (stdlib `sqlite3`) so the agent survives restarts without a database server.
The two rate guards live here because they must be checked before any model call, and they need
the same persisted state as the tickets.
"""

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    n               INTEGER PRIMARY KEY,
    ticket_id       TEXT NOT NULL UNIQUE,
    reporter_id     TEXT NOT NULL,
    reporter_name   TEXT NOT NULL,
    support_room_id TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    report_json     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    pr_url          TEXT,
    created_at      TEXT NOT NULL,
    closed_at       TEXT
);
CREATE TABLE IF NOT EXISTS subscribers (
    ticket_id TEXT NOT NULL REFERENCES tickets (ticket_id),
    user_id   TEXT NOT NULL,
    room_id   TEXT NOT NULL,
    PRIMARY KEY (ticket_id, user_id)
);
CREATE TABLE IF NOT EXISTS drafts (
    room_id      TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    report_json  TEXT NOT NULL,
    missing_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (room_id, user_id)
);
CREATE TABLE IF NOT EXISTS requests (
    id         INTEGER PRIMARY KEY,
    user_id    TEXT NOT NULL,
    room_id    TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS muted_threads (
    room_id   TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    PRIMARY KEY (room_id, thread_id)
);
CREATE TABLE IF NOT EXISTS reply_log (
    user_id TEXT NOT NULL,
    ts      REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    reporter_id: str
    reporter_name: str
    support_room_id: str
    title: str
    summary: str
    report: dict[str, Any]
    status: str
    pr_url: str | None
    created_at: str
    closed_at: str | None


@dataclass(frozen=True)
class Draft:
    """An incomplete bug report waiting for the user's next message."""

    report: dict[str, Any]
    missing: list[str]


class Subscriber(NamedTuple):
    user_id: str
    room_id: str


class Store:
    """All front-desk state behind one SQLite connection.

    Pass ":memory:" or a temporary path in tests. `clock` returns epoch seconds and is
    injectable so the cooldown can be tested without waiting.
    """

    def __init__(
        self, path: str | Path = config.DB_PATH, clock: Callable[[], float] = time.time
    ) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._clock = clock

    def close(self) -> None:
        self._db.close()

    def _iso_now(self) -> str:
        return datetime.fromtimestamp(self._clock(), UTC).isoformat(timespec="seconds")

    # --- tickets --------------------------------------------------------------------------------

    def open_ticket(
        self,
        reporter_id: str,
        reporter_name: str,
        support_room_id: str,
        title: str,
        summary: str,
        report: dict[str, Any],
    ) -> str:
        """Create the next ticket (BL-1, BL-2, ...), subscribe the reporter, return its id."""
        with self._db:
            (last,) = self._db.execute("SELECT COALESCE(MAX(n), 0) FROM tickets").fetchone()
            ticket_id = config.format_ticket_id(last + 1)
            self._db.execute(
                "INSERT INTO tickets (n, ticket_id, reporter_id, reporter_name, support_room_id,"
                " title, summary, report_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    last + 1,
                    ticket_id,
                    reporter_id,
                    reporter_name,
                    support_room_id,
                    title,
                    summary,
                    json.dumps(report),
                    self._iso_now(),
                ),
            )
            # The reporter is the first subscriber, so closing a ticket has one list to notify.
            self._db.execute(
                "INSERT INTO subscribers (ticket_id, user_id, room_id) VALUES (?, ?, ?)",
                (ticket_id, reporter_id, support_room_id),
            )
        return ticket_id

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        row = self._db.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return _ticket(row) if row else None

    def open_tickets(self) -> list[Ticket]:
        """All open tickets, oldest first. The duplicate check reads their id, title and summary."""
        rows = self._db.execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY n").fetchall()
        return [_ticket(row) for row in rows]

    def subscribe(self, ticket_id: str, user_id: str, room_id: str) -> None:
        """Add a user to a ticket's notify list. Subscribing twice is a no-op."""
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO subscribers (ticket_id, user_id, room_id) VALUES (?, ?, ?)",
                (ticket_id, user_id, room_id),
            )

    def close_ticket(self, ticket_id: str, pr_url: str) -> list[Subscriber]:
        """Mark a ticket fixed and return who to notify: the reporter, then each subscriber once.

        Returns an empty list if the ticket is unknown or already closed, so a repeated close
        message never notifies anyone twice.
        """
        with self._db:
            updated = self._db.execute(
                "UPDATE tickets SET status = 'closed', pr_url = ?, closed_at = ?"
                " WHERE ticket_id = ? AND status = 'open'",
                (pr_url, self._iso_now(), ticket_id),
            ).rowcount
        if not updated:
            return []
        rows = self._db.execute(
            "SELECT user_id, room_id FROM subscribers WHERE ticket_id = ? ORDER BY rowid",
            (ticket_id,),
        ).fetchall()
        return [Subscriber(row["user_id"], row["room_id"]) for row in rows]

    # --- drafts ---------------------------------------------------------------------------------

    def get_draft(self, room_id: str, user_id: str) -> Draft | None:
        row = self._db.execute(
            "SELECT report_json, missing_json FROM drafts WHERE room_id = ? AND user_id = ?",
            (room_id, user_id),
        ).fetchone()
        if not row:
            return None
        return Draft(json.loads(row["report_json"]), json.loads(row["missing_json"]))

    def save_draft(
        self, room_id: str, user_id: str, report: dict[str, Any], missing: list[str]
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO drafts (room_id, user_id, report_json, missing_json,"
                " updated_at) VALUES (?, ?, ?, ?, ?)",
                (room_id, user_id, json.dumps(report), json.dumps(missing), self._iso_now()),
            )

    def clear_draft(self, room_id: str, user_id: str) -> None:
        with self._db:
            self._db.execute(
                "DELETE FROM drafts WHERE room_id = ? AND user_id = ?", (room_id, user_id)
            )

    # --- requests and muted threads -------------------------------------------------------------

    def log_request(self, user_id: str, room_id: str, text: str) -> int:
        """Keep a feature request for later. Requests are not escalated during the hackathon."""
        with self._db:
            cursor = self._db.execute(
                "INSERT INTO requests (user_id, room_id, text, created_at) VALUES (?, ?, ?, ?)",
                (user_id, room_id, text, self._iso_now()),
            )
        return cursor.lastrowid or 0

    def mute(self, room_id: str, thread_id: str) -> None:
        """Stop engaging with an off-topic thread: no replies and no model calls."""
        with self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO muted_threads (room_id, thread_id) VALUES (?, ?)",
                (room_id, thread_id),
            )

    def is_muted(self, room_id: str, thread_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM muted_threads WHERE room_id = ? AND thread_id = ?",
            (room_id, thread_id),
        ).fetchone()
        return row is not None

    # --- rate guards (check both before any model call) -----------------------------------------

    def too_many_open_tickets(self, user_id: str) -> bool:
        """True when the user already reported MAX_OPEN_TICKETS tickets that are still open."""
        (count,) = self._db.execute(
            "SELECT COUNT(*) FROM tickets WHERE reporter_id = ? AND status = 'open'", (user_id,)
        ).fetchone()
        return count >= config.MAX_OPEN_TICKETS

    def allow_model_reply(self, user_id: str, now: float | None = None) -> bool:
        """Cooldown: at most REPLIES_PER_MINUTE model-backed replies per user per minute.

        Returns True and records the reply when the user is under the limit; False otherwise.
        """
        now = self._clock() if now is None else now
        window_start = now - config.REPLY_WINDOW_S
        with self._db:
            self._db.execute(
                "DELETE FROM reply_log WHERE user_id = ? AND ts <= ?", (user_id, window_start)
            )
            (recent,) = self._db.execute(
                "SELECT COUNT(*) FROM reply_log WHERE user_id = ?", (user_id,)
            ).fetchone()
            if recent >= config.REPLIES_PER_MINUTE:
                return False
            self._db.execute("INSERT INTO reply_log (user_id, ts) VALUES (?, ?)", (user_id, now))
        return True


def _ticket(row: sqlite3.Row) -> Ticket:
    return Ticket(
        ticket_id=row["ticket_id"],
        reporter_id=row["reporter_id"],
        reporter_name=row["reporter_name"],
        support_room_id=row["support_room_id"],
        title=row["title"],
        summary=row["summary"],
        report=json.loads(row["report_json"]),
        status=row["status"],
        pr_url=row["pr_url"],
        created_at=row["created_at"],
        closed_at=row["closed_at"],
    )
