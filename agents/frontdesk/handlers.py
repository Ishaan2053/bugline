"""What the front desk does with one addressed message, as a list of posts to make.

No sockets and no HTTP here: `handle` reads the message and the store, calls the models, and
returns `Post` actions that agent.py carries out. That keeps every rule from CLAUDE.md section 2
("Front-desk filtering rules") testable with a fake model and an in-memory store.
"""

import logging
import re
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from common.conventions import without_mentions
from common.switch_client import IncomingMessage

import classify
import config
import messages
from classify import Classification, RateLimited, Report
from store import Draft, Question, Store, Ticket

log = logging.getLogger(__name__)


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
    """The model calls handlers need. The classify module is the real implementation."""

    def classify(self, message: str, draft: Draft | None = None) -> Classification: ...

    def check_duplicate(self, report: Report, open_tickets: Sequence[Ticket]) -> str | None: ...

    def answer_question(self, question: str) -> str: ...

    def translate(self, text: str, language: str) -> str: ...


# The whole of an eng message after the mentions: "status" or "status BL-n", any case.
STATUS_RE = re.compile(
    rf"{config.STATUS_COMMAND}(?:\s+{config.TICKET_ID_RE.pattern})?[.!?]?", re.IGNORECASE
)
REQUESTS_RE = re.compile(rf"{config.REQUESTS_COMMAND}[.!?]?", re.IGNORECASE)
# "ask BL-n: <question>" (the colon is optional); the question may run over several lines.
ASK_RE = re.compile(
    rf"{config.ASK_COMMAND}\s+{config.TICKET_ID_RE.pattern}[:,]?\s+(.+)", re.IGNORECASE | re.DOTALL
)


def handle(
    msg: IncomingMessage,
    store: Store,
    models: Models = classify,
    verifiers: Collection[str] = (),
) -> list[Post]:
    """Decide what to post for one addressed message.

    `verifiers` are the agent names whose `Verified BL-n` closes a ticket (the reproducer's);
    agent.py looks them up at start.
    """
    if msg.room == config.ROOM_ENG:
        return _handle_eng(msg, store, verifiers, models)
    return _handle_support(msg, store, models)


def _reply(msg: IncomingMessage, body: str) -> Post:
    return Post(msg.room, body, thread_id=msg.thread_root)


def _in_language(text: str, user_id: str, store: Store, models: Models) -> str:
    """`text` in the language `user_id` writes in. If translating fails, the English text."""
    language = store.language(user_id)
    if language == config.TEAM_LANGUAGE:
        return text
    try:
        return models.translate(text, language)
    except Exception:  # a reply in English beats no reply
        log.warning("could not translate a reply into %s; sending it in English", language)
        return text


def _say(msg: IncomingMessage, body: str, store: Store, models: Models) -> Post:
    """A reply to the sender in the support room, in their language."""
    return _reply(msg, _in_language(body, msg.sender_id, store, models))


def _handle_support(msg: IncomingMessage, store: Store, models: Models) -> list[Post]:
    # Order matters: everything up to classify costs no model call.
    if store.is_muted(msg.room_id, msg.thread_root):
        return []
    text = without_mentions(msg.body)
    # A reporter with a question from the eng room: this message is the answer. It is passed on
    # as it is, so no model call and no rate guard.
    named = config.TICKET_ID_RE.search(text)
    ticket_id = config.format_ticket_id(int(named.group(1))) if named else None
    question = store.pending_question(msg.sender_id, msg.room_id, ticket_id) or (
        store.pending_question(msg.sender_id, msg.room_id) if ticket_id else None
    )
    if question:
        return _pass_answer(msg, text, question, store, models)
    # "still broken" from someone waiting on a closed ticket: reopen it, again with no model call.
    if config.REOPEN_RE.search(text):
        closed = store.closed_ticket_of(msg.sender_id, ticket_id)
        if closed and store.reopen_ticket(closed.ticket_id):
            return _reopen(msg, text, closed, store, models)
    if store.too_many_open_tickets(msg.sender_id):
        return [_reply(msg, messages.TOO_MANY_OPEN)]
    if not store.allow_model_reply(msg.sender_id):
        return [_reply(msg, messages.COOLDOWN)]
    try:
        return _route(msg, text, store, models)
    except RateLimited:
        return [_reply(msg, messages.RATE_LIMITED)]


