"""Every text the front desk posts, in one place.

The switch/ briefs and room instructions quote these formats (the escalation and the close), so
change them here and there together.
"""

from classify import Report
from config import MAX_OPEN_TICKETS, REPRODUCER_ROLE, ROOM_NAMES, ROOM_SUPPORT, TICKET_PREFIX

# What each report field is called when the front desk asks for it.
FIELD_LABELS = {
    "title": "a one-line summary",
    "steps": "the steps you took",
    "expected": "what you expected to happen",
    "actual": "what happened instead",
    "group_id": "your group id",
}

# --- support room ---------------------------------------------------------------------------
TOO_MANY_OPEN = (
    f"You have {MAX_OPEN_TICKETS} reports still open. Let's resolve the open ones first;"
    " I'll tell you here as each one is fixed."
)
COOLDOWN = "Give me a minute, then send that again."
RATE_LIMITED = "I'm rate-limited, trying again shortly."
OFF_TOPIC = "Sorry, that's not something I can help with here."
REQUEST_LOGGED = "Thanks, I've noted that as a request for the team."
TRACKED = "Already tracked as {ticket_id}, I'll tell you when it's fixed."
ESCALATED = (
    "Thanks, logged as {ticket_id} and passed to the team. I'll tell you here when it's fixed."
)
FIXED = "{name}, {ticket_id} is fixed: {pr_url}"

# --- eng room -------------------------------------------------------------------------------
CLOSED = "Closed {ticket_id}, telling the reporter."
NOT_OPEN = "{ticket_id} is not an open ticket, so there is nothing to close."
ENG_HELP = (
    f"I bring bug reports here and close them: mention me with the ticket id"
    f" ({TICKET_PREFIX}-n) and the PR link."
)
NO_REPRODUCER = "Nobody holds the {role} role right now. PM, please start one for {ticket_id}."


def ask_missing(missing: list[str]) -> str:
    """Ask once for exactly the fields a bug report still lacks."""
    labels = [FIELD_LABELS.get(name, name) for name in missing]
    wanted = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
    return f"Thanks. To pass this to the team I need {wanted}. Reply here and mention me."


def escalation(ticket_id: str, report: Report, reporter_name: str) -> str:
    """The structured report posted to the eng room. First line `BL-n: <title>`."""
    return "\n".join(
        [
            f"{ticket_id}: {_one_line(report.title)}",
            f"Reporter: {reporter_name} ({ROOM_NAMES[ROOM_SUPPORT]})",
            f"Group: {_one_line(report.group_id)}",
            f"Steps: {_one_line(report.steps)}",
            f"Expected: {_one_line(report.expected)}",
            f"Actual: {_one_line(report.actual)}",
            f"@{REPRODUCER_ROLE} please reproduce and post your verdict in this thread.",
        ]
    )


def _one_line(text: str) -> str:
    """Join a multi-line field with "; " so each field stays on its own line."""
    return "; ".join(line.strip() for line in text.splitlines() if line.strip())
