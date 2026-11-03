# Setting up Bugline in Switch

The ordered checklist for standing up both rooms, all three agents and the links between them, by
hand, in Switch Console, the Gateway, Telegram and Slack. Do the steps in order: later steps need
what earlier ones make.

Nothing here has been run end to end yet. Untagged steps follow the Switch docs closely.
**(unverified)** marks steps where the docs are silent or the behaviour is inferred. Fix this file
when a live run shows otherwise.

What goes where:

| Thing | Made by |
| --- | --- |
| `bugline-support` (Telegram) | Adding the bot to the Telegram group (step 2) |
| `bugline-frontdesk` | Its own `--register` run (step 5) |
| `bugline-eng` (Slack), `bugline-repro`, `bugline-fixer`, roles, repo reference | The room template `switch/bugline.template.yaml` (step 8), or by hand (step 8b) |
| Room links, room instructions, front desk aliases | `scripts/setup_rooms.py` (step 10) |
| Fixer access rule, front desk "Anyone", documents, `bugline-kit` | By hand (steps 6, 9, 11) |

## 0. Before you start

- Switch Console installed and a local server running (Home shows it), with agent management on.
- Settings → Agent providers shows **Signed in** for Claude Code or OpenCode. If it says "CLI not
  installed" after installing, close the Switch Console window (on Windows that quits it) and
  reopen it.
- Two Telegram accounts, each with a username (a phone number is not enough): one for you, one
  as the second end user.
- A Slack workspace you own, and a second Slack account in it for the refusal test.
- Python 3.14, Git, the GitHub CLI (`gh`), and a Google AI Studio key for the front desk.

> **Never disconnect a messaging app in Switch.** Disconnecting deletes every Switch room on that
> app, with its history, and cannot be undone. To change a token, edit the connection; do not
> disconnect and reconnect.

## 1. Telegram bot and group

1. In Telegram, open `@BotFather` and send `/newbot`. Give it a display name and a username ending
   in `bot`. Save the token straight away.
2. Turn off group privacy **before** adding the bot anywhere: `/mybots` → your bot → **Bot
   Settings** → **Group Privacy** → **Turn off**. Telegram reads this when the bot joins.
3. Create a Telegram group named `bugline-support` with your two accounts in it. Do not add the
   bot yet.

## 2. Connect Telegram and make `bugline-support`

1. Switch Console → server **Home** → **Messaging apps** → **Connect** → **Telegram**.
2. Fill in **Name** (`Bugline Telegram`), **Bot Token** and **Bot Username**. Select **Connect**.
3. In the Telegram group, add the bot as a member. It needs no admin rights. Switch creates the
   room and it shows under **Your Rooms**.
