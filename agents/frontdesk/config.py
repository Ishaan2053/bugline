"""Settings for the front desk agent: every constant and environment variable lives here.

Other modules import this file and read `config.NAME` at call time, so there is exactly one place
to change a model name, a limit or a path, and tests can point paths at temporary files.
"""

import os
import re
from pathlib import Path

# Shared with the coder agents. Re-exported so the front desk keeps reading them as config.NAME.
from common.conventions import (  # noqa: F401
    PR_URL_RE,
    REPLY_MAX_LINES,
    REPRODUCER_ROLE,
    TICKET_ID_RE,
    TICKET_PREFIX,
    VERDICT_RE,
    VERIFIED,
    format_ticket_id,
)
from common.env import load_env_file, require_env
from common.project import load_project

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent.parent
# The project the front desk takes reports for (bugline.toml): names, report fields, user guide.
PROJECT = load_project()


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
# The eng room's language. Reports reach it in this language; a reporter who writes in another
# one gets the front desk's replies translated (one lite-model call per reply).
TEAM_LANGUAGE = "English"
DUPLICATE_MIN_CONFIDENCE = 0.7  # below this a duplicate match counts as no match
# HTTP statuses worth waiting out: 429 is the free-tier quota, 503 is "the model is currently
# experiencing high demand" (seen live on Nov 5). Any other error is raised at once.
RETRY_STATUSES = (429, 503)
BACKOFF_START_S = 2.0  # first wait after a retried status, doubled on each retry
BACKOFF_CAP_S = 30.0
BACKOFF_TRIES = 5  # total attempts, including the first


def gemini_api_key() -> str:
    """The Google AI Studio key."""
    return require_env(GEMINI_KEY_ENV)


# --- Tickets and rate guards (CLAUDE.md section 2) ----------------------------------------------
MAX_OPEN_TICKETS = 5  # per reporter
REPLIES_PER_MINUTE = 3  # model-backed replies per user
REPLY_WINDOW_S = 60.0

# Who may close a ticket (CLAUDE.md section 2): the reproducer, with `Verified BL-n: <PR url>`
# (VERDICT_RE), or the room owner by hand in the same format. The reproducer is known by the agent
# id bootstrap writes here; the front desk looks up its name once at start, because a message's
# sender is a participant id, not an agent id. Without it, only the owner can close.
VERIFIER_AGENT_ID_ENV = "SWITCH_REPRODUCER_AGENT_ID"
# A message's `sender_role` when the sender is the workspace owner (the PM who owns the agents).
OWNER_SENDER_ROLE = "owner"

# "@frontdesk status" in the eng room lists tickets; "status BL-n" shows one.
STATUS_COMMAND = "status"
# "@frontdesk ask BL-n: <question>" in the eng room asks that ticket's reporter in the support room.
ASK_COMMAND = "ask"

# A subscriber's message in the support room that reopens their closed ticket. The "fixed" message
# tells them to reply `still broken`; the other phrases are what people say anyway.
REOPEN_RE = re.compile(
    r"\b(?:reopen|still (?:broken|happening|failing|not working)|not fixed)\b", re.IGNORECASE
)

# "@frontdesk requests" in the eng room lists the feature requests the support room logged.
REQUESTS_COMMAND = "requests"

# One line per ticket (or request) plus a "+n more" line keeps a list under REPLY_MAX_LINES.
STATUS_MAX_ROWS = REPLY_MAX_LINES - 2


# --- Switch (CLAUDE.md section 5) ---------------------------------------------------------------
AGENT_NAME = PROJECT.agents["frontdesk"]
AGENT_DESCRIPTION = (
    "Bugline front desk: takes reports in the support chat, hands complete bugs to engineering"
    " and tells the reporter when they are fixed."
)
SWITCH_API_URL_ENV = "SWITCH_API_URL"  # the bridge ("API URL"), not the Gateway web page
REGISTRATION_KEY_ENV = "SWITCH_REGISTRATION_KEY"

# Room keys used in the code, the Switch room each one is, and the env var with its room id.
ROOM_SUPPORT = "support"
ROOM_ENG = "eng"
ROOM_NAMES = {key: PROJECT.rooms[key] for key in (ROOM_SUPPORT, ROOM_ENG)}
ROOM_ID_ENVS = {ROOM_SUPPORT: "SWITCH_SUPPORT_ROOM_ID", ROOM_ENG: "SWITCH_ENG_ROOM_ID"}
# The chat app each room is on, as Switch names its connection types ("bridge_type"). Only
# scripts/bootstrap.py reads it, to pick the connection. bugline.toml gives the default, these
# env vars override it, and bootstrap's flags override both.
BRIDGE_ENVS = {ROOM_SUPPORT: "BUGLINE_SUPPORT_BRIDGE", ROOM_ENG: "BUGLINE_ENG_BRIDGE"}
BRIDGE_TYPES = {
    key: os.environ.get(env) or PROJECT.bridges[key] for key, env in BRIDGE_ENVS.items()
}

# Optional agent name targeted alongside the role. A role mention reaches an agent only while its
# session holds the role; a name reaches it either way.
REPRODUCER_NAME = os.environ.get("FRONTDESK_REPRODUCER_NAME", "")


def switch_api_url() -> str:
    return require_env(SWITCH_API_URL_ENV).rstrip("/")


def verifier_agent_id() -> str:
    """The reproducer's agent id, or "" when bootstrap has not written it yet."""
    return os.environ.get(VERIFIER_AGENT_ID_ENV, "")


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
USER_FAQ_PATH = _path_from_env("FRONTDESK_USER_FAQ", PROJECT.user_guide_path)
