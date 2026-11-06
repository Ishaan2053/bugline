# Bugline — project context for coding agents

This file is read by Claude Code (CLAUDE.md) and by OpenCode (through AGENTS.md, which points here).
It is the single source of truth for the repo. The human-facing build plan with the day-by-day
checklist lives in a Claude Doc; everything an agent needs from it is copied below.

## 1. What we are building and why

**Bugline** is our entry for the Flip the Switch Hackathon (WeMakeDevs x DevTools Academy x Switch),
Track 01 "Best Business Workflow" ($2,000), stacked with Best Blog and #HowISwitch posts.

One-line pitch: *Users report bugs in the chat they already use; the team fixes them in the chat they
already use; Switch carries the work across, keeps a human in charge, and closes the loop back to the
reporter.*

Hard constraints from the hackathon:

- Hacking window: **Nov 4, 12:01 AM IST → Nov 7, 11:59 PM IST (2026)**. We submit by **9 PM IST Nov 7**.
- Switch must be central; the README must show how. The Switch setup and workflow must be built
  during the window (tooling/setup on Nov 3 is fine).
- Judges check whether a stranger can clone the repo and reproduce the project.
- Low-effort or "unreviewed AI output" is not judged. Every line in this repo must be something the
  author can explain. Keep code small and readable over clever.
- Everything here is original and standalone. **Nothing from any other project or employer codebase
  may be copied in.** Do not reference, import, or reproduce code from outside this repo.

Judging criteria (assume equal weight):

| Criterion | What it asks | How Bugline answers it |
| --- | --- | --- |
| Use of Switch | Would it stop working without Switch? | Cross-app rooms, room links, shared + exclusive roles, access rules as the approval gate, agent-to-agent handoff |
| Technical execution | Does it run; is it reproducible from the repo? | `docker compose up`, room template YAML, custom protocol agent, step-by-step README |
| Creativity and impact | Fresh idea that solves a real team's problem | End user → engineering → back to the user; not an incident-rollback clone |
| Presentation | Do video + README make Switch's role obvious? | README headed by the criteria; video built around three Switch-only moments |

The three moments we never cut: the report crossing two chat apps, a non-PM being **refused** by
`@fixer`, and the "fixed, here's the PR" message landing back with the reporter on Telegram.

## 2. Architecture

Two rooms on two chat apps, linked in Switch; three agents in three roles; one human gate.

```
Telegram · bugline-support                 Slack · bugline-eng
┌──────────────────────┐                   ┌──────────────────────────────────────┐
│  End user            │                   │  @reproducer ──repro──▶ PM (human)   │
│    │ report          │   bug report      │  OpenCode/Claude Code    │ "@fixer go"│
│    ▼                 │ ───────────────▶  │  shared role             ▼           │
│  @frontdesk            │   (room link      │                        @fixer        │
│  custom Gemini agent │    "escalates to")│  ◀───── PR link + result  exclusive  │
│    │ resolved        │                   │                          PM only     │
│    ▼ End user        │                   └──────────────────────────────────────┘
└──────────────────────┘
```

### Rooms

| Room | App | Members | Purpose |
| --- | --- | --- | --- |
| `bugline-support` | Telegram group | end users, `@frontdesk` | Users report in plain language; frontdesk answers or escalates |
| `bugline-eng` | Slack channel (personal workspace) | PM (owner), `@frontdesk`, `@reproducer`, `@fixer` | Decide, reproduce, fix |

Links: support → eng labelled `escalates to`; eng → support labelled `supports`. A link tells agents
the other room exists; it does not grant access. `!follow-ups off` in both rooms so agents act only
when named.

### Roles, agents, access rules

