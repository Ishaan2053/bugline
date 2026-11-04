"""Tests for handlers.py: a fake model and an in-memory store, one test per branch."""

from collections.abc import Sequence

import pytest
from common.switch_client import IncomingMessage

import config
import messages
from classify import Classification, RateLimited, Report
from handlers import Post, handle
from store import Draft, Store, Ticket

PR = "https://github.com/Ishaan2053/bugline/pull/7"
COMPLETE = Report(
    title="Share link returns an error",
    steps="Open /share/goa-trip-share",
    expected="Group summary",
    actual="Internal Server Error",
    group_id="1",
)


class FakeModels:
    """Returns queued classifications and records every model call."""

    def __init__(self, *results: Classification | Exception, duplicate: str | None = None):
        self.results = list(results)
        self.duplicate = duplicate
        self.calls: list[tuple] = []

    def classify(self, message: str, draft: Draft | None = None) -> Classification:
        self.calls.append(("classify", message, draft))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def check_duplicate(self, report: Report, open_tickets: Sequence[Ticket]) -> str | None:
        self.calls.append(("duplicate", [t.ticket_id for t in open_tickets]))
        return self.duplicate

    def answer_question(self, question: str) -> str:
        self.calls.append(("answer", question))
        return "Net is paid minus owes."


def bug(missing: Sequence[str] = (), report: Report = COMPLETE) -> Classification:
    return Classification("bug", list(missing), report)


def kind(name: str) -> Classification:
    return Classification(name, [], Report())  # type: ignore[arg-type]


def msg(body: str, *, room: str = config.ROOM_SUPPORT, user: str = "u1", n: int = 1, thread=None):
    return IncomingMessage(
        room=room,
        room_id=f"room-{room}",
        sender_id=user,
        sender_name={"u1": "Asha", "u2": "Ravi"}.get(user, user),
        body=body,
        message_id=f"m{n}",
        thread_id=thread,
    )


@pytest.fixture
def store() -> Store:
    now = [0.0]
    s = Store(":memory:", clock=lambda: now[0])
    s.now = now  # type: ignore[attr-defined]  # tests move the clock forward
    return s


def reply(body: str, n: int = 1) -> Post:
    return Post(config.ROOM_SUPPORT, body, thread_id=f"m{n}")


def test_question_is_answered_in_thread(store: Store) -> None:
    models = FakeModels(kind("question"))
    posts = handle(msg("@frontdesk what does net mean?"), store, models)
    assert posts == [reply("Net is paid minus owes.")]
    assert models.calls[0] == ("classify", "what does net mean?", None)  # mention stripped


def test_request_is_logged_and_acknowledged(store: Store) -> None:
    posts = handle(msg("@frontdesk please add CSV export"), store, FakeModels(kind("request")))
    assert posts == [reply(messages.REQUEST_LOGGED)]


def test_off_topic_gets_one_line_then_the_thread_is_muted(store: Store) -> None:
    models = FakeModels(kind("off-topic"))
    assert handle(msg("@frontdesk buy crypto"), store, models) == [reply(messages.OFF_TOPIC)]
    follow_up = msg("@frontdesk hello??", n=2, thread="m1")
    assert handle(follow_up, store, models) == []
    assert len(models.calls) == 1  # no model call for the muted thread


def test_incomplete_bug_asks_for_missing_fields_and_keeps_a_draft(store: Store) -> None:
    vague = Report(title="Share link broken", actual="error")
    models = FakeModels(bug(["steps", "group_id"], vague), bug())
    posts = handle(msg("@frontdesk share link is broken"), store, models)
    assert posts == [reply(messages.ask_missing(["steps", "group_id"]))]
    assert "the steps you took and your group id" in posts[0].body
    assert store.open_tickets() == []

    handle(msg("@frontdesk group 1, I opened the link", n=2), store, models)
    draft = models.calls[1][2]
    assert draft == Draft(report={**vars(vague)}, missing=["steps", "group_id"])
    assert store.get_draft("room-support", "u1") is None  # cleared once complete


