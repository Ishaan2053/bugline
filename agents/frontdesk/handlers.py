"""What the front desk does with one addressed message, as a list of posts to make.

No sockets and no HTTP here: `handle` reads the message and the store, calls the models, and
returns `Post` actions that agent.py carries out. That keeps every rule from CLAUDE.md section 2
("Front-desk filtering rules") testable with a fake model and an in-memory store.
"""

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

import classify
import config
import messages
from classify import Classification, RateLimited, Report
from store import Draft, Store, Ticket
from switch_client import IncomingMessage


@dataclass(frozen=True)
class Post:
    """A message to post in a room (by key), optionally in a thread and addressed to targets.

    With targets, agent.py uses send_targeted_message; if none of them is reachable it posts
    `if_unreachable` in the same thread so a person sees that nobody picked the work up.
    """

    room: str
    body: str
    thread_id: str | None = None
    target_roles: tuple[str, ...] = ()
    target_names: tuple[str, ...] = ()
    if_unreachable: str | None = None


class Models(Protocol):
    """The three model calls handlers need. The classify module is the real implementation."""

    def classify(self, message: str, draft: Draft | None = None) -> Classification: ...

    def check_duplicate(self, report: Report, open_tickets: Sequence[Ticket]) -> str | None: ...

    def answer_question(self, question: str) -> str: ...


# A leading "@frontdesk" or "@bugline-frontdesk," only addresses us; it is not part of the report.
LEADING_MENTIONS = re.compile(r"^\s*(@[\w.-]+[,:]?\s*)+")


def handle(msg: IncomingMessage, store: Store, models: Models = classify) -> list[Post]:
    """Decide what to post for one addressed message."""
    if msg.room == config.ROOM_ENG:
        return _handle_eng(msg, store)
    return _handle_support(msg, store, models)


def _reply(msg: IncomingMessage, body: str) -> Post:
    return Post(msg.room, body, thread_id=msg.message_id)


def _handle_support(msg: IncomingMessage, store: Store, models: Models) -> list[Post]:
    # Order matters: everything up to classify costs no model call.
    if store.is_muted(msg.room_id, msg.thread_root):
        return []
    if store.too_many_open_tickets(msg.sender_id):
        return [_reply(msg, messages.TOO_MANY_OPEN)]
    if not store.allow_model_reply(msg.sender_id):
        return [_reply(msg, messages.COOLDOWN)]
    text = LEADING_MENTIONS.sub("", msg.body).strip()
    try:
        return _route(msg, text, store, models)
    except RateLimited:
        return [_reply(msg, messages.RATE_LIMITED)]


def _route(msg: IncomingMessage, text: str, store: Store, models: Models) -> list[Post]:
    result = models.classify(text, store.get_draft(msg.room_id, msg.sender_id))
    if result.kind == "question":
        return [_reply(msg, models.answer_question(text))]
    if result.kind == "request":
        store.log_request(msg.sender_id, msg.room_id, text)
        return [_reply(msg, messages.REQUEST_LOGGED)]
    if result.kind == "off-topic":
        store.mute(msg.room_id, msg.thread_root)
        return [_reply(msg, messages.OFF_TOPIC)]
    return _bug(msg, result, store, models)


def _bug(msg: IncomingMessage, result: Classification, store: Store, models: Models) -> list[Post]:
    report = result.report
    if result.missing:
        store.save_draft(msg.room_id, msg.sender_id, asdict(report), result.missing)
        return [_reply(msg, messages.ask_missing(result.missing))]
    store.clear_draft(msg.room_id, msg.sender_id)

    duplicate_of = models.check_duplicate(report, store.open_tickets())
    if duplicate_of:
        store.subscribe(duplicate_of, msg.sender_id, msg.room_id, msg.sender_name, msg.message_id)
        return [_reply(msg, messages.TRACKED.format(ticket_id=duplicate_of))]

    ticket_id = store.open_ticket(
        msg.sender_id,
        msg.sender_name,
        msg.room_id,
        report.title,
        report.actual,
        asdict(report),
        thread_id=msg.message_id,
    )
    names = (config.REPRODUCER_NAME,) if config.REPRODUCER_NAME else ()
    escalate = Post(
        config.ROOM_ENG,
        messages.escalation(ticket_id, report, msg.sender_name),
        target_roles=(config.REPRODUCER_ROLE,),
        target_names=names,
        if_unreachable=messages.NO_REPRODUCER.format(
            role=config.REPRODUCER_ROLE, ticket_id=ticket_id
        ),
    )
    return [escalate, _reply(msg, messages.ESCALATED.format(ticket_id=ticket_id))]


def _handle_eng(msg: IncomingMessage, store: Store) -> list[Post]:
    """In eng the front desk only closes tickets: a ticket id plus a PR link closes it."""
    ticket = config.TICKET_ID_RE.search(msg.body)
    pr = config.PR_URL_RE.search(msg.body)
    if not (ticket and pr):
        return [_reply(msg, messages.ENG_HELP)]
    ticket_id = config.format_ticket_id(int(ticket.group(1)))
    subscribers = store.close_ticket(ticket_id, pr.group(0))
    if not subscribers:
        return [_reply(msg, messages.NOT_OPEN.format(ticket_id=ticket_id))]
    notices = [
        Post(
            config.ROOM_SUPPORT,
            messages.FIXED.format(name=s.name or "Hello", ticket_id=ticket_id, pr_url=pr.group(0)),
            thread_id=s.thread_id,
        )
        for s in subscribers
    ]
    return [_reply(msg, messages.CLOSED.format(ticket_id=ticket_id)), *notices]
