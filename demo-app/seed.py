"""Load the demo group "Goa trip" into an empty database.

Runs on every container start and does nothing if a group already exists, so restarts keep data.
The group gets id 1 and the fixed share token below, so docs and demo scripts can rely on both.
The data matches the scenarios in CLAUDE.md section 2: Meera has not paid for anything yet, and
the dinner is split three ways.
"""

from app import db, money

SHARE_TOKEN = "goa-trip-share"
MEMBERS = ["Asha", "Ravi", "Meera"]
# (payer, amount, description, share counts by name; None means split equally)
EXPENSES = [
    ("Asha", 1000.0, "Beach shack dinner", None),
    ("Ravi", 2400.0, "Scooter rental", None),
    ("Asha", 4500.0, "Villa booking", None),
    ("Ravi", 1200.0, "Parasailing (Meera went twice)", {"Asha": 1, "Ravi": 1, "Meera": 2}),
]


def seed() -> None:
    conn = db.connect()
    if conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0]:
        print("Database already has data; not seeding.")
        return
    group = db.create_group(conn, "Goa trip", SHARE_TOKEN)
    ids = {name: db.add_member(conn, group["id"], name)["id"] for name in MEMBERS}
    for payer, amount, description, shares in EXPENSES:
        if shares is None:
            split = money.split_equal(amount, list(ids.values()))
        else:
            split = money.split_by_shares(amount, {ids[name]: n for name, n in shares.items()})
        db.add_expense(conn, group["id"], ids[payer], amount, description, split)
    conn.close()
    print(f"Seeded group {group['id']} 'Goa trip'. Share token: {SHARE_TOKEN}")


if __name__ == "__main__":
    seed()