def test_complete_bug_opens_ticket_and_escalates_to_reproducer(store: Store) -> None:
    posts = handle(msg("@frontdesk full report"), store, FakeModels(bug()))
    escalate, confirm = posts
    assert escalate.room == config.ROOM_ENG
    assert escalate.target_roles == (config.REPRODUCER_ROLE,)
    assert escalate.thread_id is None
    assert escalate.body.splitlines() == [
        "BL-1: Share link returns an error",
        "Reporter: Asha (bugline-support)",
        "Group: 1",
        "Steps: Open /share/goa-trip-share",
        "Expected: Group summary",
        "Actual: Internal Server Error",
        "@reproducer please reproduce and post your verdict in this thread.",
    ]
    assert "BL-1" in escalate.if_unreachable
    assert confirm == reply(messages.ESCALATED.format(ticket_id="BL-1"))
    ticket = store.get_ticket("BL-1")
    assert ticket is not None and ticket.reporter_name == "Asha"


def test_reproducer_name_is_targeted_when_configured(store, monkeypatch) -> None:
    monkeypatch.setattr(config, "REPRODUCER_NAME", "bugline-repro")
    escalate = handle(msg("@frontdesk full report"), store, FakeModels(bug()))[0]
    assert escalate.target_names == ("bugline-repro",)


def test_duplicate_subscribes_and_posts_nothing_to_eng(store: Store) -> None:
    handle(msg("@frontdesk full report"), store, FakeModels(bug()))
    models = FakeModels(bug(), duplicate="BL-1")
    posts = handle(msg("@frontdesk share link broken for me too", user="u2", n=5), store, models)
    assert posts == [reply(messages.TRACKED.format(ticket_id="BL-1"), n=5)]
    assert ("duplicate", ["BL-1"]) in models.calls
    assert len(store.open_tickets()) == 1


def test_sixth_open_ticket_is_refused_before_any_model_call(store: Store) -> None:
    for i in range(config.MAX_OPEN_TICKETS):
        store.open_ticket("u1", "Asha", "room-support", f"bug {i}", "x", {})
    models = FakeModels()
    assert handle(msg("@frontdesk another one"), store, models) == [reply(messages.TOO_MANY_OPEN)]
    assert models.calls == []


def test_cooldown_after_three_model_replies_a_minute(store: Store) -> None:
    models = FakeModels(*[kind("question")] * 4)
    for n in range(1, 4):
        handle(msg("@frontdesk q", n=n), store, models)
    assert handle(msg("@frontdesk q", n=4), store, models) == [reply(messages.COOLDOWN, n=4)]
    assert len([c for c in models.calls if c[0] == "classify"]) == 3
    store.now[0] = config.REPLY_WINDOW_S + 1  # type: ignore[attr-defined]
    assert handle(msg("@frontdesk q", n=5), store, models)[0].body != messages.COOLDOWN


def test_rate_limited_model_gets_a_holding_reply(store: Store) -> None:
    models = FakeModels(RateLimited("429"))
    assert handle(msg("@frontdesk hi"), store, models) == [reply(messages.RATE_LIMITED)]


