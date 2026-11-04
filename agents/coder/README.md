# Bugline coder agents: `bugline-repro` and `bugline-fixer`

One small Python program that runs as either coding agent. Like the [front desk](../frontdesk/README.md),
each one is a custom agent on the Switch agent protocol. It sits in `bugline-eng` and runs
Claude Code headless (`claude -p`) in its own clone to do the work.

## Why not Console-managed agents

The plan was to let Switch Console run the reproducer and the fixer. Console 0.40.1 on Windows
refuses to run coding agents locally. Its code says:

```
if (process.platform === "win32") ... "SDK sessions require a POSIX SSH execution host."
```

So each agent registers itself over the protocol, the way the front desk does, and starts Claude
Code for each message.

## What happens to a message

1. On every connect, the agent takes its role in `bugline-eng` (`assume_role`). Switch posts its
   own notice the first time.
2. A message addressed to the agent (by name, alias or role) is queued. If a job is running, the
   agent answers "Busy with BL-n, queued." in the message's thread.
3. For each job, it posts "Working on it..." in the thread, reads the thread's earlier messages
   (`read_context`), and runs Claude Code with the brief as the system prompt. The prompt holds the
   message, the sender's name and the thread so far.
4. Claude Code's final message is posted in the thread, cut to 10 lines. A failure or timeout
   posts one line, and the agent goes on to the next job.

Who may address each agent is set by its access rule in Switch, before the message reaches the
program. The brief is the second line of defence. The code adds no third one.

| File | What it does |
| --- | --- |
| `agent.py` | Registration, the eng room connection, the job queue, the posts |
| `claude_runner.py` | The `claude` command line, running it with a timeout, trimming the answer |
| `config.py` | The two roles, their briefs, working directories and Claude Code permissions |
| `../common/` | The Switch client and ticket id format, shared with the front desk |

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `SWITCH_API_URL` | required | The bridge URL, the same as the front desk's |
| `SWITCH_REGISTRATION_KEY` | needed for `--register` | Gateway registration key |
| `SWITCH_ENG_ROOM_ID` | required | Room id of `bugline-eng` |
| `CODER_ROLE` | required | `reproducer` or `fixer`; set it per shell |
| `CODER_AGENT_NAME` | `bugline-repro` / `bugline-fixer` | Switch agent name |
| `CODER_BRIEF` | `switch/agent-briefs/<role>.md` | Brief, read at every run |
| `CODER_WORKDIR` | `C:\bugline-agents\<agent name>` | Holds the clone `bugline\`, where Claude Code runs |
| `CODER_CLAUDE_BIN` | `claude` | Path to the Claude Code CLI |
| `CODER_TIMEOUT_S` | `1800` | Seconds before a run is stopped |
| `CODER_STATE_DIR` | `state` | Holds `<agent name>/credentials.json` and `connections.json` |

## Set up once

1. Sign in to Claude Code (`claude`), GitHub CLI (`gh auth login`) and git on this machine. The
   agents use these logins, so they run natively, not in Docker.
2. Clone the repo into each working directory and make the demo app's venv with Python 3.14.
   If `py -3.14` does not resolve, use the full path to a 3.14 `python.exe`.
3. Copy `.env.example` to `.env` and fill in the three `SWITCH_` values.
4. Register each agent once. Credentials go to `state/<agent name>/credentials.json`.
5. In Switch, invite both agents to `bugline-eng`, add the roles, and set the fixer's access rule
   (PM only, in `bugline-eng` only). [docs/switch-setup.md](../../docs/switch-setup.md) has the
   steps.

PowerShell, from `agents/coder/`:

```powershell
git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-repro\bugline
git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-fixer\bugline
# in each clone's demo-app\: py -3.14 -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt

py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:CODER_ROLE = "reproducer"; python agent.py --register
$env:CODER_ROLE = "fixer"; python agent.py --register
```

Run each agent in its own terminal:

```powershell
$env:CODER_ROLE = "reproducer"; python agent.py
$env:CODER_ROLE = "fixer"; python agent.py
```

Bash:

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
CODER_ROLE=reproducer python agent.py --register
CODER_ROLE=fixer python agent.py --register
CODER_ROLE=reproducer python agent.py   # one terminal
CODER_ROLE=fixer python agent.py        # another
```

At start the agent logs the full `claude` command line it will run.

## What Claude Code may do

Each run is:

```
claude -p --output-format json --no-session-persistence
  --append-system-prompt-file <brief>
  --setting-sources project,local --settings {"attribution": {"commit": "", "pr": ""}}
  --permission-mode dontAsk --tools Read,Glob,Grep,Edit,Write,Bash
  --allowedTools <the role's list> --disallowedTools <the deny list>
```

with the prompt on stdin, in `<workdir>\bugline`. The lists are in `config.py`.

- `--permission-mode dontAsk`: anything not on the allow list is refused at once. Nobody is there
  to answer a prompt, and a run never hangs waiting for one.
- `--setting-sources project,local` leaves out the operator's own `~/.claude/settings.json`, so
  their personal allow rules do not widen the agent's. Without it, a test run of the reproducer
  could run `git push`, because the author's user settings allow it.
- `--tools` hides the tools neither agent needs (web, PowerShell, subagents).
- Both roles may read the clone, `git pull`/`checkout`/`status`/`log`/`diff`, and run `python`,
  `pip install`, `pytest`, `curl` and the venv's scripts. The reproducer may write only under
  `demo-app/scratch/`. The fixer may edit the clone, `git switch`/`branch`/`add`/`commit`/`push`,
  run `ruff`, and `gh pr create`/`view`.
- Denied for both: force-push, pushing `main`, deleting branches, `git reset --hard`,
  `gh pr merge`, and editing `seed.py` or any `.db` file.
- No AI attribution is added to commits or PR bodies (`--settings`), as `fix-policy.md` asks.

These rules narrow what Claude Code does by mistake. They are not a sandbox: `python` can run any
code, so the briefs and the PM's review of every PR still matter.

Claude Code runs inside the clone rather than the working directory because it refuses
`cd <dir> && git ...` without asking, which `dontAsk` turns into a refusal.

## Tests

```powershell
pytest -q
ruff format --check .
ruff check .
```

The tests use a short Python script in place of `claude` and a mock bridge in place of Switch.
