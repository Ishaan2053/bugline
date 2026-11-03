"""SQLite storage for groups, members and expenses.

Plain stdlib sqlite3 and hand-written SQL: the app is small enough that an ORM would hide more
than it saves. The database path comes from BUGLINE_DB so tests and Docker can point it elsewhere.
"""

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    share_token TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    payer_id INTEGER NOT NULL REFERENCES members(id),
    amount REAL NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expense_shares (
    expense_id INTEGER NOT NULL REFERENCES expenses(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    amount REAL NOT NULL,
    PRIMARY KEY (expense_id, member_id)
);
"""


def connect() -> sqlite3.Connection:
    """Open the database named by BUGLINE_DB (default bugline.db) and make sure tables exist."""
    conn = sqlite3.connect(os.environ.get("BUGLINE_DB", "bugline.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def get_group(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()


def get_group_by_token(conn: sqlite3.Connection, share_token: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM groups WHERE share_token = ?", (share_token,)).fetchone()


def create_group(conn: sqlite3.Connection, name: str, share_token: str) -> dict:
    with conn:
        cur = conn.execute(
            "INSERT INTO groups (name, share_token) VALUES (?, ?)", (name, share_token)
        )
    return {"id": cur.lastrowid, "name": name, "share_token": share_token}


def add_member(conn: sqlite3.Connection, group_id: int, name: str) -> dict:
    with conn:
        cur = conn.execute("INSERT INTO members (group_id, name) VALUES (?, ?)", (group_id, name))
    return {"id": cur.lastrowid, "group_id": group_id, "name": name}


def member_ids(conn: sqlite3.Connection, group_id: int) -> list[int]:
    rows = conn.execute("SELECT id FROM members WHERE group_id = ? ORDER BY id", (group_id,))
    return [row["id"] for row in rows]


def add_expense(
    conn: sqlite3.Connection,
    group_id: int,
    payer_id: int,
    amount: float,
    description: str,
    split: dict[int, float],
) -> dict:
    """Store an expense and what each member owes for it, in one transaction."""
    with conn:
        cur = conn.execute(
            "INSERT INTO expenses (group_id, payer_id, amount, description) VALUES (?, ?, ?, ?)",
            (group_id, payer_id, amount, description),
        )
        conn.executemany(
            "INSERT INTO expense_shares (expense_id, member_id, amount) VALUES (?, ?, ?)",
            [(cur.lastrowid, member_id, owed) for member_id, owed in split.items()],
        )
    return {
        "id": cur.lastrowid,
        "group_id": group_id,
        "payer_id": payer_id,
        "amount": amount,
        "description": description,
        "split": split,
    }


def member_totals(conn: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    """Per member: how many expenses they paid, how much they paid, and how much they owe."""
    return conn.execute(
        """
        SELECT m.id, m.name,
            (SELECT COUNT(*) FROM expenses e WHERE e.payer_id = m.id) AS expenses_paid,
            (SELECT COALESCE(SUM(e.amount), 0.0) FROM expenses e WHERE e.payer_id = m.id) AS paid,
            (SELECT COALESCE(SUM(s.amount), 0.0) FROM expense_shares s WHERE s.member_id = m.id)
                AS owes
        FROM members m
        WHERE m.group_id = ?
        ORDER BY m.id
        """,
        (group_id,),
    ).fetchall()
