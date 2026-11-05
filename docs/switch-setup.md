# Setting up Bugline in Switch

How to stand up both rooms, all three agents and everything between them. Part A is done by hand
in Telegram, Slack and Switch Console. Part B is one script. Part C starts the agents.

Parts A and C and the smoke run were done live on Nov 4, 2026, with Switch Console 0.40.1 and
server switch-core 0.31.0 on Windows 11. That day the part B steps were done with single Gateway
API calls; `scripts/bootstrap.py` was written from those calls and then run against the finished
setup, where it found everything and added `bugline-kit`. Its create paths are covered by unit
tests against a fake server, not by a fresh server.

What goes where:

| Thing | Made by |
| --- | --- |
| Telegram connection, `bugline-support` room | By hand: the bot joins the Telegram group (part A) |
| Slack connection, your linked accounts | By hand in Console (part A) |
| Registration key, the three agents, `bugline-eng` and its Slack channel, roles, the `bugline-repo` reference, agents in rooms, access rules, room instructions, links, `@frontdesk` aliases, `bugline-kit`, the room ids in both `.env` files | `scripts/bootstrap.py` (part B) |
| `bugline-support` on a chat app where Switch can create channels (not Telegram) | `scripts/bootstrap.py`, from `switch/bugline-support.template.yaml` ([other chat apps](#other-chat-apps)) |
| `!follow-ups off` in both rooms, starting the agents | By hand (part C) |

> **Never disconnect a messaging app in Switch.** Disconnecting deletes every Switch room on that
> app, with its history, and cannot be undone. To change a token, edit the connection; do not
> disconnect and reconnect.

## 0. Before you start

- Switch Console installed, with its local server running (Console Home shows it).
- Python 3.14, Git, and a Google AI Studio key for the front desk.
- Claude Code signed in (`claude`), and the GitHub CLI signed in (`gh auth login`) with your git
  name and email set. The fixer opens PRs with these logins.
- A Telegram account with a username, and a Slack workspace you own.

## Part A: the chat apps, by hand

### 1. Telegram bot and group

1. In Telegram, open `@BotFather` and send `/newbot`. Give it a display name and a username ending
   in `bot`. Save the token straight away.
2. Turn off group privacy **before** adding the bot anywhere: `/mybots` → your bot → **Bot
   Settings** → **Group Privacy** → **Turn off**. Telegram reads this when the bot joins.
3. Create a Telegram group named `bugline-support`. Do not add the bot yet.

### 2. Connect Telegram

1. Switch Console → server **Home** → **Messaging apps** → **Connect** → **Telegram**.
2. Fill in **Name** (`Bugline Telegram`), **Bot Token** and **Bot Username**. Select **Connect**.
3. Add the bot to the group, then post any message there. Switch creates a room named after the
   group, `bugline-support`.
4. Console Home → **Link your Telegram account** → **Link account**.

### 3. Connect Slack

1. At https://api.slack.com/apps → **Create New App** → **From an app manifest**. Paste the
   manifest from https://docs.switchagents.ai/switch-rooms/deploy/messaging-apps/slack.md. If the
   workspace has guests, delete the `agent_view` block first; it cannot be undone later.
2. **Basic Information** → **App-Level Tokens** → create one with scope `connections:write`
   (`xapp-...`).
3. **Install App** → copy the **Bot User OAuth Token** (`xoxb-...`).
4. Find the workspace id `T...` in the browser address `https://app.slack.com/client/T.../C...`.
5. Switch Console → **Home** → **Messaging apps** → **Connect** → **Slack**. Fill in **Name**
   (`Bugline Slack`), **Bot Token**, **App-level token**, **Workspace Id**. Leave **Allow creating
   channels from Switch** on. Select **Connect**.
6. **Link your Slack account** → **This is me**. You are the owner of the agents bootstrap
   registers, and the fixer admits only its owner, so your Slack messages must map to your Switch
   user.

Do not create `#bugline-eng` by hand; bootstrap makes the room and its channel.

## Part B: `scripts/bootstrap.py`

### 4. Agent folders

The front desk and the coders run natively, with their own venvs. The front desk's venv also runs
bootstrap.

```powershell
cd agents\frontdesk
py -3.14 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env   # set GEMINI_API_KEY; bootstrap fills in the Switch values
cd ..\coder
py -3.14 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
cd ..\..
git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-repro\bugline
git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-fixer\bugline
# in each clone's demo-app\: py -3.14 -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
```

```bash
cd agents/frontdesk
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # set GEMINI_API_KEY; bootstrap fills in the Switch values
cd ../coder
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ../..
git clone https://github.com/Ishaan2053/bugline.git ~/bugline-agents/bugline-repro/bugline
git clone https://github.com/Ishaan2053/bugline.git ~/bugline-agents/bugline-fixer/bugline
# in each clone's demo-app/: python3.14 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

More on each agent's settings: [agents/frontdesk/README.md](../agents/frontdesk/README.md),
[agents/coder/README.md](../agents/coder/README.md).

### 5. Run bootstrap

From the repo root:

```powershell
agents\frontdesk\.venv\Scripts\python scripts\bootstrap.py --dry-run
agents\frontdesk\.venv\Scripts\python scripts\bootstrap.py
```

```bash
agents/frontdesk/.venv/bin/python scripts/bootstrap.py --dry-run
agents/frontdesk/.venv/bin/python scripts/bootstrap.py
```

`--dry-run` logs in and reads, and prints every write instead of sending it. The real run prints
one line per thing: `created`, `updated`, `exists` or `skipped (why)`. Run it again any time; a
second run on a finished setup prints only `exists`. What it does, in order, is in the script's
docstring. In short:

1. Reads the API port from Console's `ports.json` and the local admin login from Console's
   `switch-core.env`, checks `/health`, and logs in.
2. Uses the registration key in `agents/frontdesk/.env`, or creates one and saves it there.
3. Registers `bugline-frontdesk`, `bugline-repro` and `bugline-fixer` if their
   `credentials.json` is missing.
4. Finds `bugline-support` on the Telegram connection. If it is not there, it stops and tells you
   to add the bot to the group and post once. (On a chat app where Switch can create channels, it
   makes the room from `switch/bugline-support.template.yaml` instead; see
   [other chat apps](#other-chat-apps).)
5. Makes `bugline-eng` on the Slack connection from `switch/bugline.template.yaml`. A room is
   matched by its name and its connection, so `bugline-eng` on Slack and `bugline-eng` on
   Mattermost can sit side by side on one server.
6. Writes `SWITCH_API_URL` and the room ids into `agents/frontdesk/.env` and `agents/coder/.env`.
7. Puts the front desk in both rooms and the coders in `bugline-eng`.
8. Access rules: the front desk open to anyone (Telegram users have no Switch account), the
   reproducer its owner and the owner's agents (the PM and the front desk), the fixer its owner
   only, in `bugline-eng` only.
9. Room instructions from `switch/room-instructions-*.md`, the links (`bugline-support` →
   `bugline-eng` "escalates to", back "supports"), and the alias `@frontdesk` in both rooms.
10. `bugline-kit`: the three files in `switch/docs/` as library documents (updated when a file
    changes), the `bugline-repo` reference, attached to both rooms.

On a team server, set `SWITCH_API_URL`, `SWITCH_ADMIN_EMAIL` and `SWITCH_ADMIN_PASSWORD` first.
If you have two connections of one chat app, pass `--support-connection "<name>"` or
`--eng-connection "<name>"` (`--slack-connection` still works for the eng room); if the support
room has another name, pass `--support-room <name or id>`.

A link tells agents the other room exists. It does not let anyone into it.

### Other chat apps

Each room can be on any chat app Switch connects. `--support-bridge` and `--eng-bridge` take the
app as Switch names it (`bridge_type` in `GET /gateway/collaborations`); the defaults are
`telegram` and `slack`, from `[rooms]` in `bugline.toml`, and
`BUGLINE_SUPPORT_BRIDGE` / `BUGLINE_ENG_BRIDGE` in `agents/frontdesk/.env` change them. Bootstrap
reads `channel_creation_supported` and `channel_creation_enabled` on the connection: where both
are true it makes a missing room from its template; where they are not, it stops and says what to
do. The flags are not saved, so a later run without them goes back to the defaults and rewrites
the room ids in both `.env` files. The fixer's access rule names the eng room bootstrap picked,
so it follows too.

- **Telegram.** Switch cannot create Telegram chats (`channel_creation_supported` is false). The
  room appears when the bot joins the group and someone posts (step 2). This is the author's
  support room.
- **Slack.** Switch makes the channel, if **Allow creating channels from Switch** is on for the
  connection (step 3). This is the author's eng room.
- **Mattermost.** Switch Console starts a Mattermost server with its local server (in Docker) and
  connects it as `Mattermost`; on the author's server it was `active`, with channel creation on.
  It is at `http://localhost:<port>`, the port being `mattermost` in Console's `ports.json`.
  `--support-bridge mattermost --eng-bridge mattermost` makes both rooms there and needs no
  Telegram or Slack account; see the README's Mattermost variant. Checked with unit tests and a
  dry run only; no real run.
- **Discord, Microsoft Teams.** Switch can create channels on both, so the same flags should work
  (`--support-bridge <type>`, with the type as `GET /gateway/collaborations` shows it). Untested.

## Part C: start the agents

### 6. Start the three agents

One terminal each, from the repo root:

```powershell
cd agents\frontdesk; .\.venv\Scripts\python agent.py
cd agents\coder; $env:CODER_ROLE = "reproducer"; .\.venv\Scripts\python agent.py
cd agents\coder; $env:CODER_ROLE = "fixer"; .\.venv\Scripts\python agent.py
```

```bash
cd agents/frontdesk && .venv/bin/python agent.py
cd agents/coder && CODER_ROLE=reproducer .venv/bin/python agent.py
cd agents/coder && CODER_ROLE=fixer .venv/bin/python agent.py
```

Each coder logs `holding the role reproducer` (or `fixer`), and Switch posts "assumed the
`reproducer` role" in `bugline-eng` the first time.

### 7. Quiet the rooms

In both rooms, so agents act only when named:

```
!follow-ups off
```

Check in `#bugline-eng`: `!roles` shows `reproducer` held by `bugline-repro` and `fixer` held by
`bugline-fixer`.

## Smoke run: the seeded paths

The paths are the seeded-faults table in [CLAUDE.md](../CLAUDE.md#demo-app-expense-splitter-demo-app).
These are the messages that passed on Nov 4. "User" is you in `bugline-support`; "second user" is
another person (on Nov 4, a second Switch user, `sam`, posting through the Gateway chat API);
"PM" is you in `#bugline-eng`. In Telegram the live messages named the agent as
`@bugline-frontdesk @<bot username>`; `@frontdesk` worked the same from the chat API. Keep
`agents/frontdesk/calls.log` open to count model calls.

**Path 4, then path 1: vague report, then the full loop.** User:

```
@frontdesk the share link is broken.
```

Expect: "Thanks. To pass this to the team I need the steps you took and your group id." No ticket.
Then, in the same thread:

```
@frontdesk group 1, I opened the share link goa-trip-share expecting the summary but got Internal Server Error. It did not specify what error.
```

Expect: "Thanks, logged as BL-1 and passed to the team." In `#bugline-eng`, `BL-1` in the shape in
`switch/docs/intake-rules.md`, addressed to `@reproducer`. The reproducer posts "Working on it",
then `Verdict: reproduced` with the `ZeroDivisionError` in `demo-app/app/main.py`, `share()`.

**Approve and close.** PM, in the `BL-1` thread:

```
@fixer go on BL-1, keep it to the share handler, add a regression test
```

Expect, in about a minute: `@reproducer please verify BL-1 on PR
https://github.com/<you>/bugline/pull/<n> (branch fix/demo-app-bl-1-...-<stamp>)`. The reproducer
then checks out the PR and posts `@bugline-frontdesk Verified BL-1: <PR link>`, the front desk
answers "Closed BL-1, telling the reporter.", and in `bugline-support` "<you>, BL-1 is fixed: <PR
link>". `@frontdesk status` shows `closed by bugline-repro`. Do not merge the PR; it removes the
seeded fault.

**Ask the reporter.** PM, in the ticket's thread, before approving:
`@frontdesk ask BL-1: which browser were you using?` → "Asked <you> in bugline-support. Their
answer will come to this thread." In `bugline-support` the reporter gets the question under their
report; their next message (`@frontdesk Firefox 131 on Windows`) comes back to the `BL-1` thread as
"<you> answered <PM>'s question on BL-1: Firefox 131 on Windows". No model call.

**Reopen.** After the close, the reporter, in their thread: `@frontdesk still broken for me` →
"Reopened BL-1 and passed it back to the team." In `#bugline-eng`, `BL-1 (reopened): ...` addressed
to `@reproducer`, with the PR that closed it. The PR is not merged, so the reproducer reproduces
again. Close it by hand as the PM with `@frontdesk Verified BL-1: <PR link>`.

**Any language.** Second user: `@frontdesk bhai share link kholte hi error aa raha hai` → the
missing-field question in Hinglish. Completing it in Hinglish opens a ticket whose report in
`#bugline-eng` is in English, with "wrote in Hinglish" on the reporter line. One `translate` line
in `calls.log` per translated reply.

**Path 3: not a bug.** User:

```
@frontdesk it says I owe money for the Goa trip dinner, but I already paid for it myself. Why?
```

Expect: an answer from `demo-app/README.md` (the expense has the wrong payer; re-add it). Nothing in
`#bugline-eng`.

**A request.** `@frontdesk can you add a way to edit an expense?` → "Thanks, I've noted that as a
request for the team." Nothing in `#bugline-eng`. PM: `@frontdesk requests` lists it with the
sender's name and age.

**Path 6: off-topic.** `@frontdesk what's a good phone under 20k?` → "Sorry, that's not something
I can help with here." A follow-up in the same thread (`@frontdesk hello?`) gets no reply and no
model call.

**Path 2: a paisa short.** User:

```
@frontdesk group 1 settle-up is wrong. Steps: opened Settle up for the Goa trip. Expected: the payments to add up to what we spent. Actual: we spent 9100 but the shares only add up to 9099.99, a paisa goes missing on the 1000 dinner split three ways.
```

Expect: `BL-2`; the reproducer shows `owes` adding to 9099.99 and Ravi getting 666.66 of 666.67,
and names `split_equal()` in `demo-app/app/money.py`.

**Path 5: duplicate.** While `BL-2` is open, second user:

```
@frontdesk for group 1 the settle-up comes out one paisa less than the total we spent. I opened Settle up and expected it to match 9100, but it adds to 9099.99.
```

Expect: "Already tracked as BL-2, I'll tell you when it's fixed." Nothing new in `#bugline-eng`.

**Only the verifier closes.** While `BL-2` is open, a second account in `#bugline-eng`, in the
`BL-2` thread: `@frontdesk Verified BL-2: https://github.com/<you>/bugline/pull/19` → "Only
the reproducer or the room owner can close a ticket, ...", and `@frontdesk status` still shows `BL-2`
open. The PM may post the same line by hand, which closes the ticket and makes `status` show
`closed by <PM>`; try that on a ticket the rest of the run does not need. A PR that does not fix
the bug gets `Not verified BL-n: <why>` from the reproducer, and the ticket stays open.

**Burst.** Second user sends three questions within a minute (`what does net mean in balances?`,
`how does settle up decide who pays whom?`, `can anyone open a share link?`). The first two are
answered; the third gets "Give me a minute, then send that again." with no model call.

**Refusal.** Second user, in `#bugline-eng`:

```
@fixer fix BL-2 now
```

Expect, posted by Switch in the fixer's name: "@sam You're not permitted to direct messages to me
in this room — my operator has restricted who can address me here." The fixer's log shows
nothing.

**Could not reproduce.** PM:

```
@reproducer a user says group 1's balances page shows amounts in dollars instead of rupees. Can you reproduce that?
```

Expect: `Verdict: not reproduced`, what it tried, and a request for what the user opened.

**Close with subscribers.** PM, in the `BL-2` thread:
`@fixer go on BL-2, keep it to the equal split in demo-app/app/money.py so the shares add up to the amount, and add a regression test`.
Expect a PR, the reproducer's `Verified BL-2`, then "BL-2 is fixed" in `bugline-support` for both
the reporter and the second user.

## Troubleshooting

- **Run doctor first.** `agents\frontdesk\.venv\Scripts\python scripts\doctor.py` checks the
  server, both bridges, both rooms, which agents are connected, each agent's key, who holds
  `reproducer` and `fixer`, the access rules, `claude`, `gh`, `git` and the two clones. It only
  reads. Each FAIL line says what to do. A bridge that is not `active` means: restart the server
  in Switch Console; never disconnect the app.
- **Start a take from `BL-1`.** Stop the agents and run `scripts\reset_demo.py --dry-run`, then
  without `--dry-run`. It refuses while any agent is connected, and it never touches
  `credentials.json` or `connections.json`.
- **Which URL is the server?** Console picks the ports when it starts the server and writes them
  to `%APPDATA%\switchdash\local-switch-server\ports.json`, for example
  `{"gateway": 50072, "api": 50073, ...}`. The API (the "bridge") is `api`:
  `GET http://127.0.0.1:<api>/health` answers `{"status": "ok"}`. The ports can change when Console
  restarts; run bootstrap again, then restart the agents. Console runs the server natively, not in
  Docker, so `docker ps` does not show it.
- **There is no Gateway page.** In native mode the server serves no dashboard: Console hides
  "Full admin interface", and the gateway port answers 404 for every path. The Gateway API still
  works under `<api>/gateway/...`, which is what bootstrap uses. It signs in as the local admin
  whose login Console keeps in `%APPDATA%\switchdash\local-switch-server\native\run\switch-core.env`.
- **Providers say "Not supported here".** Console cannot run managed coding agents on Windows
  ("SDK sessions require a POSIX SSH execution host"). That is why the reproducer and the fixer
  are custom agents in `agents/coder`. The template has no `agents:` block for the same reason;
  the server refuses one ("Unknown top-level key(s): agents").
- **A mention reached nobody.** On Slack's free plan Switch cannot make agent user groups
  ("paid_teams_only ... agents remain addressable by typing their name"), so there is no `@`
  autocomplete. Type names exactly: `@reproducer`, not `@repoducer`. A misspelled name fails
  silently.
- **`@reproducer` or `@fixer` gets no reply.** A role reaches an agent only while its program is
  running and holds the role. Check `!roles`; if a role is free, start (or restart) that coder. You
  can always address the agent by name, `@bugline-repro` or `@bugline-fixer`.
- **The refusal wording.** For a second Switch user, the fixer's refusal is "You're not permitted to
  direct messages to me in this room — my operator has restricted who can address me here." A chat
  account that is not linked to any Switch user may get a different message, said only once
  (from the Switch docs; not tested here).
- **Every shell command of a coder is refused.** Claude Code runs in `dontAsk` mode, where each part
  of a chained command must be allowed. `agents/coder/config.py` allows `Bash` and uses deny lists;
  if you narrow it, test a real ticket again.
- **Bootstrap stops at the Telegram room.** The room appears only after the bot is in the group and
  someone has posted there. If the group has another name, pass `--support-room`.
- **Bootstrap says a connection does not allow creating channels.** Turn on **Allow creating
  channels from Switch** for that connection in Console. Never disconnect it to change a setting.
- **Bootstrap says credentials are missing for a registered agent.** The server shows an agent's
  API key once, at registration. Restore `credentials.json` from where you ran it first, or delete
  the agent in Console and run bootstrap again.
