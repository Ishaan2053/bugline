# Bugline front desk

`@frontdesk` is a custom Python agent that speaks the Switch agent protocol. It sits in
`bugline-support` (Telegram), where users report problems, and `bugline-eng` (Slack), where the
team works, and in any other support room `bugline-eng` links back to. It answers questions, asks for missing details, hands complete bugs to `@reproducer`
as ticket `BL-n`, and tells every reporter when the fix lands. The rules it follows are in
[CLAUDE.md section 2](../../CLAUDE.md#2-architecture); the protocol facts are in
[CLAUDE.md section 5](../../CLAUDE.md#5-switch-protocol-facts-for-the-custom-frontdesk) and the
[Switch agent protocol docs](https://docs.switchagents.ai/switch-rooms/internals/agent-protocol).

## Files

| File | What it does |
| --- | --- |
| `agent.py` | Main loop: one connection per room, hands messages to `handlers.py`, posts the replies |
| `../common/` | Code shared with the other custom agents: the Switch client (registration, one WebSocket per room, ops), the ticket id format, `.env` loading |
| `handlers.py` | What to do with one message; returns posts, so it is tested without a socket |
| `messages.py` | Every text the agent posts, including the escalation and close formats |
| `classify.py` | The Gemini calls: classify, duplicate check, answer a question, translate a reply |
| `store.py` | SQLite: tickets, subscribers, drafts, muted threads, rate guards |
| `config.py` | Every setting and environment variable |
| `prompts/` | The four prompt templates, one per Gemini call |

## Set up once

1. Make the venv, copy `.env.example` to `.env`, and fill in `GEMINI_API_KEY`.
2. From the repo root, run `scripts/bootstrap.py`
   ([docs/switch-setup.md part B](../../docs/switch-setup.md#part-b-scriptsbootstrappy)). For the
   front desk it registers the agent (the same call as `python agent.py --register`, which writes
   `state/credentials.json`), opens it to **Anyone** (Telegram users have no Switch account, and
   the agent cannot change this itself), puts it in both rooms with the alias `@frontdesk`, and
   writes `SWITCH_API_URL`, both room ids and `SWITCH_REPRODUCER_AGENT_ID` into `.env`.
3. Start it with `python agent.py`.

Without bootstrap: set `SWITCH_API_URL` and `SWITCH_REGISTRATION_KEY`, run `--register`, have the
owner set the access rule to anyone, add the agent to both rooms, and put the room ids from
`--list-rooms` in `.env`.

PowerShell, from `agents/frontdesk/`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env   # then set GEMINI_API_KEY
python ..\..\scripts\bootstrap.py
python agent.py
```

Bash:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then set GEMINI_API_KEY
python ../../scripts/bootstrap.py
python agent.py
```

With Docker, from the repo root (set `SWITCH_API_URL` to `http://host.docker.internal:<port>`
first). Unverified against Switch Console's native server, which listens on 127.0.0.1 only; the
live run used the native commands above. The `agents` profile keeps a plain `docker compose up`
to the demo app only.

```powershell
docker compose --profile agents run --rm frontdesk python agent.py --register
docker compose --profile agents up --build
```

Credentials and tickets live in the `frontdesk-state` volume in Docker and in `state/` locally.
Register only once: a second registration of the same name is refused (409). If you registered
locally first, copy the credentials into the volume instead:

```powershell
docker compose --profile agents run --rm -v ./agents/frontdesk/state/credentials.json:/seed.json:ro frontdesk cp /seed.json state/credentials.json
```

In Git Bash, prefix that with `MSYS_NO_PATHCONV=1` so `/seed.json` is not rewritten.

## Tests

```powershell
pytest -q
ruff format --check .
ruff check .
```
