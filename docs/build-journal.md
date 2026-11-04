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

## 2026-11-04 (afternoon): the live run

- Switch Console 0.40.1 on Windows runs the server natively (switch-core 0.31.0). Ports come from
  `ports.json`; the API was 50073. There is no Gateway web UI in native mode, so the registration
  key, access rules and the template run went through the Gateway API, signed in as Console's
  local admin.
- Broke: Console cannot run managed coding agents on Windows ("SDK sessions require a POSIX SSH
  execution host"); every provider said "Not supported here". Fixed with Route B: `agents/coder`,
  one custom protocol agent that runs Claude Code headless, started as `bugline-repro` and as
  `bugline-fixer` (PR #16). The shared Switch client moved to `agents/common` (PR #13).
- Broke: the server refuses the template's `agents:` block ("Unknown top-level key(s): agents").
  The room was made from the template without it. The committed template now has no such block.
- Rooms up: `bugline-support` on Telegram, `bugline-eng` on Slack, linked both ways, instructions
  and aliases set, roles held. Setup script fixed to read `list_rooms` as the server returns it
  (PR #14).
- Broke: the reproducer's first run on `BL-1` could not run one shell command; in `dontAsk` mode
  every part of a chained command must be allowed. Fixed by allowing `Bash` and keeping deny lists
  per role (PR #17). The retry reproduced `BL-1` in 26 s.
- Broke: `@repoducer` (typo) reached nobody. Slack's free plan has no agent user groups, so there is
  no autocomplete; names must be typed exactly.
- Full loop on fault 1: vague report, front desk asked for steps and group, `BL-1` in Slack,
  reproducer verdict, PM approval, fixer PR #18 in 55 s, "BL-1 is fixed" back in Telegram. 2 Gemini
  calls, 3 Claude Code runs, 17 minutes end to end including the permission fix.
- Quiet paths all passed: question answered from the user guide, request logged, off-topic muted
  after one reply, `BL-2` reproduced (9099.99 of 9100.0), a second user's duplicate matched to
  `BL-2`, the burst guard, a false report "not reproduced", and the refusal: Switch told `sam` he
  is not permitted to address the fixer, and the fixer never saw the message. `BL-2` closed with
  PR #19 and both reporters notified, 2 min 25 s from report. 13 Gemini calls for the whole run.
- Broke: the front desk replied under the message that addressed it instead of the thread root.
  Fixed in PR #20.
- PRs #18 and #19 stay open: they remove the seeded faults.
- `scripts/bootstrap.py` replaces `setup_rooms.py`: one idempotent run for everything after the
  chat-app connections, written from the API calls above. Run against the live setup it found
  everything and created `bugline-kit` (three library documents from `switch/docs/` plus the
  `bugline-repo` reference, attached to both rooms); a second run printed only "exists".
- Not tested live: the 5-open-tickets limit, the front desk in Docker against the native server,
  and bootstrap on a fresh server.
