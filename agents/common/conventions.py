"""Facts every Bugline agent relies on: ticket ids, role names, and the hand-off lines.

The front desk makes ticket ids and closes tickets; the coder agents read ticket ids to say which
ticket they are busy with, and hand work to each other with the lines below. Both import them from
here, so the fixer's verify request and the reproducer's verdict are parsed the same way by the
agent that sends them and the agent that reads them (switch/docs/fix-policy.md and
switch/docs/repro-checklist.md give the exact wording). The ticket prefix comes from bugline.toml,
so every pattern here follows the configured project.
"""

import re

from common.project import load_project

TICKET_PREFIX = load_project().ticket_prefix  # "BL" in the shipped bugline.toml
# A ticket id anywhere in a message, with its number as group 1.
TICKET_ID_RE = re.compile(rf"\b{TICKET_PREFIX}-(\d+)\b")
# The eng room's rule (switch/room-instructions-eng.md): replies stay under 10 lines.
REPLY_MAX_LINES = 10

# The Switch roles the two coder agents hold in the eng room.
REPRODUCER_ROLE = "reproducer"
FIXER_ROLE = "fixer"

# A GitHub pull request link. Group 1 is the PR number, which the status board shows as "PR #n".
PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/(\d+)")
# Leading "@frontdesk " or "@bugline-frontdesk, " mentions. They only address a message; they are
# not part of what it says.
LEADING_MENTIONS = re.compile(r"^\s*(@[\w.-]+[,:]?\s*)+")

# The fixer's done line: "please verify BL-1 on PR <url> (branch <name>)", after its mention.
VERIFY_REQUEST_RE = re.compile(
    rf"please verify {TICKET_PREFIX}-(?P<number>\d+) on PR (?P<pr_url>{PR_URL_RE.pattern})",
    re.IGNORECASE,
)
# The reproducer's verdict, at the start of a message once the mentions are stripped:
# "Verified BL-1: <PR url>" or "Not verified BL-1: <one line why>".
VERIFIED = "verified"
VERDICT_RE = re.compile(
    rf"(?P<verdict>{VERIFIED}|not {VERIFIED}) {TICKET_PREFIX}-(?P<number>\d+):\s*(?P<rest>.*)",
    re.IGNORECASE,
)


def format_ticket_id(n: int) -> str:
    """Ticket number to its public id: 1 -> "BL-1" with the shipped prefix."""
    return f"{TICKET_PREFIX}-{n}"


def without_mentions(text: str) -> str:
    """`text` without its leading mentions: "@frontdesk Verified BL-1: x" -> "Verified BL-1: x"."""
    return LEADING_MENTIONS.sub("", text).strip()
