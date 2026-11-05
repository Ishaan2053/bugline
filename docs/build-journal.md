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

## 2026-11-04 (evening): the six additions before the video

Built from the plan in `ADDITIONS.md`, one PR each, all squash-merged with CI green.

- PR #24: the Windows Proactor shutdown error is filtered in one place (`agents/common/loop.py`).
  The error arrives from a callback, so the filter matches the callback name in the message, not
  a transport. Coders default to `~/bugline-agents/<name>` off Windows.
- PR #25: `@frontdesk status` and `@frontdesk status BL-n` in the eng room. A `closed_by` column
  is added in place with `ALTER TABLE`, so the live database survives.
- PR #26: `scripts/doctor.py` checks server, bridges, rooms, connections, keys, roles, access
  rules, tools and clones; live run all PASS in under 7 s. `scripts/reset_demo.py` restarts the
  demo at `BL-1` and refuses while an agent is live. It recreates only the demo-app container,
  because `down -v` would also delete the front desk's Docker volume.
- PR #27: bootstrap takes `--support-bridge` and `--eng-bridge`. Whether a room can be created
  comes from the connection's `channel_creation_*` fields, not a list of app types. The bundled
  Mattermost is up; the Mattermost-only path is dry-run only, so it stays "untested by the author".
- PR #28: the fixer hands its PR to `@reproducer`; only `Verified BL-n: <PR url>` from the
  reproducer or the room owner closes a ticket. Broke on paper: a message's sender is a
  participant id, not the agent id, so the check uses `sender_role == "owner"` and the
  reproducer's name. Fixer branches get a time stamp so a reset run cannot collide with #18.
- PR #29: `bugline.toml` names the project: repo, paths, test command, ticket prefix, report
  fields, rooms and agents. With the shipped file every posted message is unchanged; a `QA`
  config with four fields dry-runs cleanly.
- Not done live (the session only read): a real bootstrap, `reset_demo.py` for real, the verify
  loop, the two close negatives, and the Mattermost loop.

## 2026-11-05: four front desk features and the first live verify loop

The machine had restarted overnight, so Console, the server and Docker were down; Console would
not start from the agent's shell and was started by hand. `doctor.py` then showed only the three
agents missing.

- PR #31: `@frontdesk ask BL-n: <question>` in Slack reaches the reporter's Telegram thread; their
  next message comes back to the Slack thread. No model call.
- PR #32: `still broken` from someone waiting on a closed ticket reopens it and hands it back to
  `@reproducer`. The "fixed" message now says how.
- PR #33: `@frontdesk requests` lists logged feature requests with names (a column added in place).
- PR #35: the refusal said "Only @reproducer ...". Switch read that as addressing the role and
  the reproducer started a Claude Code run on the refusal. It saw nothing was asked and said so,
  but it cost a run. Replies no longer mention a role; a test checks every fixed text.
- PR #36: replies in the reporter's language. First live run: the Hinglish replies were right,
  but Steps/Expected/Actual reached Slack in Hinglish, because "keep quoted text as written" in
  the prompt beat "write it in English". Split into two rules; the same draft then came back in
  English.
- Skipped: the ticket board as a Switch room document. The server source says room documents
  show in the Switch room UI and to agents, never in Slack, and native Console has no room UI.

Live on Nov 5, as Admin (reporter and PM) and `sam`: `BL-3` (fault 1) → reproduced → `ask`
round trip → `requests` → `status` → PM approval → fixer PR #34 → reproducer `Verified` →
closed and "fixed" in the support room, 70 s from approval to close → `still broken` reopened
it → reproduced again on `main` → `sam`'s `Verified` refused → the owner closed it by hand.
`BL-4` came in Hinglish. The front desk made 2 Gemini calls for `BL-3`'s whole run; the
Hinglish report took 2 classify and 2 translate calls. PR #34 was closed unmerged (it removes
fault 1, like #18).

## 2026-11-05 (evening): a second copy on Mattermost, from a fresh clone

To prove part B and the Mattermost variant, a second copy of Bugline was set up from a fresh
clone with its own `bugline.toml` (`bltest-support` / `bltest-eng`, agents `bltest-*`, tickets
`BT-n`, both rooms on Console's bundled Mattermost), next to the demo on the same server.

- The dry run caught a real bug first: bootstrap found the kit's library documents by file name
  across the whole server, so the second copy would have rewritten the demo's `intake-rules.md`,
  `repro-checklist.md` and `fix-policy.md` with its own names. PR #38: the kit is now
  `<project>-kit`, and its documents are looked up inside it (Switch lets global documents share
  a name). The demo's own dry run still says `exists` for all of it.
- Bootstrap then made everything from nothing in one run; a second run changed nothing; `doctor.py`
  passed every line.
- The complete report got no reply: Gemini answered 503 "high demand", and only 429 was retried.
  PR #39 waits out 503 the same way and, if that fails, sends the rate-limited reply.
- The reproducer said it "wasn't allowed to write `scratch/bt_1.py`", as it did once on `BL-4`.
  A probe with its exact command line wrote there fine; it also showed that `Write(...)` path
  rules are ignored and `Edit(...)` rules are what allow the Write tool. PR #40 logs each refused
  tool call, so the next refusal names its path. The second run wrote its script with no refusal.
- Full loop on Mattermost: vague report → asked for the group id → `BT-1` reproduced → `sam`'s
  `@fixer` refused by Switch → owner's approval → fixer PR #41 → reproducer `Verified` (on `main`,
  then on the PR) → closed and "fixed" in `bltest-support`, under 2 minutes after approval. Two
  Gemini calls for the loop. PR #41 was closed unmerged.
- The lite model copied the share token as `goa-rip-share` into the ticket. The reproducer
  noticed, tried both tokens, and reproduced on the real one.
- On this machine `py -3.14` finds nothing, because Python 3.14 came from uv; the venvs were made
  with that interpreter's full path.
