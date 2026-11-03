"""Settings for the front desk agent: every constant and environment variable lives here.

Other modules import this file and read `config.NAME` at call time, so there is exactly one place
to change a model name, a limit or a path, and tests can point paths at temporary files.
"""

import os
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent.parent


def _path_from_env(var: str, default: Path) -> Path:
    """Path from env var `var`, or `default`. A relative value is taken from the agent dir."""
    value = os.environ.get(var)
    return AGENT_DIR / value if value else default


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
    """The Google AI Studio key. Raises if it is not set, so the failure is obvious at start."""
    key = os.environ.get(GEMINI_KEY_ENV)
    if not key:
        raise RuntimeError(f"{GEMINI_KEY_ENV} is not set; see agents/frontdesk/.env.example")
    return key


# --- Tickets and rate guards (CLAUDE.md section 2) ----------------------------------------------
TICKET_PREFIX = "BL"
MAX_OPEN_TICKETS = 5  # per reporter
REPLIES_PER_MINUTE = 3  # model-backed replies per user
REPLY_WINDOW_S = 60.0


def format_ticket_id(n: int) -> str:
    """Ticket number to its public id: 1 -> "BL-1"."""
    return f"{TICKET_PREFIX}-{n}"


# --- Files --------------------------------------------------------------------------------------
DB_PATH = _path_from_env("FRONTDESK_DB", AGENT_DIR / "state" / "frontdesk.db")
CALLS_LOG_PATH = _path_from_env("FRONTDESK_CALLS_LOG", AGENT_DIR / "calls.log")
PROMPTS_DIR = AGENT_DIR / "prompts"

# Reference docs the model reads. They are written once, in the repo, and inserted into the
# prompts at runtime so the rules are never restated in a prompt.
INTAKE_RULES_PATH = _path_from_env(
    "FRONTDESK_INTAKE_RULES", REPO_ROOT / "switch" / "docs" / "intake-rules.md"
)
USER_FAQ_PATH = _path_from_env("FRONTDESK_USER_FAQ", REPO_ROOT / "demo-app" / "README.md")
