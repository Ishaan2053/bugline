"""Every text the front desk posts, in one place.

The switch/ briefs and room instructions quote these formats (the escalation and the close), so
change them here and there together.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from classify import Report
from config import (
    MAX_OPEN_TICKETS,
    PR_URL_RE,
    REPRODUCER_ROLE,
    ROOM_NAMES,
    ROOM_SUPPORT,
    STATUS_COMMAND,
    TICKET_PREFIX,
)
from store import Subscriber, Ticket

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
RATE_LIMITED = "I'm rate-limited right now. Please send that again in a minute."
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
    f" ({TICKET_PREFIX}-n) and the PR link. `{STATUS_COMMAND}` lists the tickets,"
    f" `{STATUS_COMMAND} {TICKET_PREFIX}-n` shows one."
)
NO_TICKETS = "No tickets yet."
UNKNOWN_TICKET = "There is no ticket {ticket_id}."
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
            *_report_lines(report),
            f"@{REPRODUCER_ROLE} please reproduce and post your verdict in this thread.",
        ]
    )


def status_board(
    tickets: Sequence[Ticket], counts: Mapping[str, int], now: datetime, total: int
) -> str:
    """The eng room's ticket board: one line per ticket as given, then `+n more` if cut.

    `counts` is each ticket's subscriber count (the reporter included); `total` is how many
    tickets exist, so the last line can say how many were left out.
    """
    if not tickets:
        return NO_TICKETS
    lines = []
    for ticket in tickets:
        others = counts.get(ticket.ticket_id, 1) - 1
        who = ticket.reporter_name + (f" (+{others})" if others > 0 else "")
        what = _closed_note(ticket) if ticket.status == "closed" else _one_line(ticket.title)
        lines.append(" · ".join([ticket.ticket_id, ticket.status, _age(ticket, now), who, what]))
    if total > len(tickets):
        lines.append(f"+{total - len(tickets)} more")
    return "\n".join(lines)


def status_one(ticket: Ticket, subscribers: Sequence[Subscriber], now: datetime) -> str:
    """One ticket in full: state, who is waiting on it, the report, and when it opened/closed."""
    if ticket.status == "closed":
        by = f" by {ticket.closed_by}" if ticket.closed_by else ""
        state = f"closed after {_age(ticket, now)}{by}: {ticket.pr_url}"
    else:
        state = f"open for {_age(ticket, now)}"
    names = [
        (s.name or s.user_id) + (" (reporter)" if s.user_id == ticket.reporter_id else "")
        for s in subscribers
    ]
    times = f"Opened {_clock(ticket.created_at)}"
    if ticket.closed_at:
        times += f", closed {_clock(ticket.closed_at)}"
    return "\n".join(
        [
            f"{ticket.ticket_id}: {_one_line(ticket.title)}",
            f"Status: {state}",
            f"Subscribers: {', '.join(names)}",
            *_report_lines(Report(**ticket.report)),
            times,
        ]
    )


def _report_lines(report: Report) -> list[str]:
    """The report fields the escalation and the single-ticket status both show."""
    return [
        f"Group: {_one_line(report.group_id)}",
        f"Steps: {_one_line(report.steps)}",
        f"Expected: {_one_line(report.expected)}",
        f"Actual: {_one_line(report.actual)}",
    ]


def _closed_note(ticket: Ticket) -> str:
    """`PR #18`, plus `closed by <who>` when the store knows who closed it."""
    pr = PR_URL_RE.search(ticket.pr_url or "")
    note = f"PR #{pr.group(1)}" if pr else str(ticket.pr_url)
    return note + (f", closed by {ticket.closed_by}" if ticket.closed_by else "")


def _age(ticket: Ticket, now: datetime) -> str:
    """How long the ticket was open: until it closed, or until `now` while it is open."""
    end = datetime.fromisoformat(ticket.closed_at) if ticket.closed_at else now
    minutes = int((end - datetime.fromisoformat(ticket.created_at)).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    return f"{hours} h" if hours < 48 else f"{hours // 24} d"


def _clock(iso: str) -> str:
    """A stored timestamp as `2026-11-04 10:12 UTC`."""
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")


def _one_line(text: str) -> str:
    """Join a multi-line field with "; " so each field stays on its own line."""
    return "; ".join(line.strip() for line in text.splitlines() if line.strip())
