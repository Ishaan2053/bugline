"""Settings for the front desk agent: every constant and environment variable lives here.

Other modules import this file and read `config.NAME` at call time, so there is exactly one place
to change a model name, a limit or a path, and tests can point paths at temporary files.
"""

import os
import re
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent.parent


def _path_from_env(var: str, default: Path) -> Path:
    """Path from env var `var`, or `default`. A relative value is taken from the agent dir."""
    value = os.environ.get(var)
    return AGENT_DIR / value if value else default


def _load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from `path` into the environment, for runs outside Docker.

    Variables that are already set win, so the shell and Docker's env_file override the file.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env_file(AGENT_DIR / ".env")


def require_env(name: str) -> str:
    """Value of env var `name`. Raises if it is not set, so the failure is obvious at start."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; see agents/frontdesk/.env.example")
    return value


# --- Gemini (CLAUDE.md section 6) ---------------------------------------------------------------
GEMINI_KEY_ENV = "GEMINI_API_KEY"
MODEL_DEFAULT = "gemini-2.5-flash"  # answers to user questions
# Classification and duplicate check. CLAUDE.md names gemini-2.5-flash-lite, but on Nov 4 2026 the
# API refused it ("no longer available to new users") and named this model as the replacement.
MODEL_LITE = "gemini-3.5-flash-lite"
DUPLICATE_MIN_CONFIDENCE = 0.7  # below this a duplicate match counts as no match
BACKOFF_START_S = 2.0  # first wait after an HTTP 429, doubled on each retry
BACKOFF_CAP_S = 30.0
BACKOFF_TRIES = 5  # total attempts, including the first
REPLY_MAX_LINES = 10


def gemini_api_key() -> str:
    """The Google AI Studio key."""
    return require_env(GEMINI_KEY_ENV)


# --- Tickets and rate guards (CLAUDE.md section 2) ----------------------------------------------
TICKET_PREFIX = "BL"
MAX_OPEN_TICKETS = 5  # per reporter
REPLIES_PER_MINUTE = 3  # model-backed replies per user
REPLY_WINDOW_S = 60.0


def format_ticket_id(n: int) -> str:
    """Ticket number to its public id: 1 -> "BL-1"."""
    return f"{TICKET_PREFIX}-{n}"


# A close message in the eng room carries a ticket id and a GitHub PR link.
TICKET_ID_RE = re.compile(rf"\b{TICKET_PREFIX}-(\d+)\b")
PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/\d+")


# --- Switch (CLAUDE.md section 5) ---------------------------------------------------------------
AGENT_NAME = "bugline-frontdesk"
AGENT_DESCRIPTION = (
    "Bugline front desk: takes reports in the support chat, hands complete bugs to engineering"
    " and tells the reporter when they are fixed."
)
SWITCH_API_URL_ENV = "SWITCH_API_URL"  # the bridge ("API URL"), not the Gateway web page
REGISTRATION_KEY_ENV = "SWITCH_REGISTRATION_KEY"

# Room keys used in the code, the Switch room each one is, and the env var with its room id.
ROOM_SUPPORT = "support"
ROOM_ENG = "eng"
ROOM_NAMES = {ROOM_SUPPORT: "bugline-support", ROOM_ENG: "bugline-eng"}
ROOM_ID_ENVS = {ROOM_SUPPORT: "SWITCH_SUPPORT_ROOM_ID", ROOM_ENG: "SWITCH_ENG_ROOM_ID"}

REPRODUCER_ROLE = "reproducer"
# Optional agent name targeted alongside the role. A role mention reaches an agent only while its
# session holds the role; a name reaches it either way.
REPRODUCER_NAME = os.environ.get("FRONTDESK_REPRODUCER_NAME", "")
# send_targeted_message statuses that mean the target will see the message.
REACHABLE_STATUSES = frozenset({"live", "awaiting_manual_poll"})

RECONNECT_START_S = 1.0  # WebSocket reconnect backoff, doubled up to the cap
RECONNECT_CAP_S = 30.0
HTTP_TIMEOUT_S = 30.0


def switch_api_url() -> str:
    return require_env(SWITCH_API_URL_ENV).rstrip("/")


def room_ids() -> dict[str, str]:
    """Room key -> Switch room id, from the environment."""
    return {key: require_env(env) for key, env in ROOM_ID_ENVS.items()}


# --- Files --------------------------------------------------------------------------------------
STATE_DIR = _path_from_env("FRONTDESK_STATE_DIR", AGENT_DIR / "state")
DB_PATH = _path_from_env("FRONTDESK_DB", STATE_DIR / "frontdesk.db")
CREDENTIALS_PATH = STATE_DIR / "credentials.json"  # agent id + API key, written once by --register
CONNECTIONS_PATH = STATE_DIR / "connections.json"  # one stable connection id per room
CALLS_LOG_PATH = _path_from_env("FRONTDESK_CALLS_LOG", AGENT_DIR / "calls.log")
PROMPTS_DIR = AGENT_DIR / "prompts"

# Reference docs the model reads. They are written once, in the repo, and inserted into the
# prompts at runtime so the rules are never restated in a prompt.
INTAKE_RULES_PATH = _path_from_env(
    "FRONTDESK_INTAKE_RULES", REPO_ROOT / "switch" / "docs" / "intake-rules.md"
)
USER_FAQ_PATH = _path_from_env("FRONTDESK_USER_FAQ", REPO_ROOT / "demo-app" / "README.md")
