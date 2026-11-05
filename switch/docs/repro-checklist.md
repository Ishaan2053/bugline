# Reproduction checklist

How the reproducer turns a ticket into a verdict. A ticket arrives in `$eng_room` in the shape
given in [intake-rules.md](intake-rules.md#handing-a-bug-to-bugline-eng). The verdict goes in that
ticket's thread.

## 1. Environment

Work in your own clone; each run starts in it. Never in someone else's checkout.

First time:

```powershell
git clone $repo_url
cd $clone_dir\$app_dir
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

Every ticket, before anything else, from the clone's root:

```powershell
git checkout $default_branch
git pull --ff-only
cd $app_dir
pip install -r requirements-dev.txt
```

Use the venv. Docker (`docker compose up --build` from the repo root, app on port 8000) is the
second choice; it is slower to start and its first build needs the PM's go-ahead.

## 2. The smallest failing script

- Scratch scripts go in `$scratch_dir/`, named after the ticket: `$scratch_module/${ticket_slug}_<n>.py`. That
  folder is in `.gitignore`. Never commit a scratch script, never put one in `tests/`.
- Use a fresh database in a temp folder and the seed data, so the run does not depend on what is in
  `bugline.db`. The seed is group `1` "Goa trip", members Asha, Ravi and Meera, share token
  `goa-trip-share` (see `$app_dir/seed.py`).
- Call the endpoint the report names through FastAPI's `TestClient`. It raises server errors, so a
  500 shows its full traceback.
- One script, one request or one short sequence of requests. Print the status code and the body.

Starting point (change the request to match the ticket):

```python
"""$ticket_prefix-<n>: <title>. Scratch repro, not committed."""

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

Run it from `$app_dir/`:

```powershell
python -m $scratch_module.${ticket_slug}_<n>
```

If the report names a group other than `1`, build that state in the script with the same API calls
the user made (`POST /groups`, `POST /groups/{id}/members`, `POST /groups/{id}/expenses`). The
endpoints are listed in `$user_guide`.

## 3. Read the result

- Compare what you got with the ticket's `Expected` and `Actual` lines.
- For wrong numbers, show the exact numbers and the sum that does not add up. Do the arithmetic in
  the reply; do not describe it.
- Find the line the traceback ends in, or the function that computes the wrong number. Open it and
  read it before you name a cause.

## 4. What to post

Reply in the ticket's thread, under 10 lines, in this order:

```
Ran: python -m $scratch_module.${ticket_slug}_<n>   (GET /share/goa-trip-share on a fresh seeded db)
Output: <the last lines of the traceback, or the status code and the relevant numbers>
Verdict: reproduced
Likely cause: <file>, <function>: <one sentence>
```

- The verdict line is exactly `Verdict: reproduced` or `Verdict: not reproduced`. Nothing else
  on that line.
- `Likely cause` names a file and a function you read, for example
  `$app_dir/app/main.py, share()`. If you are not sure, say what you checked and stop there.
- For `not reproduced`, list what you tried (requests, groups, amounts) so the PM can ask the
  reporter for the difference. Do not offer a cause.

## 5. Verify a fix

After the fixer opens a PR, it asks you in the ticket's thread:
`@reproducer please verify $ticket_prefix-<n> on PR <url> (branch <name>)`. Check the PR, not the fixer's word
for it. `<N>` is the number at the end of the PR URL.

```powershell
cd $clone_dir
git checkout $default_branch
git fetch origin +pull/<N>/head:verify-${ticket_slug}-<n>
git checkout verify-${ticket_slug}-<n>
cd $app_dir
python -m $scratch_module.${ticket_slug}_<n>
$test_command
cd ..
git checkout $default_branch
```

- The scratch script is the one you wrote when you reproduced the ticket. If it is missing, write
  it again from the ticket (section 2) before you check out the PR.
- Always end on `$default_branch`, even when a step fails.
- The `+` in the fetch replaces an old `verify-${ticket_slug}-<n>` from an earlier run.

Your reply's first line is the verdict, in exactly one of these two forms. The program sends it to
the front desk, and the front desk reads it:

```
@frontdesk Verified $ticket_prefix-1: $repo_web/pull/12
@frontdesk Not verified $ticket_prefix-1: <one line: what still fails>
```

- `Verified` only when the script no longer shows the bug **and** every test passes. Then the
  front desk closes the ticket and tells the reporter.
- Anything else is `Not verified`, with one line saying what failed. The ticket stays open and the
  PM reads the thread.
- Under the verdict, add the script's output and the last line of `$test_command`. Keep it under 10
  lines.

## 6. Never

- Never guess an output you did not run. If a step fails, post the failure.
- Never fix the bug, edit files outside `$scratch_dir/`, push, or open a PR. That is the
  fixer's job, after the PM approves it.
- Never touch `bugline.db` in the repo or `seed.py`.
