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
5. Two answers hand work on, and go out with `send_targeted_message` so Switch says whether
   anyone will see them. The fixer's `please verify BL-n on PR <url>` goes to the `reproducer`
   role; the reproducer's `Verified BL-n: <url>` or `Not verified BL-n: <why>` goes to the front
   desk by name (`FRONTDESK_AGENT_NAME`). If no live agent gets it, one line in the thread says
   so. The patterns are in `../common/conventions.py`.

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
| `SWITCH_REGISTRATION_KEY` | needed for `--register` | Registration key; bootstrap registers without it |
| `SWITCH_ENG_ROOM_ID` | required | Room id of `bugline-eng` |
| `FRONTDESK_AGENT_NAME` | none; bootstrap writes it | Where the reproducer sends its verdict. Unset: the verdict is posted plainly and reaches the front desk through `@frontdesk` |
| `CODER_ROLE` | required | `reproducer` or `fixer`; set it per shell |
| `CODER_AGENT_NAME` | `[agents]` in `bugline.toml` (`bugline-repro` / `bugline-fixer`) | Switch agent name |
| `CODER_BRIEF` | `switch/agent-briefs/<role>.md` | Brief. At start it is filled with the names in `bugline.toml`, followed by the role's documents from `switch/docs/`, and written to `state/<agent name>/brief.md`, which every run reads |
| `CODER_WORKDIR` | `C:\bugline-agents\<agent name>`; `~/bugline-agents/<agent name>` off Windows | Holds the clone (`clone_dir` in `bugline.toml`, `bugline` by default), where Claude Code runs |
| `CODER_CLAUDE_BIN` | `claude` | Path to the Claude Code CLI |
| `CODER_TIMEOUT_S` | `1800` | Seconds before a run is stopped |
| `CODER_STATE_DIR` | `state` | Holds `<agent name>/credentials.json` and `connections.json` |

## Set up once

1. Sign in to Claude Code (`claude`), GitHub CLI (`gh auth login`) and git on this machine. The
   agents use these logins, so they run natively, not in Docker.
2. Clone the repo into each working directory and make the demo app's venv with Python 3.14.
   If `py -3.14` does not resolve, use the full path to a 3.14 `python.exe`.
3. From the repo root, run `scripts/bootstrap.py`
   ([docs/switch-setup.md part B](../../docs/switch-setup.md#part-b-scriptsbootstrappy)). It
   registers both agents (credentials go to `state/<agent name>/credentials.json`), writes
   `SWITCH_API_URL`, `SWITCH_ENG_ROOM_ID` and `FRONTDESK_AGENT_NAME` into `.env`, puts both agents in `bugline-eng` with
   its roles, and sets the access rules: the reproducer its owner and the owner's agents, the
   fixer its owner only, in `bugline-eng` only.

Without bootstrap: copy `.env.example` to `.env`, fill in the three `SWITCH_` values, run
`--register` once per role, then add the agents, roles and access rules by hand.

PowerShell, from `agents/coder/`:

```powershell
git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-repro\bugline
git clone https://github.com/Ishaan2053/bugline.git C:\bugline-agents\bugline-fixer\bugline
# in each clone's demo-app\: py -3.14 -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt

py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python ..\..\scripts\bootstrap.py   # or, without it: $env:CODER_ROLE = "reproducer"; python agent.py --register (and "fixer")
```

Run each agent in its own terminal:

```powershell
$env:CODER_ROLE = "reproducer"; python agent.py
$env:CODER_ROLE = "fixer"; python agent.py
```

Bash:

```bash
git clone https://github.com/Ishaan2053/bugline.git ~/bugline-agents/bugline-repro/bugline
git clone https://github.com/Ishaan2053/bugline.git ~/bugline-agents/bugline-fixer/bugline
# in each clone's demo-app/: python3.14 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python ../../scripts/bootstrap.py   # or CODER_ROLE=reproducer|fixer python agent.py --register
CODER_ROLE=reproducer python agent.py   # one terminal
CODER_ROLE=fixer python agent.py        # another
```

At start the agent logs the full `claude` command line it will run.

## What Claude Code may do

Each run is:

```
claude -p --output-format json --no-session-persistence
  --append-system-prompt-file state/<agent name>/brief.md
  --setting-sources local --settings {"attribution": {"commit": "", "pr": ""}}
  --permission-mode dontAsk --tools Read,Glob,Grep,Edit,Write,Bash
  --allowedTools <the role's list> --disallowedTools <the deny list>
```

with the prompt on stdin, in `<workdir>\bugline`. The lists are in `config.py`.

- `--permission-mode dontAsk`: anything not on the allow list is refused at once. Nobody is there
  to answer a prompt, and a run never hangs waiting for one.
- `--setting-sources local` leaves out the operator's own `~/.claude/settings.json`, so their
  personal allow rules do not widen the agent's. Without it, a test run of the reproducer could run
  `git push`, because the author's user settings allow it. It also leaves out the clone's
  `CLAUDE.md`, which is written for the repo's developers; this repo's said "stop and ask before
  overwriting a branch", which a verify run does. A probe confirmed both: with `project,local` the
  run had this repo's CLAUDE.md in context, with `local` it did not.
- Path rules are written relative to the repo root in `config.py` and passed as absolute paths
  under the clone (`Edit(//c/bugline-agents/bugline-repro/bugline/demo-app/scratch/**)`). Claude
  Code reads a relative rule against the shell's current directory, so after `cd demo-app` the
  reproducer could not write its scratch script, and the fixer's `seed.py` rule did not match.
  An `Edit` rule also covers the Write tool.
- `--tools` hides the tools neither agent needs (web, PowerShell, subagents).
- Both roles may run any shell command in the clone. Claude Code chains commands
  (`cd demo-app && ... | tail -3; mkdir -p scratch`), and in `dontAsk` mode every part of a chain
  must be allowed. A list of single commands refused nearly every real step in the first live
  run, so the deny lists below keep each agent in its lane instead.
- The reproducer may write only under `scratch_dir` (`demo-app/scratch/` by default), and is
  refused `git commit`, `git push`, `git merge`, `git rebase` and every `gh` command. The fixer
  may edit the clone.
- Denied for both: force-push, pushing `default_branch` (`main`), deleting branches,
  `git reset --hard`, `gh pr merge`, and editing `protected_paths` (`seed.py` and any `.db` file
  by default). The paths and the branch come from `bugline.toml`.
- No AI attribution is added to commits or PR bodies (`--settings`), as `fix-policy.md` asks.

These rules narrow what Claude Code does by mistake. They are not a sandbox: `python` can run any
code, so the briefs and the PM's review of every PR still matter.

Claude Code runs inside the clone, so the repo root is its starting directory.

## Tests

```powershell
pytest -q
ruff format --check .
ruff check .
```

The tests use a short Python script in place of `claude` and a mock bridge in place of Switch.
