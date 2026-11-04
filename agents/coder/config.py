"""Settings for the coder agent, one program that runs as `bugline-repro` or `bugline-fixer`.

`CODER_ROLE` picks the role. The agent name, brief and working directory default from the role
and can each be overridden by an environment variable. What Claude Code may do in each role (its
tool permissions) is defined here too, so the README and the code describe the same thing.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from common.conventions import FIXER_ROLE, REPRODUCER_ROLE
from common.env import load_env_file, require_env

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent.parent

load_env_file(AGENT_DIR / ".env")


def _path(var: str, default: Path) -> Path:
    """Path from env var `var`, or `default`. A relative value is taken from agents/coder/."""
    value = os.environ.get(var)
    return AGENT_DIR / value if value else default


def default_workdir(agent_name: str) -> Path:
    """Where an agent works when CODER_WORKDIR is not set.

    C:\\bugline-agents\\<agent> on Windows, ~/bugline-agents/<agent> everywhere else.
    """
    if sys.platform == "win32":
        return Path(r"C:\bugline-agents") / agent_name
    return Path.home() / "bugline-agents" / agent_name


# state/<agent name>/ holds that agent's credentials and connection id.
STATE_ROOT = _path("CODER_STATE_DIR", AGENT_DIR / "state")

SWITCH_API_URL_ENV = "SWITCH_API_URL"  # the bridge ("API URL"), not the Gateway web page
REGISTRATION_KEY_ENV = "SWITCH_REGISTRATION_KEY"
ENG_ROOM_ID_ENV = "SWITCH_ENG_ROOM_ID"
ENG_ROOM = "eng"  # the room key the connection id is saved under
# The front desk's agent name, written by bootstrap. The reproducer sends its verdict to that name;
# without it the verdict is posted plainly and reaches the front desk through its `@frontdesk`
# alias, with no word on whether it is connected.
FRONTDESK_AGENT_NAME_ENV = "FRONTDESK_AGENT_NAME"

DEFAULT_TIMEOUT_S = 1800.0  # one Claude Code run; a fix with a full test run takes minutes
REPLY_MAX_CHARS = 2000  # hard cap on a posted answer, on top of REPLY_MAX_LINES
THREAD_READ_LIMIT = 100  # timeline entries read when looking for the message's thread

# --- Claude Code permissions ----------------------------------------------------------------------
# The tools Claude Code is given at all (--tools). Bash runs python, git and gh; on Windows it is
# Git Bash. Anything not allowed below is refused without a prompt (--permission-mode dontAsk).
TOOLS = ("Read", "Glob", "Grep", "Edit", "Write", "Bash")

# Claude Code runs inside the agent's clone (<workdir>/bugline), so paths below are relative to
# the repo root.
#
# Both roles may run any shell command. Claude Code chains commands (`cd demo-app && ... | tail`)
# and in dontAsk mode every part of a chain must be allowed, so a list of single commands refused
# almost every real step in the first live run. The deny lists below are what keeps each agent in
# its lane; deny rules win over "Bash".
_READ_AND_RUN = ("Read", "Glob", "Grep", "Bash")

# The reproducer writes only scratch scripts (switch/docs/repro-checklist.md).
REPRODUCER_ALLOWED = (
    *_READ_AND_RUN,
    "Edit(demo-app/scratch/**)",
    "Write(demo-app/scratch/**)",
)

# The fixer edits the clone, commits, pushes its branch and opens the PR
# (switch/docs/fix-policy.md).
FIXER_ALLOWED = (*_READ_AND_RUN, "Edit(**)", "Write(**)")

# Passed with --settings. Commits and PRs carry no AI attribution (switch/docs/fix-policy.md).
CLAUDE_SETTINGS = {"attribution": {"commit": "", "pr": ""}}

# The reproducer never changes the repo: no commits, pushes or pull requests.
REPRODUCER_DENIED = (
    "Bash(git commit*)",
    "Bash(git push*)",
    "Bash(git merge*)",
    "Bash(git rebase*)",
    "Bash(gh *)",
)

# Refused for both, even where an allow rule above would match. Deny rules win.
DENIED = (
    "Bash(git push *--force*)",
    "Bash(git push -f*)",
    "Bash(git push * -f*)",
    "Bash(git push * main*)",
    "Bash(git branch -d *)",
    "Bash(git branch -D *)",
    "Bash(git reset --hard*)",
    "Bash(gh pr merge *)",
    "Edit(demo-app/seed.py)",
    "Edit(**/*.db)",
)


@dataclass(frozen=True)
class Role:
    agent_name: str
    description: str
    brief: str  # file name in switch/agent-briefs/
    allowed: tuple[str, ...]
    denied: tuple[str, ...]


ROLES = {
    REPRODUCER_ROLE: Role(
        "bugline-repro",
        "Bugline reproducer: runs Claude Code to reproduce a ticket and posts the verdict.",
        "reproducer.md",
        REPRODUCER_ALLOWED,
        (*REPRODUCER_DENIED, *DENIED),
    ),
    FIXER_ROLE: Role(
        "bugline-fixer",
        "Bugline fixer: runs Claude Code to fix an approved ticket and opens the pull request.",
        "fixer.md",
        FIXER_ALLOWED,
        DENIED,
    ),
}


@dataclass(frozen=True)
class Settings:
    """Everything one coder instance needs except the Switch URL, key and room id."""

    role: str
    agent_name: str
    description: str
    brief: Path
    workdir: Path
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    claude_bin: str = "claude"
    timeout_s: float = DEFAULT_TIMEOUT_S
    frontdesk_name: str = ""  # FRONTDESK_AGENT_NAME; "" when bootstrap has not written it

    @property
    def clone(self) -> Path:
        """The agent's clone of the repo, where Claude Code runs."""
        return self.workdir / "bugline"

    @property
    def state_dir(self) -> Path:
        return STATE_ROOT / self.agent_name

    @property
    def credentials_path(self) -> Path:
        return self.state_dir / "credentials.json"  # agent id + API key, written by --register

    @property
    def connections_path(self) -> Path:
        return self.state_dir / "connections.json"  # the stable connection id


def settings(role_name: str | None = None) -> Settings:
    """The settings for `role_name`, or for the role named in CODER_ROLE.

    scripts/bootstrap.py passes the role to set up both agents from one process.
    """
    role_name = role_name or require_env("CODER_ROLE")
    if role_name not in ROLES:
        raise RuntimeError(f"CODER_ROLE must be one of {sorted(ROLES)}, not {role_name!r}")
    role = ROLES[role_name]
    name = os.environ.get("CODER_AGENT_NAME") or role.agent_name
    return Settings(
        role=role_name,
        agent_name=name,
        description=role.description,
        brief=_path("CODER_BRIEF", REPO_ROOT / "switch" / "agent-briefs" / role.brief),
        workdir=_path("CODER_WORKDIR", default_workdir(name)),
        allowed_tools=role.allowed,
        denied_tools=role.denied,
        claude_bin=os.environ.get("CODER_CLAUDE_BIN") or "claude",
        timeout_s=float(os.environ.get("CODER_TIMEOUT_S") or DEFAULT_TIMEOUT_S),
        frontdesk_name=os.environ.get(FRONTDESK_AGENT_NAME_ENV, ""),
    )


def switch_api_url() -> str:
    return require_env(SWITCH_API_URL_ENV).rstrip("/")


def eng_room_id() -> str:
    return require_env(ENG_ROOM_ID_ENV)