| Role | Type | Agent name | Runtime | Who may instruct | Job |
| --- | --- | --- | --- | --- | --- |
| `frontdesk` | shared | `bugline-frontdesk` | Custom Python agent over the Switch protocol, Gemini | `anyone` | Classify each report as bug / question / request; ask for missing fields; answer questions from the repo reference; hand complete bugs to `#eng` as a structured report with a ticket id (`BL-n`); close a ticket only on a verified fix and post the resolution back to the reporter |
| `reproducer` | shared | `bugline-repro` | Custom protocol agent in `agents/coder` running Claude Code headless (Console cannot run coding agents on Windows) | frontdesk + PM + fixer (owner and owner's agents) | Clone the referenced repo, write the smallest failing script, run it, post exact output + verdict (reproduced / not) + likely cause. **Never guess.** When the fixer asks, check out the PR, rerun the script and the tests, and send `Verified BL-n: <PR url>` or `Not verified BL-n: <why>` to the front desk. The only agent whose `Verified` closes a ticket. |
| `fixer` | **exclusive** | `bugline-fixer` | The same `agents/coder` program with `CODER_ROLE=fixer` | **PM only, in `bugline-eng` only** | Fix one handler, add a regression test, run tests, open a PR on a branch with a time stamp, then hand it to `@reproducer` with `please verify BL-n on PR <url> (branch <name>)`. Never closes a ticket. Never touch migrations or data. |

### Shared material (room documents, in `switch/docs/`)

- Room instructions: purpose, reply in-thread, replies under 10 lines, announce slow steps, say
  "cannot reproduce" rather than guess.
- Reference: this GitHub repo (agents read it with their own access).
- `intake-rules.md` — bug vs question vs request; a complete report has steps, expected, actual, group id.
- `repro-checklist.md` — environment, where scripts go, what to post.
- `fix-policy.md` — scope limits, regression test required, PR title format `BL-n: <summary>`.
- Package `bugline-kit` bundling the three documents + the reference.

### Demo app: expense splitter (`demo-app/`)

FastAPI + SQLite. Endpoints: `POST /groups`, `POST /groups/{id}/members`,
`POST /groups/{id}/expenses` (payer, amount, split equally or by shares), `GET /groups/{id}/balances`,
`GET /groups/{id}/settle`, `GET /share/{token}`. Seed: one group "Goa trip", 3 members, 4 expenses.

Seeded faults (planted on purpose; do not fix them unless the task explicitly says so):

| # | Fault | User sees | Expected path |
| --- | --- | --- | --- |
| 1 | `GET /share/{token}` divides by a member's expense count → `ZeroDivisionError` for a member with none | "Share link gives an error" | frontdesk → reproducer → PM approves → fixer PR → frontdesk closes loop |
| 2 | Settlement rounds each share with `round(x, 2)` and drops the remainder on 3-way splits | "Settle-up is a paisa short of what we spent" | reproducer shows exact numbers |
| 3 | Not a bug: expense entered with the wrong payer | "It says I owe money I already paid" | frontdesk answers from the docs, never escalates |
| 4 | Report with no steps / no group id | vague complaint | frontdesk asks for exactly the missing fields |
| 5 | Duplicate: a second user reports fault 1 while `BL-1` is open | "Share link broken for me too" | frontdesk matches it to `BL-1`, tells the user it is already tracked, subscribes them; nothing reaches `#eng`; when `BL-1` closes, every subscriber is notified |
| 6 | Off-topic: spam or a question about another product | anything unrelated | frontdesk replies once ("not something I can help with here") and drops it |

### Front-desk filtering rules (only complete, new bugs cross the room link)

- Classification schema has four kinds: `bug`, `question`, `request`, `off-topic`.
- `question` → answered in the support room from the repo reference and intake rules.
- `request` → acknowledged and logged locally; not escalated. `@frontdesk requests` in `#eng`
  lists them, newest first, with who asked.
- `off-topic` → one polite line, no further engagement, no model calls on follow-ups in that thread.
- `bug` with missing fields → ask once for exactly the missing fields; no ticket until complete.
- `bug`, complete → **duplicate check** before escalating: one lite-model call (see section 6) with the
  titles and summaries of all open tickets, asking whether this is the same problem. Match →
  reply "already tracked as `BL-n`, I'll tell you when it's fixed", add the reporter to that
  ticket's subscribers, post nothing to `#eng`. No match → new ticket, escalate.
- On close → notify the original reporter and every subscriber in the support room. A close is
  `Verified BL-n: <PR url>` at the start of a message in `#eng`, and only from the reproducer
  (known by its name, looked up at start from `SWITCH_REPRODUCER_AGENT_ID`, which bootstrap
  writes) or the room owner by hand (`sender_role` is `owner`). `Not verified BL-n: <why>` → the
  ticket stays open. Anyone else naming a ticket → "only @reproducer or the room owner can close".
  Without the agent id, only the owner can close. `status` shows who closed each ticket.
- **Ask the reporter:** `@frontdesk ask BL-n: <question>` in `#eng` posts the question to the
  reporter's support thread; their next message to the front desk goes back, word for word, to
  the eng thread it was asked in. No model call, no rate guard.
- **Reopen:** `still broken` / `reopen` / `not fixed` from a subscriber of a closed ticket reopens
  it and hands it back to `@reproducer` like a new ticket. No model call.
- **Language:** the classification names the language the user wrote in; the ticket in `#eng` is
  in English and says "wrote in Hindi". Replies to that user (including "fixed" and `ask`
  questions) cost one lite-model `translate` call each; their `ask` answers are translated to
  English. Rate-guard replies stay in English, since they exist to avoid model calls.
- **Rate guards:** a user may have at most **5 open tickets**; beyond that the front desk replies
  "let's resolve the open ones first" and does not escalate. A per-user cooldown of 3 model-backed
  replies per minute; messages over the limit get a short "give me a minute" and are not sent to
  the model. Both guards live in `store.py` and are checked before any model call.

Tests: 6–8 pytest tests that pass. The two tests that would catch faults 1 and 2 are deliberately
absent; the fixer adds them during the demo.

## 3. Repo layout

```
bugline/
  CLAUDE.md                 this file
  AGENTS.md                 one line pointing OpenCode here
  README.md                 judge-facing; structure in section 8
  LICENSE                   MIT
  bugline.toml              the project the agents work on: repo, paths, test command, ticket
                            prefix, report fields, room and agent names (BUGLINE_CONFIG = another)
  demo-app/                 FastAPI app, tests, Dockerfile, docker-compose.yml, seed.py
  agents/common/            Switch protocol client, ticket id format, .env loading, project.py
                            (reads bugline.toml, fills the $placeholders in switch/ files) (shared)
  agents/frontdesk/           agent.py, prompts/, Dockerfile, .env.example, requirements.txt
  agents/coder/             bugline-repro and bugline-fixer: one program running Claude Code
  switch/
    bugline.template.yaml   room template: params / room / kickoff (no agents: block)
    room-instructions-support.md
    room-instructions-eng.md
    docs/                   intake-rules.md, repro-checklist.md, fix-policy.md
    agent-briefs/           frontdesk.md, reproducer.md, fixer.md
  scripts/bootstrap.py      one idempotent run: agents, bugline-eng, access rules, links, bugline-kit
  docs/                     switch-setup.md, own-repo.md, build-journal.md, images/ (screenshots)
```

## 4. Stack and conventions

### Engineering principles (apply everywhere, every day)

- **DRY — do not repeat yourself.** One definition per fact: the ticket-id format, the JSON schema,
  the Switch base URL, the room names, the model names each live in exactly one place (a constant,
  a config module, or one doc) and are referenced from everywhere else. The same goes for prose:
  briefs, room instructions and README sections link to each other instead of restating. If you
  find yourself pasting a block a second time, extract it first.
  Project names (repo, paths, test command, ticket prefix, report fields, room and agent names)
  live in `bugline.toml`, read through `agents/common/project.py`; switch/ files use `$placeholders`.
- **Feature branches and PRs only.** `main` is never committed to directly. Every piece of work —
  code, docs, briefs, README — starts on a branch named `feat/<area>-<short-slug>`,
  `fix/<area>-<short-slug>` or `docs/<short-slug>`, cut from the latest `main`. When the work is
  done, open a PR from that branch to `main` with a title in the form `area: what changed`, a
  description that says what, why, and how it was tested, and labels from the set
  `demo-app`, `frontdesk`, `switch-config`, `docs`, `infra`, `hackathon`. **Merge with squash** so
  `main` has one clean commit per PR; delete the branch after merging. Small commits on the branch
  are fine and encouraged — they get squashed.
- **Newest compatible versions of everything.** Before adding or pinning any library, tool, base
  image, GitHub Action or CLI (Python, FastAPI, pytest, httpx, websockets, `google-genai`, ruff,
  Docker base images, OpenCode/Claude Code, Switch Console), look up the current latest release
  and use it unless a documented incompatibility forces an older one; record the reason in the
  commit if it does. Pin exact versions in `requirements.txt` / `pyproject.toml` so judges get the
  same build. Re-check versions on Nov 3 and again before the final tag.
- **Context7 MCP for documentation.** Use the Context7 MCP server to pull the latest docs for
  every library and tool before writing code against it (FastAPI, pytest, httpx, websockets,
  `google-genai`, ruff, Docker Compose, Telegram Bot API, Slack API). Do not rely on memorised API
  shapes; they are often stale. For Switch itself use its own docs MCP
  (`https://docs.switchagents.ai/mcp`). If Context7 has no entry for a tool, fetch its official
  docs page and say so.

### Stack

- Python (newest stable 3.x), FastAPI, SQLite via `sqlite3` or SQLModel (pick one, stay with it),
  pytest, httpx, `websockets`, `google-genai` SDK — all at their newest compatible releases, pinned.
  No Postgres, no ORM migrations, no frontend.
- Format with `ruff format`; lint with `ruff check`. Type hints on public functions.
- One module per concern in the frontdesk: `switch_client.py` (register, WebSocket, ops),
  `classify.py` (Gemini call + JSON schema), `handlers.py` (bug / question / request paths),
  `store.py` (SQLite ticket table), `agent.py` (main loop).
- Secrets only via environment variables; `.env.example` lists every variable with a comment;
  `.env` is gitignored. **Never commit a key, token, or chat-app secret.**
- Windows host: paths in docs use `C:\bugline-agents\<agent>` for agent working directories;
  shell snippets in README are PowerShell first, bash second.
- Commit messages: `area: what changed` (`frontdesk: backoff on 429`). Small commits, one concern
  each, on a feature branch; the PR's squash commit carries the PR title.
- Tests run with `pytest -q` from `demo-app/`; the app runs with `docker compose up` from the repo root.

## 5. Switch protocol facts (for the custom frontdesk)

- Confirm the bridge base URL with `GET /health`. It is usually **not** the Gateway URL.
- Register once with `POST /agents` using a *registration* API key (`POST /gateway/api-keys`).
  Body: `name` (`^[a-z0-9][a-z0-9._-]*$`), `description`, `connector_type: "custom"`,
  `integration_profile: {connection_model: "session_addressable", message_exchange: true,
  pre_invocation_mediation: [], post_invocation_mediation: [], event_reporting: []}`.
  The response returns `id` and `api_key` **once** — persist both. Re-registering the same name
  returns 409; `overwrite: true` issues a new key and breaks the old one. Do not use
  `POST /agents/register-known`.
- New agents answer only their owner. The agent cannot change this itself (the server refuses
  `update_agent_detail` on yourself with 403): the owner sets **Who can talk to your agent → Anyone**
  for `bugline-frontdesk` (`PUT /gateway/agents/{id}/addressing-policy {"policy": null}`).
- Connect: WebSocket at `/agents/{agent_id}/connection/ws` with `Authorization: Bearer <api_key>`;
  the connection id (UUID, reused on reconnect) and the room go in **query parameters**.
  **One connection covers one room**, so the frontdesk holds two (support + eng), and each op call
  carries the `X-Switch-Connection-Id` of the room it acts in. SSE is deprecated.
- Lifecycle: take `rooms`, `cursor` and `generation` from the `connection_state` frame, not from
  what you requested. Answer every `ping` with a `pong` carrying the cursor. Act on a `message`
  event **only when `payload.addressed` is true**. The text is in `payload.body`; there is no
  mentions list, so ticket ids and PR links are parsed from the body.
- Operations: discover with `GET /agents/{id}/ops` at startup; invoke with
  `POST /agents/{id}/ops/<name>`, header `X-Switch-Connection-Id`, body = bare arguments.
  `post_message(body, thread_id)` posts to the connection's room (no room id, no mentions);
  `send_targeted_message(body, target_names, target_roles, thread_id)` is how one agent hands work
  to another and reports whether each target is reachable. Errors: 400 bad args, 403 permission,
  404 unknown op, 409 dead connection. Arguments are validated against the function signature,
  not the published schema.
- Without a connection, `POST /agents/{id}/message` with `{room_id, content}` posts a message
  (no threading).
- There is no task protocol: one agent hands work to another with a targeted message.
- Roles are not access rules. An agent holds one role across all rooms, so `@frontdesk` is a
  per-room alias (`!set-alias`), not a role. A role mention (`@fixer`) reaches an agent only while
  its session is live and holds the role. "PM only, in `bugline-eng` only" is a custom access rule
  the owner sets on `bugline-fixer` (`owner: true`, `rooms: [<eng id>]`, set by
  `scripts/bootstrap.py`); templates only offer `owner`, `owner-agents`, `anyone`. Refusals are posted by Switch, and their wording depends on account linking.
- Templates can create and link only their own rooms; the Telegram room is adopted by adding the
  bot, and the custom frontdesk is registered by its own script. `docs/switch-setup.md` lists what
  is manual.
- Switch Console on Windows runs the server natively. Its ports are in
  `%APPDATA%\switchdash\local-switch-server\ports.json` (`api` is the bridge) and can change on
  restart. It serves no Gateway web UI; the Gateway API under `<api>/gateway/...` works with the
  admin login in `native\run\switch-core.env` (cookie from `POST /gateway/auth/login`). It cannot
  run managed coding agents ("SDK sessions require a POSIX SSH execution host"), and
  `POST /gateway/rooms/from-yaml` refuses a template `agents:` block. Hence `agents/coder` and
  `scripts/bootstrap.py` (verified Nov 4, Console 0.40.1, server 0.31.0).
- Docs are available to agents over MCP at `https://docs.switchagents.ai/mcp`; use it to check any
  detail above before relying on it.

## 6. Gemini free tier (Google AI Studio key)

- Default model `gemini-2.5-flash`; use the lite model for the frontdesk's classification
  call so load spreads across two quotas. The model names live in `agents/frontdesk/config.py`.
  `gemini-2.5-flash-lite` is closed to new users (404 on Nov 4), so the lite model is
  `gemini-3.5-flash-lite`. Structured output via a JSON schema:
  `{kind: "bug"|"question"|"request"|"off-topic", language: string, missing: [string], report: {title, steps, expected, actual, group_id}}`.
  The report fields are always in English, whatever language the user wrote in.
  The duplicate check is a second, separate lite-model call returning
  `{duplicate_of: "BL-n" | null, confidence: number}`; treat confidence under 0.7 as no match.
- Exponential backoff on HTTP 429 and 503 (start 2 s, cap 30 s, 5 tries), then post "I'm
  rate-limited right now. Please send that again in a minute" rather than failing silently. The agent does not
  retry on its own.
- Log every model call to `agents/frontdesk/calls.log` (timestamp, model, tokens). We quote these
  numbers in the blog. Target under 25 calls per full loop.
- Keep agent replies under 10 lines; no chatter; never call the model for a message that does not
  address the agent.

## 7. Working rules for the agent

- **Before any slow or destructive action** — `docker compose up` the first time, deleting a
  branch, force-pushing, disconnecting a chat app, re-registering a Switch agent — stop and ask.
  Disconnecting a chat app in Switch deletes every room on it irreversibly; never do it.
- Keep diffs small and explain them in one paragraph the author could repeat to a judge. If a
  change needs more than ~150 lines, propose the split first.
- Start every task by confirming you are on a fresh feature branch off `main` (never on `main`);
  end every task by opening or updating the PR (title, description, labels) and saying so.
- Before writing code against any library, pull its current docs through Context7 and check the
  newest release; before adding a dependency, state the version you are pinning and why.
- Before duplicating any constant, schema, prompt text or paragraph, find where it already lives
  and reference it (DRY).
- Prefer boring, well-known patterns. No new dependencies without a one-line reason in the commit.
- Do not "fix" the seeded faults in `demo-app/` unless the task is explicitly the fixer's demo run.
- When something is unverified (Console on Windows, OpenCode's Google provider, template schema
  support for links and custom agents, exact free-tier limits), say so and propose the cheapest
  test, instead of assuming.
- Prompts to this agent are often dictated. Read them for intent; ask one question if
  a spoken instruction is ambiguous instead of guessing.
- Naming: the intake agent is `@frontdesk` and its rules file is `intake-rules.md`. Do not use the
  word "triage" anywhere in code, docs, README, briefs, commit messages or the video script; the
  pitch leads with the cross-app handoff, the approval gate and the closed loop, and mentions
  classification in one sentence at most.
- Write prose files (briefs, room instructions, README sections) in the author's plain voice:
  short sentences, specific nouns, no marketing adjectives. These are instructions to colleagues.
- Everything you write must be explainable by the author. Add a short docstring to each module
  saying what it does and why it exists.
- Keep a running `docs/build-journal.md`: one dated entry per session with what was done, what
  broke, what fixed it. This feeds the blog.

## 8. README structure (judge-facing)

Each heading's first sentence answers its criterion.

1. Bugline — one paragraph + GIF
2. Why this stops working without Switch (Use of Switch)
3. Architecture (diagram)
4. The workflow, step by step, with screenshots (a judge sees how Switch is used before setup)
5. Reproduce it (Technical execution): prerequisites, `docker compose up`, fork, env vars,
   Telegram and Slack connection steps — every command copied from a real run. Side material
   (the Mattermost variant, running on another repo) lives in `docs/`, not the README
6. The agents: runtime, role, access rule, link to each brief
7. The problem this solves for a real team (Creativity and impact)
8. What the agents got wrong and how the briefs fixed it
9. Limits and next steps
10. Licence and credits

## 9. Day-by-day checklist

Tick items as they are done. "Done" for the project = the three never-cut moments work from a fresh
clone and are on video.

### Day 0 — Nov 3 (tooling only; no workflow building)

- [ ] Register for the hackathon; star `sandbox-quantum/switch`; join the WeMakeDevs Discord
- [ ] Ask in Discord: judging weights? one project in two tracks? video length limit? submission form?
- [x] Create repo `bugline` (MIT; private until submission, flip to public before Nov 7); commit this file and `AGENTS.md` on `docs/bootstrap`,
      open the first PR, squash-merge it
- [x] Protect `main`: require a PR, allow squash merge only, delete branches on merge; create the
      labels `demo-app`, `frontdesk`, `switch-config`, `docs`, `infra`, `hackathon`
- [ ] Install the Context7 MCP in Claude Code / OpenCode and confirm it returns docs for FastAPI
- [x] Check newest releases of Python, FastAPI, pytest, httpx, websockets, `google-genai`, ruff and
      the Docker base image; note them in `docs/build-journal.md`
- [x] Docker Desktop (WSL2) works: `docker run hello-world`
- [x] Install latest stable Switch Console for Windows; start a local server; bundled Mattermost up
- [x] Decide the coding-agent provider: if the Claude subscription includes Claude Code, sign in
      and prefer it; otherwise install OpenCode, configure Google provider with the AI Studio key
- [ ] Console > Settings > Agent providers shows "Signed in" (if "CLI not installed": close the
      Console window — this quits the app on Windows — and reopen)
- [ ] Create the Switch expert from Templates with "Start it in a room"; it answers one question
- [x] **Go / no-go:** provider answers in a room → Route A for reproducer/fixer. Otherwise Route B
      (custom Python agents) for everything, 90-minute cap on trying. Route B: Console cannot run
      coding agents on Windows
- [ ] Add the Switch docs MCP (`https://docs.switchagents.ai/mcp`) to the coding agent
- [x] Telegram: BotFather bot, group `bugline-support`, connect in Console
- [x] Slack: create app in the personal workspace, channel `#bugline-eng`, connect in Console
- [x] Gateway > API Keys: registration key; `GET /health` on the bridge
- [ ] 20-line Python skeleton: register `hello-agent`, WebSocket, pong, post "hi" when addressed
- [ ] Dictate build-journal entry for the day

### Day 1 — Nov 4 (demo app + eng room + reproducer)

- [x] `demo-app/` endpoints, seed, Dockerfile, compose; faults 1 and 2 planted; 6–8 passing tests
- [x] Fresh clone: `docker compose up` + `curl` works
- [x] PR `demo-app: expense splitter with seeded faults` squash-merged to `main`; this is the
      repo the room references
- [x] Room `bugline-eng` on Slack; room instructions set; repo registered as reference
- [x] Documents `intake-rules.md`, `repro-checklist.md`, `fix-policy.md` attached
- [x] Roles `reproducer` (shared) and `fixer` (exclusive) defined; `!roles` shows both
- [x] Agent `bugline-repro` created, added to the room, holds `reproducer`
- [x] "@reproducer the share link for group 1 returns 500 — reproduce it" → script, traceback, cause
- [x] Non-bug report → "could not reproduce" with what it tried
- [ ] Commit `switch/`; journal entry; 20-second clip of the reproducer result

### Day 2 — Nov 5 (frontdesk + Telegram + full loop)

- [x] `agents/frontdesk/`: register once, WebSocket loop, pong, reconnect with same connection id
- [x] Classification with JSON schema; question → answer from repo; incomplete → ask; complete →
      post to `bugline-eng` mentioning `@reproducer` with ticket id `BL-n`
- [x] SQLite ticket table: ticket id → reporter id, support room id, status, summary,
      `subscribers` (list of reporter ids)
- [x] `off-topic` class: one polite reply, no follow-up engagement
- [x] Duplicate check against open tickets before escalating; match → "already tracked as
      `BL-n`", subscribe the reporter, nothing posted to `#eng`
- [x] Close notifies the reporter **and** all subscribers
- [x] Rate guards in `store.py`: max 5 open tickets per user; 3 model-backed replies per user
      per minute; both checked before any model call
- [ ] Test the quiet paths: duplicate report, off-topic message, 6th open ticket, burst of
      messages from one user
- [x] Backoff on 429; calls.log
- [x] `addressing: anyone`; `connection_model: session_addressable`
- [x] Dockerfile + compose service for the frontdesk
- [x] Room `bugline-support` on Telegram; frontdesk in both rooms; `!follow-ups off` in both
- [x] Links: support → eng `escalates to`; eng → support `supports`
- [ ] Second Telegram account as the "end user"
- [x] Agent `bugline-fixer`: exclusive role `fixer`; access rule PM-only in `bugline-eng`;
      `gh auth login` in its working directory
- [ ] Refusal test from a second Slack user → refused
- [x] Approval test: "@fixer go on BL-1, keep it to the share handler, add a regression test" →
      branch, tests, PR link, mentions `@frontdesk BL-1`
- [x] Front desk posts "BL-1 is fixed — <PR link>" in Telegram
- [ ] Full run on fault 1; record model-call count and wall time; journal; clips of handoff + refusal

### Day 3 — Nov 6 (feature freeze; reproducibility, README, video)

- [ ] `switch/bugline.template.yaml` (`version: 1`, modelled on the official `triage-pair`
      template); tested with a fresh team prefix
- [x] If the template cannot express two rooms / links / the custom agent → `scripts/bootstrap.py`
      via the Gateway API, documented
- [ ] README per section 8; every "Reproduce it" command tested from a fresh clone in a new folder
- [ ] `.env.example` for frontdesk and demo app; no secrets committed
- [ ] Rehearse the video script; record with both apps on screen right after a quota reset;
      upload unlisted; link in README
- [ ] Blog draft assembled from the journal

### Day 4 — Nov 7 (polish, publish, submit by 9 PM IST)

- [ ] Final fresh-clone test; fix README gaps only
- [ ] Final video export; link opens in a private window
- [ ] Blog published (dev.to or Hashnode, tags `switch`, `wemakedevs`, `hackathon`); link in Discord
- [ ] Three #HowISwitch clips posted with the repo link
- [ ] All PRs squash-merged; no open branches; `main` history reads as one line per PR
- [ ] Final version check: every pinned dependency is still the newest compatible release
- [ ] README checked against the judging table; tag `v1.0-hackathon`
- [ ] Submit: repo, video, README, Track 01, blog link; confirmation screenshot

### If behind, cut in this order

1. Fault 2 (rounding)
2. PR opening — fixer posts diff + test output instead
3. Room template — replaced by `scripts/bootstrap.py` + documented manual setup
4. Blog

Never cut: cross-app handoff, refusal moment, loop closing back to the reporter, fresh-clone test.

## 10. Video script (3–4 minutes, both apps on screen throughout)

| Time | Beat | On screen |
| --- | --- | --- |
| 0:00–0:15 | Hook | Both rooms quiet; one-line pitch |
| 0:15–0:40 | Report | User reports in Telegram; frontdesk asks for the group id |
| 0:40–1:00 | Handoff | Structured report appears in `#bugline-eng` tagging `@reproducer` |
| 1:00–1:25 | Reproduce | Script, traceback, likely cause |
| 1:25–1:40 | Second app | A Mattermost user reports the same bug in `bugline-support-mattermost` → "already tracked as BL-1" |
| 1:40–1:55 | Refusal | Second Slack user: "@fixer fix it" → refused by Switch |
| 1:55–2:20 | Approve + fix | PM instruction; branch, tests, PR link |
| 2:20–2:35 | Verify | Fixer hands the PR to `@reproducer`; "Verified BL-1: PR link" |
| 2:35–2:55 | Close the loop | "BL-1 is fixed — PR link" lands in Telegram and in Mattermost |
| 2:55–3:10 | Approvers | `approvers = [...]` in `bugline.toml`, one bootstrap run, the same second user's `@fixer` now goes through. No code change |
| 3:10–3:35 | Quiet paths | Question answered without escalation; vague report asked for details; off-topic dropped; "could not reproduce" |
| 3:35–3:55 | Reproduce it | README section, `bootstrap.py`, `doctor.py` all PASS, `docker compose up` |

## 11. Links

- Hackathon: https://www.wemakedevs.org/hackathons/switch (rules, schedule, resources under it)
- Discord: https://discord.gg/E2rWw2Yhsm
- Switch repo: https://github.com/sandbox-quantum/switch · releases: /releases/latest
- Docs: https://docs.switchagents.ai/ · index: https://docs.switchagents.ai/llms.txt
- Quickstart: https://docs.switchagents.ai/switch-rooms/getting-started
- Framework: https://docs.switchagents.ai/switch-rooms/building/index
- Payments room example: https://docs.switchagents.ai/switch-rooms/building/payments-room
- Agent protocol: https://docs.switchagents.ai/switch-rooms/internals/agent-protocol
- Agent connection / events: .../internals/agent-connection.md · .../internals/agent-events.md
- Room templates: https://docs.switchagents.ai/switch-rooms/administer/room-templates.md
- Messaging apps: https://docs.switchagents.ai/switch-rooms/deploy/messaging-apps/index
- Troubleshooting: https://docs.switchagents.ai/switch-rooms/resources/troubleshooting.md
- Official template to model ours on:
  https://github.com/sandbox-quantum/switch/blob/main/examples/agent-templates/triage-pair.template.yaml
- Chat commands: `!roles` · `!set-alias` · `!follow-ups off` · `!reset`

Unverified as of Nov 4 (test before relying on): Console early-access build on Windows; OpenCode
with Google as provider inside Console; whether Claude Code is available on the current
subscription; how long a managed agent's session (and so its role) stays live; refusal wording for an
unlinked Slack user; exact free-tier limits for
`gemini-2.5-flash` and `gemini-3.5-flash-lite` on this project.