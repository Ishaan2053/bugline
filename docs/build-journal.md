# Build journal

One dated entry per session: what was done, what broke, what fixed it.

## 2026-11-04

- Repo bootstrapped: `CLAUDE.md`, `AGENTS.md`, MIT licence, `.gitignore`.
- Demo app built on `feat/demo-app-expense-splitter`: FastAPI + stdlib sqlite3, seed group
  "Goa trip" (share token `goa-trip-share`), 8 tests, Dockerfile and root `docker-compose.yml`.
- Broke: `starlette.testclient` warns that using `httpx` is deprecated. Fixed by pinning `httpx2`
  in the dev requirements instead.
- Fault 2 on the seeded data is one paisa, not one rupee: members owe 9099.99 of 9100.00 spent.
- Versions checked today and pinned: Python 3.14.7 (image `python:3.14.10-slim`), FastAPI 0.162.0,
  uvicorn 0.54.0, pytest 9.2.0, httpx 0.28.1 / httpx2 2.16.0, websockets 17.4, google-genai 2.34.0,
  ruff 0.17.3.
- Front desk store and Gemini calls merged: SQLite tickets, drafts, subscribers, both rate guards,
  backoff on 429, `calls.log`. 20 tests.
- Broke: `gemini-2.5-flash-lite` returns 404 "no longer available to new users". Fixed by moving
  the lite model to `gemini-3.5-flash-lite`, named once in `agents/frontdesk/config.py`.
- Read the Switch protocol docs and server source. Our plan was wrong in a few places: one
  WebSocket connection per room (the front desk needs two), `post_message` has no mentions,
  the agent cannot open itself to "anyone" (the owner does it in Console), and the fixer's
  PM-only rule is a custom access rule set in Console, not in the template. CLAUDE.md section 5
  now says this.
- Switch folder merged: room instructions, `intake-rules.md` (also the model's input for
  classification), `repro-checklist.md`, `fix-policy.md`, the three agent briefs,
  `bugline.template.yaml`, `scripts/setup_rooms.py` and the manual walkthrough
  `docs/switch-setup.md`. The template cannot create the Telegram room, the custom front desk or
  the fixer's PM-only rule, so those steps are manual and marked in the guide.
- Front desk loop merged in two PRs (client, then handlers and main loop), about 770 lines before
  tests. Two WebSocket connections, one per room. Messages are queued so a slow model call never
  delays a pong. With live Gemini on three messages it asked for missing fields on a vague
  report, escalated a complete one as BL-1 and declined an off-topic one. 43 tests.
- Changed the rate-limit reply to ask the user to resend: the agent does not retry by itself, so
  "trying again shortly" was not true.
- Fresh-clone test passed: `docker compose up --build -d` serves the app, `/share/goa-trip-share`
  returns the planted 500, both test suites pass. CI runs ruff and pytest for both projects on
  every PR and is required on `main`.
- Judge-facing README merged, with author placeholders for the GIF, video, screenshots, call
  counts and the Wispr scorecard.
- Not done yet, needs the Switch server: registering the front desk, both rooms, the managed
  reproducer and fixer, the refusal test and the full loop. Everything that rests on an unverified
  protocol detail is tagged "(unverified)" in `docs/switch-setup.md` and in the PR descriptions.
