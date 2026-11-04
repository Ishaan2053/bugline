"""Settings for the front desk agent: every constant and environment variable lives here.

Other modules import this file and read `config.NAME` at call time, so there is exactly one place
to change a model name, a limit or a path, and tests can point paths at temporary files.
"""

import os
import re
from pathlib import Path

# Shared with the coder agents. Re-exported so the front desk keeps reading them as config.NAME.
from common.conventions import (  # noqa: F401
    REPLY_MAX_LINES,
    TICKET_ID_RE,
    TICKET_PREFIX,
    format_ticket_id,
)
from common.env import load_env_file, require_env

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent.parent


def _path_from_env(var: str, default: Path) -> Path:
    """Path from env var `var`, or `default`. A relative value is taken from the agent dir."""
    value = os.environ.get(var)
    return AGENT_DIR / value if value else default


load_env_file(AGENT_DIR / ".env")


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


def gemini_api_key() -> str:
    """The Google AI Studio key."""
    return require_env(GEMINI_KEY_ENV)


# --- Tickets and rate guards (CLAUDE.md section 2) ----------------------------------------------
MAX_OPEN_TICKETS = 5  # per reporter
REPLIES_PER_MINUTE = 3  # model-backed replies per user
REPLY_WINDOW_S = 60.0

# A close message in the eng room carries a ticket id (TICKET_ID_RE) and a GitHub PR link.
# Group 1 is the PR number, which the status board shows as "PR #n".
PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/(\d+)")

# "@frontdesk status" in the eng room lists tickets; "status BL-n" shows one.
STATUS_COMMAND = "status"
# One line per ticket plus a "+n more" line keeps the board under REPLY_MAX_LINES.
STATUS_MAX_ROWS = REPLY_MAX_LINES - 2


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
# The chat app each room is on, as Switch names its connection types ("bridge_type"). Only
# scripts/bootstrap.py reads it, to pick the connection; its flags override these.
BRIDGE_TYPES = {
    ROOM_SUPPORT: os.environ.get("BUGLINE_SUPPORT_BRIDGE", "telegram"),
    ROOM_ENG: os.environ.get("BUGLINE_ENG_BRIDGE", "slack"),
}

REPRODUCER_ROLE = "reproducer"
# Optional agent name targeted alongside the role. A role mention reaches an agent only while its
# session holds the role; a name reaches it either way.
REPRODUCER_NAME = os.environ.get("FRONTDESK_REPRODUCER_NAME", "")
# send_targeted_message statuses that mean the target will see the message.
REACHABLE_STATUSES = frozenset({"live", "awaiting_manual_poll"})


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
