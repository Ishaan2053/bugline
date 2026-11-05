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

## 2026-11-05 (night): an outside read, seven fixes, one more live loop

Three fresh reviewers read the repo: two for bugs, one as a judge would. Each finding below was
checked against the code or a live probe before anything changed.

- PR #43, the coders:
  - Path rules are now absolute under each clone. A probe with the real command line showed
    `cd demo-app` followed by a write to `demo-app/scratch/` denied, which explains the
    "not allowed to write" lines on `BL-4` and `BT-1`. The same `cd` had switched off the
    fixer's `seed.py` deny rule; after the fix that edit is refused.
  - `--setting-sources local`. A probe showed the repo's own CLAUDE.md, our build rules, in
    every coder run.
  - The checklist no longer tells the fixer to work in the reproducer's folder.
- PR #44, the front desk:
  - Closing a ticket drops its unanswered `ask` questions; before, they swallowed `still broken`.
  - A non-bug message, or 30 minutes, drops an unfinished draft.
  - Any routing error gets a reply.
  - A rate-limited duplicate check keeps the complete report.
- Live loop on fault 2 (`BL-5`):
  - My report had the wrong numbers, and the reproducer answered `not reproduced`. That was
    right: the transfers do add up.
  - Pointed at `/groups/1/balances` by the PM, it reproduced 9099.99 of 9100.00.
  - Fixer PR #45, `Verified`, closed, "fixed" in Telegram: 78 s from approval. PR #45 was
    closed unmerged.
  - `calls.log` shows two 503s on the classify call, waited out by #39 with no reply lost.
  - The reproducer wrote `scratch/bl_5.py`, and neither coder logged a refused tool call.
- README:
  - The workflow now comes before setup.
  - The faults table moved out of CLAUDE.md, and the test counts and Nov 5 numbers are current.
  - Part B has a fork step and a line for non-Windows setups.
  - The Mattermost variant and the Switch-docs lessons moved to `docs/switch-setup.md`, and
    "Run it on your own repo" moved to `docs/own-repo.md`.

## 2026-11-06

Feature-freeze day. A review asked which Switch features the agents use at run time. They called
four ops (`post_message`, `send_targeted_message`, `get_room_detail`, `assume_role`) out of about
55. The room links and the `bugline-kit` documents were set up by bootstrap but read by nothing:
the front desk took the eng room from `.env` and the rules from the repo.

- PR #47: the front desk sent a message's posts inside one `try`. A failed `Closed BL-n` reply in
  eng would have skipped every "fixed" message. Each post now goes out on its own.
- PR #48: the front desk finds `bugline-eng` by asking Switch where the support room's
  "escalates to" link points (`list_linked_rooms`). No link, no start. `doctor.py` checks it.
- PR #49: the front desk reads `intake-rules.md` from the kit before each support message, and
  the coders rebuild their brief from the kit before each run (`list_references`, then
  `load_internal_documents`). The repo copy is the fallback. `doctor.py` checks that the kit
  matches `switch/docs/`.
- Switch Console lists only its own `switch-buddy-admin`. The three Bugline agents are on the
  server (`GET /gateway/agents`), as custom agents Console does not show.
- Rehearsal on Telegram and Slack after `reset_demo.py`, all on the new code: question answered,
  vague report asked for four fields, off-topic declined, duplicate matched to `BL-1`, fault 1
  reproduced in 37 s, sam refused by Switch, and 95 s from the PM's approval to "BL-1 is fixed"
  for both reporters. Every brief came from Switch, and no tool call was refused.

## 2026-11-06 (later)

- 00:39: Switch's own Postgres crashed (`PANIC: could not write to log file`, Windows error 1450)
  and restarted. The agents had just been started after `reset_demo.py`, with cursor 0, and
  reconnected with `start_from=0`, which the server reads as "every event from the first". All
  three got their whole history. The front desk answered two old Telegram messages and escalated
  an old report; the fixer was handed three old approvals and ran none, only because it crashed
  on the server's 500s first. Stopped by hand.
- PR #52: no `start_from` while the cursor is 0; the coder survives a dropped post.
- PR #53: a connection hands on no message older than 30 minutes and none it already handed on.
- PRs #54 to #56, the rest of the Nov 5 review: a reopen phrase counts only in a message's first
  four words; a muted thread still takes an `ask` answer and a reopen; `doctor.py` checks that
  Claude Code is signed in; after an unfinished run the coder's clone goes back to `main`.
- PRs #57 and #58: one eng room, many support rooms. The front desk serves every room
  `bugline-eng` links to with "supports", on any chat app; `bootstrap.py --add-support mattermost`
  makes one. One ticket can collect reporters from Telegram and Mattermost, each told in their own
  app.
- PR #59: `approvers` in `bugline.toml` go into the fixer's access rule. A rule's `users` hold
  Switch's ids for chat-app people (`ExternalUser`), not Slack member ids, so bootstrap looks them
  up through the connection's users list.
- Not yet run live: the server was stopped after the crash.