def test_close_in_eng_notifies_reporter_and_every_subscriber(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    handle(msg("@frontdesk me too", user="u2", n=2), store, FakeModels(bug(), duplicate="BL-1"))
    close = msg(f"@frontdesk BL-1 fixed in {PR}", room=config.ROOM_ENG, user="fixer", n=9)

    posts = handle(close, store, FakeModels())

    assert posts == [
        Post(config.ROOM_ENG, "Closed BL-1, telling the reporter.", thread_id="m9"),
        Post(config.ROOM_SUPPORT, f"Asha, BL-1 is fixed: {PR}", thread_id="m1"),
        Post(config.ROOM_SUPPORT, f"Ravi, BL-1 is fixed: {PR}", thread_id="m2"),
    ]
    again = handle(close, store, FakeModels())
    assert again == [Post(config.ROOM_ENG, messages.NOT_OPEN.format(ticket_id="BL-1"), "m9")]


def test_replies_inside_a_thread_stay_in_that_thread(store: Store) -> None:
    # The live BL-2 run: the fixer's close is a reply in the ticket's thread (root t1), so
    # "Closed" must go to t1, not start a sub-thread under the fixer's own message.
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    close = msg(f"@frontdesk BL-1 fixed in {PR}", room=config.ROOM_ENG, n=9, thread="t1")
    assert handle(close, store, FakeModels())[0].thread_id == "t1"
    # A report completed by a reply in a support thread is answered, and later notified, there.
    completed = msg("@frontdesk group 1", user="u2", n=3, thread="t2")
    assert handle(completed, store, FakeModels(bug()))[-1].thread_id == "t2"
    close_2 = msg(f"@frontdesk BL-2 fixed in {PR}", room=config.ROOM_ENG, n=10, thread="t3")
    assert handle(close_2, store, FakeModels())[-1].thread_id == "t2"


def test_other_eng_messages_get_one_line_about_what_the_front_desk_does(store: Store) -> None:
    posts = handle(msg("@frontdesk BL-1 reproduced", room=config.ROOM_ENG), store, FakeModels())
    assert posts == [Post(config.ROOM_ENG, messages.ENG_HELP, thread_id="m1")]


def eng(body: str, n: int = 9) -> IncomingMessage:
    return msg(body, room=config.ROOM_ENG, user="pm", n=n)


def test_status_with_no_tickets(store: Store) -> None:
    posts = handle(eng("@frontdesk status"), store, FakeModels())
    assert posts == [Post(config.ROOM_ENG, messages.NO_TICKETS, thread_id="m9")]


def test_status_board_lists_tickets_newest_first(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))  # BL-1 at 0 min
    store.now[0] = 5 * 60  # type: ignore[attr-defined]
    handle(msg("@frontdesk other bug", user="u2", n=2), store, FakeModels(bug()))  # BL-2
    handle(msg("@frontdesk me too", n=3), store, FakeModels(bug(), duplicate="BL-2"))
    store.now[0] = 17 * 60  # type: ignore[attr-defined]
    store.close_ticket("BL-1", PR, closed_by="bugline-repro")
    store.now[0] = 30 * 60  # type: ignore[attr-defined]
    handle(msg("@frontdesk third", user="u3", n=4), store, FakeModels(bug()))  # BL-3

    store.now[0] = 42 * 60  # type: ignore[attr-defined]
    (post,) = handle(eng("@frontdesk Status."), store, FakeModels())

    assert post.body.splitlines() == [
        "BL-3 · open · 12 min · u3 · Share link returns an error",
        "BL-2 · open · 37 min · Ravi (+1) · Share link returns an error",
        "BL-1 · closed · 17 min · Asha · PR #7, closed by bugline-repro",
    ]


def test_status_board_is_cut_to_fit_the_reply_limit(store: Store) -> None:
    for i in range(12):
        store.open_ticket("u1", "Asha", "room-support", f"bug {i + 1}", "x", {})
    (post,) = handle(eng("@frontdesk status"), store, FakeModels())
    lines = post.body.splitlines()
    assert len(lines) < config.REPLY_MAX_LINES
    assert [line.split(" · ")[0] for line in lines[:-1]] == [f"BL-{n}" for n in range(12, 4, -1)]
    assert lines[-1] == "+4 more"


def test_status_of_one_ticket_shows_report_and_everyone_waiting(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    handle(msg("@frontdesk me too", user="u2", n=2), store, FakeModels(bug(), duplicate="BL-1"))
    store.now[0] = 12 * 60  # type: ignore[attr-defined]
    (open_post,) = handle(eng("@frontdesk status bl-1"), store, FakeModels())
    assert open_post.body.splitlines() == [
        "BL-1: Share link returns an error",
        "Status: open for 12 min",
        "Subscribers: Asha (reporter), Ravi",
        "Group: 1",
        "Steps: Open /share/goa-trip-share",
        "Expected: Group summary",
        "Actual: Internal Server Error",
        "Opened 1970-01-01 00:00 UTC",
    ]

    store.now[0] = 17 * 60  # type: ignore[attr-defined]
    store.close_ticket("BL-1", PR, closed_by="Ishaan")
    (closed_post,) = handle(eng("@frontdesk status BL-1"), store, FakeModels())
    lines = closed_post.body.splitlines()
    assert lines[1] == f"Status: closed after 17 min by Ishaan: {PR}"
    assert lines[-1] == "Opened 1970-01-01 00:00 UTC, closed 1970-01-01 00:17 UTC"
    assert len(lines) < config.REPLY_MAX_LINES


def test_status_of_an_unknown_ticket(store: Store) -> None:
    (post,) = handle(eng("@frontdesk status BL-4"), store, FakeModels())
    assert post.body == messages.UNKNOWN_TICKET.format(ticket_id="BL-4")


def test_status_is_not_a_command_in_the_support_room(store: Store) -> None:
    models = FakeModels(kind("question"))
    handle(msg("@frontdesk status"), store, models)
    assert models.calls[0] == ("classify", "status", None)


def test_a_sentence_starting_with_status_is_not_the_command(store: Store) -> None:
    posts = handle(eng("@frontdesk status of BL-1 please"), store, FakeModels())
    assert posts == [Post(config.ROOM_ENG, messages.ENG_HELP, thread_id="m9")]