def _route(msg: IncomingMessage, text: str, store: Store, models: Models) -> list[Post]:
    result = models.classify(text, store.get_draft(msg.room_id, msg.sender_id))
    store.set_language(msg.sender_id, result.language)
    if result.kind == "question":  # the answer prompt replies in the question's language
        return [_reply(msg, models.answer_question(text))]
    if result.kind == "request":
        store.log_request(msg.sender_id, msg.room_id, text, msg.sender_name)
        return [_say(msg, messages.REQUEST_LOGGED, store, models)]
    if result.kind == "off-topic":
        store.mute(msg.room_id, msg.thread_root)
        return [_say(msg, messages.OFF_TOPIC, store, models)]
    return _bug(msg, result, store, models)


def _bug(msg: IncomingMessage, result: Classification, store: Store, models: Models) -> list[Post]:
    report = result.report
    if result.missing:
        store.save_draft(msg.room_id, msg.sender_id, asdict(report), result.missing)
        return [_say(msg, messages.ask_missing(result.missing), store, models)]
    store.clear_draft(msg.room_id, msg.sender_id)

    duplicate_of = models.check_duplicate(report, store.open_tickets())
    if duplicate_of:
        store.subscribe(duplicate_of, msg.sender_id, msg.room_id, msg.sender_name, msg.thread_root)
        return [_say(msg, messages.TRACKED.format(ticket_id=duplicate_of), store, models)]

    ticket_id = store.open_ticket(
        msg.sender_id,
        msg.sender_name,
        msg.room_id,
        report.title,
        getattr(report, config.PROJECT.summary_field),  # what the duplicate check reads
        asdict(report),
        thread_id=msg.thread_root,
    )
    body = messages.escalation(ticket_id, report, msg.sender_name, result.language)
    escalate = _to_reproducer(body, ticket_id)
    return [escalate, _say(msg, messages.ESCALATED.format(ticket_id=ticket_id), store, models)]


def _pass_answer(
    msg: IncomingMessage, text: str, question: Question, store: Store, models: Models
) -> list[Post]:
    """Post the reporter's answer in the eng thread the question was asked in, in TEAM_LANGUAGE."""
    store.mark_answered(question.id)
    if store.language(msg.sender_id) != config.TEAM_LANGUAGE:
        try:
            text = models.translate(text, config.TEAM_LANGUAGE)
        except Exception:
            log.warning("could not translate an answer; passing it on as written")
    body = messages.answer(msg.sender_name, question.asked_by, question.ticket_id, text)
    return [
        Post(config.ROOM_ENG, body, thread_id=question.eng_thread_id),
        _say(msg, messages.ANSWER_PASSED, store, models),
    ]


def _reopen(
    msg: IncomingMessage, text: str, ticket: Ticket, store: Store, models: Models
) -> list[Post]:
    """Hand a reopened ticket back to the reproducer, the same way as a new one."""
    escalate = _to_reproducer(messages.reopened(ticket, msg.sender_name, text), ticket.ticket_id)
    confirm = _say(msg, messages.REOPENED.format(ticket_id=ticket.ticket_id), store, models)
    return [escalate, confirm]


def _to_reproducer(body: str, ticket_id: str) -> Post:
    """A post in the eng room addressed to the reproducer role (and its name, when set)."""
    names = (config.REPRODUCER_NAME,) if config.REPRODUCER_NAME else ()
    return Post(
        config.ROOM_ENG,
        body,
        target_roles=(config.REPRODUCER_ROLE,),
        target_names=names,
        if_unreachable=messages.NO_REPRODUCER.format(
            role=config.REPRODUCER_ROLE, ticket_id=ticket_id
        ),
    )


