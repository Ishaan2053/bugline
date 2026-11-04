"""Facts every Bugline agent relies on: the ticket id format and the reply length limit.

The front desk makes ticket ids and reads them back from the fixer's close message; the coder
agents read them to say which ticket they are busy with. Both import them from here.
"""

import re

TICKET_PREFIX = "BL"
# A ticket id anywhere in a message, with its number as group 1.
TICKET_ID_RE = re.compile(rf"\b{TICKET_PREFIX}-(\d+)\b")
# The eng room's rule (switch/room-instructions-eng.md): replies stay under 10 lines.
REPLY_MAX_LINES = 10


def format_ticket_id(n: int) -> str:
    """Ticket number to its public id: 1 -> "BL-1"."""
    return f"{TICKET_PREFIX}-{n}"
