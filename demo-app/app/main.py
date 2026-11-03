"""HTTP routes for the expense splitter.

Each route checks its input, uses db.py for storage and money.py for the arithmetic, and returns
plain JSON. Run it with `uvicorn app.main:app` from demo-app/.
"""

import secrets
import sqlite3
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, PositiveInt

from app import db, money

app = FastAPI(title="Bugline demo: expense splitter")


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


class NameIn(BaseModel):
    name: str = Field(min_length=1)


class ExpenseIn(BaseModel):
    payer_id: int
    amount: float = Field(gt=0)
    description: str = Field(min_length=1)
    split: Literal["equal", "shares"] = "equal"
    shares: dict[int, PositiveInt] | None = None  # member id -> share count, for split="shares"


def require_group(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row:
    group = db.get_group(conn, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="group not found")
    return group


def member_balances(conn: sqlite3.Connection, group_id: int) -> list[dict]:
    return [
        {
            "member_id": row["id"],
            "name": row["name"],
            "paid": round(row["paid"], 2),
            "owes": round(row["owes"], 2),
            "net": round(row["paid"] - row["owes"], 2),
        }
        for row in db.member_totals(conn, group_id)
    ]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/groups", status_code=201)
def create_group(body: NameIn, conn: Conn) -> dict:
    return db.create_group(conn, body.name, secrets.token_urlsafe(8))


@app.post("/groups/{group_id}/members", status_code=201)
def add_member(group_id: int, body: NameIn, conn: Conn) -> dict:
    require_group(conn, group_id)
    return db.add_member(conn, group_id, body.name)


@app.post("/groups/{group_id}/expenses", status_code=201)
def add_expense(group_id: int, body: ExpenseIn, conn: Conn) -> dict:
    require_group(conn, group_id)
    members = db.member_ids(conn, group_id)
    if body.payer_id not in members:
        raise HTTPException(status_code=400, detail="payer is not a member of this group")
    if body.split == "equal":
        split = money.split_equal(body.amount, members)
    elif body.shares and set(body.shares) <= set(members):
        split = money.split_by_shares(body.amount, body.shares)
    else:
        raise HTTPException(
            status_code=400, detail="shares must map members of this group to share counts"
        )
    return db.add_expense(conn, group_id, body.payer_id, body.amount, body.description, split)


@app.get("/groups/{group_id}/balances")
def balances(group_id: int, conn: Conn) -> dict:
    require_group(conn, group_id)
    members = member_balances(conn, group_id)
    total_spent = round(sum(member["paid"] for member in members), 2)
    return {"group_id": group_id, "total_spent": total_spent, "members": members}


@app.get("/groups/{group_id}/settle")
def settle(group_id: int, conn: Conn) -> dict:
    require_group(conn, group_id)
    members = member_balances(conn, group_id)
    names = {member["member_id"]: member["name"] for member in members}
    net = {member["member_id"]: member["net"] for member in members}
    transfers = [
        {"from": names[debtor], "to": names[creditor], "amount": amount}
        for debtor, creditor, amount in money.settle_up(net)
    ]
    return {"group_id": group_id, "transfers": transfers}


@app.get("/share/{share_token}")
def share(share_token: str, conn: Conn) -> dict:
    """Read-only summary for anyone holding the group's share link."""
    group = db.get_group_by_token(conn, share_token)
    if group is None:
        raise HTTPException(status_code=404, detail="share link not found")
    members = [
        {
            "name": row["name"],
            "total_paid": round(row["paid"], 2),
            "expenses_paid": row["expenses_paid"],
            "average_expense": round(row["paid"] / row["expenses_paid"], 2),
        }
        for row in db.member_totals(conn, group["id"])
    ]
    return {"group": group["name"], "members": members}
