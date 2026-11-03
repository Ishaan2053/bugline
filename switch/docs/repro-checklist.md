# Reproduction checklist

How the reproducer turns a ticket into a verdict. A ticket arrives in `bugline-eng` in the shape
given in [intake-rules.md](intake-rules.md#handing-a-bug-to-bugline-eng). The verdict goes in that
ticket's thread.

## 1. Environment

Work in your own working directory (`C:\bugline-agents\bugline-repro`). Never in someone else's
checkout.

First time:

```powershell
git clone https://github.com/Ishaan2053/bugline.git
cd bugline\demo-app
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Every ticket, before anything else:

```powershell
cd bugline
git checkout main
git pull --ff-only
cd demo-app
pip install -r requirements-dev.txt
```

Use the venv. Docker (`docker compose up --build` from the repo root, app on port 8000) is the
second choice; it is slower to start and its first build needs the PM's go-ahead.

## 2. The smallest failing script

- Scratch scripts go in `demo-app/scratch/`, named after the ticket: `scratch/bl_<n>.py`. That
  folder is in `.gitignore`. Never commit a scratch script, never put one in `tests/`.
- Use a fresh database in a temp folder and the seed data, so the run does not depend on what is in
  `bugline.db`. The seed is group `1` "Goa trip", members Asha, Ravi and Meera, share token
  `goa-trip-share` (see `demo-app/seed.py`).
- Call the endpoint the report names through FastAPI's `TestClient`. It raises server errors, so a
  500 shows its full traceback.
- One script, one request or one short sequence of requests. Print the status code and the body.

Starting point (change the request to match the ticket):

```python
"""BL-<n>: <title>. Scratch repro, not committed."""

import os
import tempfile

os.environ["BUGLINE_DB"] = os.path.join(tempfile.mkdtemp(), "repro.db")

from fastapi.testclient import TestClient  # noqa: E402

import seed  # noqa: E402
from app.main import app  # noqa: E402

seed.seed()
with TestClient(app) as client:
    response = client.get("/groups/1/balances")
    print(response.status_code, response.text)
```

Run it from `demo-app/`:

```powershell
python -m scratch.bl_<n>
```

If the report names a group other than `1`, build that state in the script with the same API calls
the user made (`POST /groups`, `POST /groups/{id}/members`, `POST /groups/{id}/expenses`). The
endpoints are listed in `demo-app/README.md`.

## 3. Read the result

- Compare what you got with the ticket's `Expected` and `Actual` lines.
- For wrong numbers, show the exact numbers and the sum that does not add up. Do the arithmetic in
  the reply; do not describe it.
- Find the line the traceback ends in, or the function that computes the wrong number. Open it and
  read it before you name a cause.

## 4. What to post

Reply in the ticket's thread, under 10 lines, in this order:

```
Ran: python -m scratch.bl_<n>   (GET /share/goa-trip-share on a fresh seeded db)
Output: <the last lines of the traceback, or the status code and the relevant numbers>
Verdict: reproduced
Likely cause: <file>, <function>: <one sentence>
```

- The verdict line is exactly `Verdict: reproduced` or `Verdict: not reproduced`. Nothing else
  on that line.
- `Likely cause` names a file and a function you read, for example
  `demo-app/app/main.py, share()`. If you are not sure, say what you checked and stop there.
- For `not reproduced`, list what you tried (requests, groups, amounts) so the PM can ask the
  reporter for the difference. Do not offer a cause.

## 5. Never

- Never guess an output you did not run. If a step fails, post the failure.
- Never fix the bug, edit files outside `demo-app/scratch/`, push, or open a PR. That is the
  fixer's job, after the PM approves it.
- Never touch `bugline.db` in the repo or `seed.py`.
