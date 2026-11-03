# Expense splitter (Bugline demo app)

A small FastAPI + SQLite app for splitting trip expenses in a group. It is the codebase the Bugline
agents reproduce and fix bugs in. See the [repo CLAUDE.md](../CLAUDE.md#demo-app-expense-splitter-demo-app)
for how it fits into the project.

## Run it

With Docker, from the repo root:

```powershell
docker compose up --build
```

Without Docker, from `demo-app/` (PowerShell):

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python seed.py
uvicorn app.main:app --port 8000
```

Bash:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python seed.py
uvicorn app.main:app --port 8000
```

The database file is `bugline.db` in the working directory; set `BUGLINE_DB` to use another path.
`seed.py` loads the group "Goa trip" (id `1`, members Asha, Ravi and Meera, four expenses) into an
empty database and does nothing if data already exists. Its share token is `goa-trip-share`.

Tests and lint, from `demo-app/`:

```powershell
pytest -q
ruff format --check .
ruff check .
```

## Endpoints

Amounts are rupees.

| Method and path | Body | Returns |
| --- | --- | --- |
| `GET /health` | | `{"status": "ok"}` |
| `POST /groups` | `{"name": "Goa trip"}` | the group with its `id` and `share_token` |
| `POST /groups/{id}/members` | `{"name": "Asha"}` | the member with its `id` |
| `POST /groups/{id}/expenses` | `{"payer_id": 1, "amount": 1200, "description": "Dinner"}` | the expense and what each member owes for it (`split`) |
| `GET /groups/{id}/balances` | | per member: `paid`, `owes`, `net` |
| `GET /groups/{id}/settle` | | transfers: `from`, `to`, `amount` |
| `GET /share/{token}` | | read-only summary: per member total paid, number of expenses paid, average expense |

An expense is split equally between all members by default. To split it unevenly, send
`"split": "shares"` and a map of member id to share count, for example
`"shares": {"1": 1, "2": 1, "3": 2}` (member 3 owes half, members 1 and 2 a quarter each).

## Using the app / FAQ

**Why does it say I owe money I already paid?**
Balances follow the payer recorded on each expense. If an expense was entered with someone else as
the payer, the app thinks they paid and you owe your part of it. This is not a bug in the app;
the expense needs correcting. There is no edit or delete endpoint, so re-add the expense with the
right payer and the same amount, and put the whole of it on the person who was wrongly recorded
as payer: `"split": "shares", "shares": {"<their member id>": 1}`. That cancels the mistake and
every balance comes out right. `total_spent` will count the amount twice; if that matters, start
a fresh group.

**What does "net" mean on the balances page?**
`paid` is everything you paid for the group. `owes` is your part of every expense. `net` is
`paid - owes`: positive means the group owes you, negative means you owe the group.

**How does settle-up work?**
`GET /groups/{id}/settle` turns the balances into a short list of payments. The person who owes
the most pays the person who is owed the most, then the next pair, until everyone is square. Make
those payments outside the app; the app does not record them.

**How do share links work?**
Every group gets a share token when it is created. `GET /share/{token}` shows a read-only summary
(who paid how much, how many expenses each, and their average expense) to anyone with the link,
without a login. The seeded group's link is `/share/goa-trip-share`.

## Seeded faults (maintainers' note)

This app has faults planted on purpose for the Bugline demo. Do not fix them outside the fixer's
demo run. The full list, with what a user sees and the expected path through the agents, is the
seeded-faults table in [CLAUDE.md](../CLAUDE.md#demo-app-expense-splitter-demo-app). Faults 1 and 2
live in this app; there are deliberately no tests for them yet.

What faults 1 and 2 look like on the seeded "Goa trip" group:

- **Fault 1:** `GET /share/goa-trip-share` returns HTTP 500 because Meera has paid for nothing
  (`ZeroDivisionError` in the server log).
- **Fault 2:** the beach shack dinner (₹1000 split three ways) is stored as ₹333.33 each, so
  ₹0.01 disappears. `GET /groups/1/balances` shows `total_spent` 9100.00, but the members' `owes`
  add up to 9099.99 (2933.33 + 2933.33 + 3233.33) and the `net` values add up to +0.01.
  `GET /groups/1/settle` has Meera pay Asha 2566.67 and Ravi 666.66, a total of 3233.33, while
  Asha and Ravi are owed 2566.67 + 666.67 = 3233.34. Ravi is left owed ₹0.01 with no transfer.