4. Check the room's name in Console. If it is not `bugline-support`, note its id for step 10
   **(unverified: the room is expected to take the group's title)**.
5. Post any message in the group, then Console Home → **Link your Telegram account** → **Link
   account**. Typing `/` in the group should now list the Switch commands.

## 3. Connect Slack

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
6. **Link your Slack account** → **This is me**. The template in step 8 puts you in the room
   through this link, and the fixer's access rule in step 9 depends on it.
7. Do **not** create `#bugline-eng` by hand if you will use the template; the template creates the
   channel **(unverified: the channel is expected to take the room's name)**.

## 4. Find the bridge URL

Agents talk to the bridge (the API), not the Gateway web page. Switch Console picks free ports, so
look them up **(unverified: a Console server started without Docker will not show in `docker ps`)**.

PowerShell:

```powershell
docker ps --format "table {{.Names}}\t{{.Ports}}"
# For each published 127.0.0.1 port:
Invoke-RestMethod http://127.0.0.1:<port>/health
```

Bash:

```bash
docker ps --format "table {{.Names}}\t{{.Ports}}"
curl -s http://127.0.0.1:<port>/health
```

The bridge answers `{"status": "ok"}` (PowerShell shows `status : ok`). A 401 means the right
host and the wrong path. The Gateway opens from Console Home → **Full admin interface** → **Open**;
its address bar gives the Gateway's host and port, which is usually not the bridge.

## 5. Register the front desk

1. Gateway → **API Keys** → **Create Registration Key**, label `bugline-frontdesk`. You own every
   agent registered with it, which is what lets the reproducer accept the front desk as "my
   agent". Do not use the server's bootstrap `AGENT_REGISTRATION_TOKEN`.
2. Register once. The server returns the id and API key only once; `--register` saves both to
   `agents/frontdesk/state/credentials.json` (gitignored) and refuses to run if that file exists.
   Copy the two values into `scripts/.env` if you use `setup_rooms.py`. Registering the same name
   again fails with 409. Full details and environment variables:
   [agents/frontdesk/README.md](../agents/frontdesk/README.md).

   PowerShell:

   ```powershell
   cd agents\frontdesk
   py -3.14 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env   # fill in the bridge URL, registration key and Gemini key
   python agent.py --register
   ```

   Bash:

   ```bash
   cd agents/frontdesk
   python3.14 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # fill in the bridge URL, registration key and Gemini key
   python agent.py --register
   ```

3. Do not start the agent yet. It must be a member of both rooms first, or the server refuses its
   connection (close code 4403).

## 6. Let anyone talk to the front desk

Switch Console → **Your Agents** → `bugline-frontdesk` → **General** → **Who can talk to your
agent** → **Anyone**.

Telegram users have no Switch account, so any narrower setting refuses them. An agent cannot
change this setting for itself (the API answers 403), which is why it is done here.

## 7. Put the front desk in `bugline-support`

In the Telegram group:

```
!invite-agent @bugline-frontdesk
!set-alias @bugline-frontdesk @frontdesk
```

Telegram also takes `/invite_agent @bugline-frontdesk` **(unverified: whether `!` commands work as
typed in Telegram, or only the `/` forms)**. Console's room form lists only agents Console created,
so use the command or the Gateway room page. Users type `@frontdesk` in full; Telegram does not
autocomplete agent names.

## 8. Make `bugline-eng` from the template

Needs: the front desk registered (step 5), your Slack account linked (step 3.6), the provider
signed in, and this machine online.

1. Make the working directories, and save the agents a slow first clone during the demo:

   ```powershell
   New-Item -ItemType Directory -Force C:\bugline-agents\bugline-repro, C:\bugline-agents\bugline-fixer
   git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-repro\bugline
   git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-fixer\bugline
   ```

2. Switch Console → **Templates** → **Import template** → `switch/bugline.template.yaml`.
3. Open it → **Use template**. Pick the Slack connection for **bridge**. Under advanced, check
   **directory** is `C:\bugline-agents\{agent}` and **provider** is the one signed in. Keep
   **team** as `bugline`. Select **Create all**.
4. If it fails, nothing is created. The error names the cause (`provider_login_missing`,
   `controller_offline`, `name_taken`, ...). Fix it and run again.
5. The kickoff message asks `bugline-repro` and `bugline-fixer` to take their roles and say hello.
   Wait for both replies.

To try the template without touching the real names, run it with **team** `bltest`, then archive
the room and delete the two `bltest-` agents.

The template's comments list what it cannot do. Two things to check after the run
**(unverified)**: that `!list-aliases` in `bugline-eng` shows `frontdesk` (the alias key uses a
parameter), and that the room got the `bugline-repo` reference. Step 10 sets both again if not.

### 8b. Without the template

1. In Slack, create the public channel `bugline-eng` and run `/invite @<your Switch app name>` in
   it. The room appears in Console **(unverified)**.
2. Create the two agents: Switch Console → **Your Agents** → the dashed **+** card. Name
   `bugline-repro` / `bugline-fixer`, a one-line description, **Run location** This computer,
   **Directory** `C:\bugline-agents\<name>` (it cannot be changed later), the signed-in provider,
   default advanced settings, **Who can talk to your agent** left at **Me and my agents**. Select
   **Add agent**.
3. In `#bugline-eng`:

   ```
   !invite-agent @bugline-frontdesk
   !invite-agent @bugline-repro
   !invite-agent @bugline-fixer
   ```

4. Gateway → the room's page → **Add role**, twice: `reproducer` (shared) and `fixer`
   (exclusive). Copy each role's instructions from the `roles:` section of
   `switch/bugline.template.yaml`.
5. Ask each agent to take its role:
   `@bugline-repro take the reproducer role in this room.` and
   `@bugline-fixer take the fixer role in this room.`

## 9. Briefs, the fixer's access rule, and `gh`

1. Switch Console → **Your Agents** → `bugline-repro` → **Agent instructions**: paste everything
   below the line in [switch/agent-briefs/reproducer.md](../switch/agent-briefs/reproducer.md).
   Do the same for `bugline-fixer` with
   [switch/agent-briefs/fixer.md](../switch/agent-briefs/fixer.md). This replaces the short
   pointers the template set.
2. `bugline-repro` keeps **Me and my agents**. That admits you (the PM) and `bugline-frontdesk`,
   because you own both.
3. `bugline-fixer` → **Who can talk to your agent** → **Custom rules**, one rule:
   - Rooms: `bugline-eng`
   - Room groups: any
   - People: your own Switch user, named explicitly (not "owner"; see step 13 for why)
   - Agents: none

   Anyone not named is refused, and nothing warns you about who you left out. Your Slack account
   must be linked (step 3.6), or you are refused too **(unverified: the exact field names on the
   rule form)**.
4. The fixer opens PRs with your GitHub login. In a terminal as the same Windows user:

   ```powershell
   gh auth login
   gh auth status
   git config --global user.name
   git config --global user.email
   ```

   Switch Console agents inherit your `gh` login. Check the git name and email are yours; the
   fixer commits with them.

## 10. Links, room instructions and aliases: `scripts/setup_rooms.py`

The template cannot link to the Telegram room, so this script makes the two links and sets the
rest that can be set without taking a room away from the running front desk. It acts as the front
desk, with the id and key from step 5. Every call is listed in the script's docstring
**(unverified: not yet run against a live server)**.

PowerShell:

```powershell
Copy-Item scripts\.env.example scripts\.env   # optional: it falls back to agents/frontdesk/.env and the saved credentials
py -3.14 scripts\setup_rooms.py --dry-run
py -3.14 scripts\setup_rooms.py
```

Bash:

```bash
cp scripts/.env.example scripts/.env
python3.14 scripts/setup_rooms.py --dry-run
python3.14 scripts/setup_rooms.py
```

It prints each step. Re-running it is safe. If it stops at "rooms match", the front desk is not in
that room yet (step 7 or 8), or the room has another name: put the room id in `scripts/.env`.

If the script cannot run, do the same by hand: Gateway → each room's page → **Add linked room**:
`bugline-support` → `bugline-eng` labelled `escalates to`, and `bugline-eng` → `bugline-support`
labelled `supports`. Paste `switch/room-instructions-support.md` and
`switch/room-instructions-eng.md` into each room's instructions, and run
`!set-alias @bugline-frontdesk @frontdesk` in `#bugline-eng`.

A link tells agents the other room exists. It does not let anyone into it.

## 11. Shared documents and the `bugline-kit` package

Packages hold only library documents and references, and only a person can make them, in the
Gateway **(unverified: exact menu names)**.

1. Gateway → **Resources** → documents: create three library documents. Name each after its file
   and paste the file's text as the content:
   - `intake-rules.md` from `switch/docs/intake-rules.md`
   - `repro-checklist.md` from `switch/docs/repro-checklist.md`
   - `fix-policy.md` from `switch/docs/fix-policy.md`
2. Create the package `bugline-kit` with the three documents and the `bugline-repo` reference.
3. Attach `bugline-kit` to `bugline-eng` and `bugline-support` from each room's page.

The files in `switch/docs/` are the source. When one changes, paste it into its library document
again. The front desk reads `intake-rules.md` from the repo, not from Switch.

## 12. Start the front desk and quiet the rooms

1. Start the front desk (details in [agents/frontdesk/README.md](../agents/frontdesk/README.md)):

   ```powershell
   cd agents\frontdesk
   .\.venv\Scripts\Activate.ps1
   python agent.py
   ```

   ```bash
   cd agents/frontdesk && source .venv/bin/activate && python agent.py
   ```

2. In both rooms, so agents act only when named:

   ```
   !follow-ups off
   ```

3. Check, in `#bugline-eng`:
   - `!roles`: `reproducer` (shared) held by `bugline-repro`, `fixer` (exclusive) held by
     `bugline-fixer`.
   - `!list-aliases`: `frontdesk` → `bugline-frontdesk`. Same in `bugline-support`.
   - `!list-agents`: all three agents.
   - `!list-references` and `!list-documents`: `bugline-repo` and the three documents.
4. In the Gateway, each room's page lists its link with the right label.

## 13. The refusal test

From the second Slack account, in `#bugline-eng`:

```
@fixer fix BL-1 now
```

Switch, not the fixer, posts the refusal in the fixer's name. The fixer's code does nothing. The
wording depends on the sender's account **(unverified: test once before recording)**:

- Second account linked to a different Switch user, or a rule that names your user explicitly:
  "You're not permitted to direct messages to me in this room — my operator has restricted who
  can address me here."
- Second account not linked, and a rule that uses "owner": "I only take instructions from my
  owner, and this chat account isn't linked to a Switch user yet ...". This one is said only once;
  later messages from that account get no reply at all.

For the video you want the first message, so name your user explicitly in the rule (step 9.3).
If `@fixer` gets no reply at all, the role has no live holder (step 14); use `@bugline-fixer`
instead, which is refused the same way.

## 14. When a role mention reaches nobody

`@reproducer` and `@fixer` reach an agent only while a running session holds the role. When the
session ends (idle, `!reset`, the machine restarts), the role is released, `!roles` shows it free,
and a role mention goes nowhere with no error. That includes the `@reproducer` line in the front
desk's tickets.

Workaround:

1. Before every demo run, `!roles` in `#bugline-eng`. If a role is free, wake the agent and ask
   again: `@bugline-repro take the reproducer role in this room.` /
   `@bugline-fixer take the fixer role in this room.` Then `!roles` again.
2. During a run, if a role mention gets no reply within a minute, address the agent by name in the
   same thread: `@bugline-repro please reproduce BL-1.` or
   `@bugline-fixer go on BL-1, keep it to the share handler, add a regression test`.
3. Find out how long a role lasts: take it, wait ten minutes, run `!roles`
   **(unverified: the session lifetime of a Console-managed agent is not documented)**.

## 15. Smoke run: the six seeded paths

The paths are the seeded-faults table in [CLAUDE.md](../CLAUDE.md#demo-app-expense-splitter-demo-app).
Run them in this order, because path 5 needs `BL-1` open. "User A" and "user B" are your two
Telegram accounts in `bugline-support`; "PM" is you in `#bugline-eng`. Keep
`agents/frontdesk/calls.log` open to count model calls.

**Path 4: vague report.** User A:

```
@frontdesk the app is broken
```

Expect: the front desk asks once for the missing details (steps, what you expected, what
happened, the group). No ticket. Nothing in `#bugline-eng`.

**Path 1: share link error, the full loop.** User A, in a new message:

```
@frontdesk I opened the share link /share/goa-trip-share for group 1 and got "Internal Server Error". I expected the summary of who paid what.
```

Expect: user A is told the ticket id `BL-1`. In `#bugline-eng` the ticket appears in the shape in
`switch/docs/intake-rules.md`, ending with `@reproducer`. The reproducer replies in that thread
with `Verdict: reproduced` and a cause in `demo-app/app/main.py`, `share()`.

**Path 5: duplicate.** While `BL-1` is open, user B:

```
@frontdesk the share link for group 1 is broken for me too, it says Internal Server Error instead of the summary
```

Expect: user B is told it is already tracked as `BL-1`. Nothing new in `#bugline-eng`.

**Refusal.** Do step 13 now.

**Approve and close.** PM, in the `BL-1` thread:

```
@fixer go on BL-1, keep it to the share handler, add a regression test
```

Expect: the fixer names its branch `fix/demo-app-bl-1-...`, runs `pytest -q`, opens a PR titled
`BL-1: ...` and posts `@frontdesk BL-1 is fixed: https://github.com/Ishaan2053/bugline/pull/<n>`.
In `bugline-support`, the front desk tells user A and user B that `BL-1` is fixed, with the link.
Do not merge the PR until the run is recorded.

**Path 2: totals off by a paisa.** User A:

```
@frontdesk in group 1 the balances don't add up. Total spent is 9100 but the three "owes" amounts add to 9099.99. I expected them to add up to the total.
```

Expect: `BL-2` in `#bugline-eng`; the reproducer shows the exact numbers from
`GET /groups/1/balances` and names the rounding in `demo-app/app/money.py`. Approving a fix is
optional.

**Path 3: not a bug.** User A:

```
@frontdesk it says I owe money I already paid. Why?
```

Expect: an answer from the user guide in `demo-app/README.md` (the expense has the wrong payer, and
how to correct it). Nothing in `#bugline-eng`.

**Path 6: off-topic.** User B:

```
@frontdesk can you recommend a good pizza place in Goa?
```

Expect: one polite line. A follow-up from user B in the same thread gets no reply.

**Could not reproduce.** PM, in `#bugline-eng`:

```
@bugline-repro please reproduce: GET /groups/1/settle returns 500 for group 1
```

Expect: `Verdict: not reproduced`, with what it tried, and no cause offered.

After the run, note the model-call count from `calls.log` and the wall time in
`docs/build-journal.md`.