def _handle_eng(
    msg: IncomingMessage, store: Store, verifiers: Collection[str], models: Models
) -> list[Post]:
    """In eng the front desk shows the ticket board, asks reporters, and closes verified tickets.

    `status` lists tickets and `status BL-n` shows one. `requests` lists feature requests.
    `ask BL-n: <question>` asks the reporter. `Verified BL-n: <PR url>` from the reproducer or
    the room owner closes a ticket; `Not verified BL-n: <why>` leaves it open.
    Anyone else who names a ticket is told who may close it. No model call happens here.
    """
    text = without_mentions(msg.body)
    status = STATUS_RE.fullmatch(text)
    if status:
        return [_reply(msg, _status(store, status.group(1)))]
    if REQUESTS_RE.fullmatch(text):
        requests = store.list_requests(config.STATUS_MAX_ROWS)
        board = messages.request_list(requests, store.utc_now(), store.count_requests())
        return [_reply(msg, board)]
    ask = ASK_RE.fullmatch(text)
    if ask:
        ticket_id = config.format_ticket_id(int(ask.group(1)))
        return _ask_reporter(msg, store, models, ticket_id, ask.group(2))
    if not config.TICKET_ID_RE.search(msg.body):
        return [_reply(msg, messages.ENG_HELP)]
    if not _may_close(msg, verifiers):
        return [_reply(msg, messages.NOT_VERIFIER)]
    verdict = config.VERDICT_RE.match(text)
    if not verdict:
        return [_reply(msg, messages.CLOSE_FORMAT)]
    ticket_id = config.format_ticket_id(int(verdict.group("number")))
    if verdict.group("verdict").lower() != config.VERIFIED:
        return [_reply(msg, messages.STAYS_OPEN.format(ticket_id=ticket_id))]
    pr = config.PR_URL_RE.search(verdict.group("rest"))
    if not pr:
        return [_reply(msg, messages.CLOSE_FORMAT)]
    subscribers = store.close_ticket(ticket_id, pr.group(0), msg.sender_name or msg.sender_id)
    if not subscribers:
        return [_reply(msg, messages.NOT_OPEN.format(ticket_id=ticket_id))]
    notices = [
        Post(
            config.ROOM_SUPPORT,
            _in_language(
                messages.FIXED.format(
                    name=s.name or "Hello", ticket_id=ticket_id, pr_url=pr.group(0)
                ),
                s.user_id,
                store,
                models,
            ),
            thread_id=s.thread_id,
        )
        for s in subscribers
    ]
    return [_reply(msg, messages.CLOSED.format(ticket_id=ticket_id)), *notices]


def _ask_reporter(
    msg: IncomingMessage, store: Store, models: Models, ticket_id: str, question: str
) -> list[Post]:
    """Ask the ticket's reporter in their support thread; their next message comes back here.

    Anyone in the eng room may ask, people and agents: the room is already the team's.
    """
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        return [_reply(msg, messages.UNKNOWN_TICKET.format(ticket_id=ticket_id))]
    if ticket.status != "open":
        return [_reply(msg, messages.ASK_CLOSED.format(ticket_id=ticket_id))]
    reporter = next(s for s in store.subscribers(ticket_id) if s.user_id == ticket.reporter_id)
    asked_by = msg.sender_name or msg.sender_id
    store.add_question(ticket_id, reporter.user_id, reporter.room_id, asked_by, msg.thread_root)
    name = reporter.name or "Hello"
    return [
        Post(
            config.ROOM_SUPPORT,
            _in_language(
                messages.QUESTION.format(name=name, ticket_id=ticket_id, question=question.strip()),
                reporter.user_id,
                store,
                models,
            ),
            thread_id=reporter.thread_id,
        ),
        _reply(msg, messages.ASKED.format(name=name, room=config.ROOM_NAMES[config.ROOM_SUPPORT])),
    ]


def _may_close(msg: IncomingMessage, verifiers: Collection[str]) -> bool:
    """The room owner, or the reproducer agent.

    Switch tells us a person's workspace role with each message (`sender_role`). An agent has
    none, so the reproducer is known by its name, and only when no person's role came with it.
    """
    if msg.sender_role == config.OWNER_SENDER_ROLE:
        return True
    return msg.sender_role is None and msg.sender_name in verifiers


def _status(store: Store, number: str | None) -> str:
    """The ticket board, or one ticket in full when `number` is given."""
    if number is None:
        tickets = store.list_tickets(config.STATUS_MAX_ROWS)
        counts = {t.ticket_id: len(store.subscribers(t.ticket_id)) for t in tickets}
        return messages.status_board(tickets, counts, store.utc_now(), store.count_tickets())
    ticket_id = config.format_ticket_id(int(number))
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        return messages.UNKNOWN_TICKET.format(ticket_id=ticket_id)
    return messages.status_one(ticket, store.subscribers(ticket_id), store.utc_now())
