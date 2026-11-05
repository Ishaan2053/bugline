"""Tests for handlers.py: a fake model and an in-memory store, one test per branch."""

from collections.abc import Sequence
from dataclasses import replace

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
        self.translate_error: Exception | None = None
        self.duplicate_error: Exception | None = None
        self.calls: list[tuple] = []

    def classify(self, message: str, draft: Draft | None = None) -> Classification:
        self.calls.append(("classify", message, draft))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def check_duplicate(self, report: Report, open_tickets: Sequence[Ticket]) -> str | None:
        self.calls.append(("duplicate", [t.ticket_id for t in open_tickets]))
        if self.duplicate_error:
            raise self.duplicate_error
        return self.duplicate

    def answer_question(self, question: str) -> str:
        self.calls.append(("answer", question))
        return "Net is paid minus owes."

    def translate(self, text: str, language: str) -> str:
        self.calls.append(("translate", language))
        if self.translate_error:
            raise self.translate_error
        return f"[{language}] {text}"


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


REPRO = "bugline-repro"  # the verifier's agent name, as agent.py looks it up
VERIFIERS = frozenset({REPRO})


def eng(body: str, n: int = 9, user: str = "pm", role: str | None = None, thread=None):
    """A message in the eng room. `role` is the sender_role Switch reports for a person."""
    return replace(msg(body, room=config.ROOM_ENG, user=user, n=n, thread=thread), sender_role=role)


def verified(ticket: int = 1, by: str = REPRO, **kwargs) -> IncomingMessage:
    return eng(f"@bugline-frontdesk Verified BL-{ticket}: {PR}", user=by, **kwargs)


def fixed(name: str, ticket_id: str = "BL-1") -> str:
    return messages.FIXED.format(name=name, ticket_id=ticket_id, pr_url=PR)


def close(message: IncomingMessage, store: Store) -> list[Post]:
    return handle(message, store, FakeModels(), verifiers=VERIFIERS)


def test_verified_by_the_reproducer_closes_and_notifies_every_subscriber(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    handle(msg("@frontdesk me too", user="u2", n=2), store, FakeModels(bug(), duplicate="BL-1"))

    posts = close(verified(), store)

    assert posts == [
        Post(config.ROOM_ENG, "Closed BL-1, telling the reporter.", thread_id="m9"),
        Post(config.ROOM_SUPPORT, fixed("Asha"), thread_id="m1"),
        Post(config.ROOM_SUPPORT, fixed("Ravi"), thread_id="m2"),
    ]
    assert store.get_ticket("BL-1").closed_by == REPRO  # type: ignore[union-attr]
    (board,) = handle(eng("@frontdesk status"), store, FakeModels())
    assert board.body.endswith(f"PR #7, closed by {REPRO}")
    again = close(verified(), store)
    assert again == [Post(config.ROOM_ENG, messages.NOT_OPEN.format(ticket_id="BL-1"), "m9")]


def test_the_room_owner_may_close_by_hand(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    posts = close(verified(by="ishaan2053", role=config.OWNER_SENDER_ROLE), store)
    assert posts[0].body == "Closed BL-1, telling the reporter."
    assert store.get_ticket("BL-1").closed_by == "ishaan2053"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "sender",
    [
        verified(by="fixer"),  # another agent: the fixer's old close line no longer closes
        verified(by="sam", role="member"),  # a person who is not the owner
        verified(by=REPRO, role="admin"),  # a person who took the reproducer's name
        eng("@frontdesk BL-1 reproduced", user="u1"),
    ],
)
def test_anyone_else_naming_a_ticket_is_refused(store: Store, sender: IncomingMessage) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    assert close(sender, store) == [Post(config.ROOM_ENG, messages.NOT_VERIFIER, "m9")]
    assert store.get_ticket("BL-1").status == "open"  # type: ignore[union-attr]


def test_without_a_verifier_id_only_the_owner_closes(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    refused = handle(verified(), store, FakeModels())  # agent.py found no verifier: empty set
    assert refused == [Post(config.ROOM_ENG, messages.NOT_VERIFIER, "m9")]
    owner = handle(verified(role=config.OWNER_SENDER_ROLE), store, FakeModels())
    assert owner[0].body == "Closed BL-1, telling the reporter."


def test_not_verified_leaves_the_ticket_open(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    posts = close(eng("@frontdesk Not verified BL-1: test_share fails", user=REPRO), store)
    assert posts == [Post(config.ROOM_ENG, messages.STAYS_OPEN.format(ticket_id="BL-1"), "m9")]
    (board,) = handle(eng("@frontdesk status"), store, FakeModels())
    assert " · open · " in board.body


@pytest.mark.parametrize(
    "body", [f"@frontdesk BL-1 is fixed: {PR}", "@frontdesk Verified BL-1: see the PR"]
)
def test_a_close_needs_the_verified_line_with_a_pr_link(store: Store, body: str) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    posts = close(eng(body, user=REPRO), store)
    assert posts == [Post(config.ROOM_ENG, messages.CLOSE_FORMAT, "m9")]


def test_replies_inside_a_thread_stay_in_that_thread(store: Store) -> None:
    # The live BL-2 run: the close is a reply in the ticket's thread (root t1), so "Closed" must
    # go to t1, not start a sub-thread under the closing message.
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    assert close(verified(thread="t1"), store)[0].thread_id == "t1"
    # A report completed by a reply in a support thread is answered, and later notified, there.
    completed = msg("@frontdesk group 1", user="u2", n=3, thread="t2")
    assert handle(completed, store, FakeModels(bug()))[-1].thread_id == "t2"
    assert close(verified(2, n=10, thread="t3"), store)[-1].thread_id == "t2"


def test_other_eng_messages_get_one_line_about_what_the_front_desk_does(store: Store) -> None:
    posts = handle(eng("@frontdesk hello"), store, FakeModels())
    assert posts == [Post(config.ROOM_ENG, messages.ENG_HELP, thread_id="m9")]


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
    posts = handle(eng("@frontdesk status of the share link please"), store, FakeModels())
    assert posts == [Post(config.ROOM_ENG, messages.ENG_HELP, thread_id="m9")]


def test_ask_reaches_the_reporter_and_the_answer_comes_back(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    handle(msg("@frontdesk me too", user="u2", n=2), store, FakeModels(bug(), duplicate="BL-1"))

    posts = handle(eng("@frontdesk ask BL-1: which browser?", thread="t1"), store, FakeModels())

    question = messages.QUESTION.format(name="Asha", ticket_id="BL-1", question="which browser?")
    asked = messages.ASKED.format(name="Asha", room="bugline-support")
    assert posts == [  # only the reporter is asked, in the thread of their report
        Post(config.ROOM_SUPPORT, question, thread_id="m1"),
        Post(config.ROOM_ENG, asked, thread_id="t1"),
    ]
    for _ in range(config.REPLIES_PER_MINUTE):  # Asha is at her cooldown limit
        store.allow_model_reply("u1")

    answer = handle(
        msg("@frontdesk Firefox 130\non Windows", n=3, thread="m1"), store, FakeModels()
    )

    assert answer == [  # passed on as it is: no model call, no rate guard
        Post(config.ROOM_ENG, "Asha answered pm's question on BL-1: Firefox 130; on Windows", "t1"),
        Post(config.ROOM_SUPPORT, messages.ANSWER_PASSED, thread_id="m1"),
    ]
    store.now[0] += config.REPLY_WINDOW_S  # type: ignore[attr-defined]
    models = FakeModels(kind("question"))
    handle(msg("@frontdesk what does net mean?", n=4), store, models)
    assert models.calls[0][0] == "classify"  # the question was answered once; back to normal


def test_an_answer_naming_a_ticket_goes_to_that_tickets_question(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    handle(msg("@frontdesk another report", n=2), store, FakeModels(bug()))
    handle(eng("@frontdesk ask BL-1: which browser?", thread="t1"), store, FakeModels())
    handle(eng("@frontdesk ask BL-2 what amount?", thread="t2", n=10), store, FakeModels())

    first = handle(msg("@frontdesk BL-2: 1000 rupees", n=3), store, FakeModels())[0]
    second = handle(msg("@frontdesk Firefox", n=4), store, FakeModels())[0]

    assert (first.thread_id, second.thread_id) == ("t2", "t1")
    assert first.body.startswith("Asha answered pm's question on BL-2")


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (False, messages.UNKNOWN_TICKET.format(ticket_id="BL-1")),
        (True, messages.ASK_CLOSED.format(ticket_id="BL-1")),
    ],
)
def test_ask_needs_an_open_ticket(store: Store, setup: bool, expected: str) -> None:
    if setup:
        handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
        close(verified(), store)
    posts = handle(eng("@frontdesk ask BL-1: which browser?"), store, FakeModels())
    assert posts == [Post(config.ROOM_ENG, expected, thread_id="m9")]


def test_still_broken_reopens_the_ticket_and_hands_it_back(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    handle(msg("@frontdesk me too", user="u2", n=2), store, FakeModels(bug(), duplicate="BL-1"))
    close(verified(), store)

    posts = handle(msg("@frontdesk Still broken on group 1", user="u2", n=3), store, FakeModels())

    escalate, confirm = posts  # no model call: FakeModels has nothing queued
    assert escalate.room == config.ROOM_ENG
    assert escalate.target_roles == (config.REPRODUCER_ROLE,)
    assert escalate.body.splitlines()[:3] == [
        "BL-1 (reopened): Share link returns an error",
        "Reopened by: Ravi (bugline-support): Still broken on group 1",
        f"Closed before with: {PR}",
    ]
    assert confirm == reply(messages.REOPENED.format(ticket_id="BL-1"), n=3)
    ticket = store.get_ticket("BL-1")
    assert ticket is not None and (ticket.status, ticket.closed_by) == ("open", None)
    assert len(close(verified(), store)) == 3  # the next close tells both again


def test_reopen_needs_a_closed_ticket_the_sender_waits_on(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    close(verified(), store)
    # Someone who never reported BL-1, and the reporter of an open ticket, go to the model.
    stranger = FakeModels(kind("question"))
    handle(msg("@frontdesk BL-1 is still broken", user="u2", n=2), store, stranger)
    assert stranger.calls[0][0] == "classify"
    assert store.get_ticket("BL-1").status == "closed"  # type: ignore[union-attr]
    handle(msg("@frontdesk reopen BL-1", n=3), store, FakeModels())
    again = FakeModels(kind("question"))
    handle(msg("@frontdesk reopen BL-1", n=4), store, again)  # already open
    assert again.calls[0][0] == "classify"


def test_requests_lists_what_the_support_room_asked_for(store: Store) -> None:
    assert handle(eng("@frontdesk requests"), store, FakeModels())[0].body == messages.NO_REQUESTS
    handle(msg("@frontdesk please add CSV export", n=1), store, FakeModels(kind("request")))
    store.now[0] += 2 * 3600  # type: ignore[attr-defined]
    handle(msg("@frontdesk dark mode\nplease", user="u2", n=2), store, FakeModels(kind("request")))

    (posts,) = handle(eng("@frontdesk Requests"), store, FakeModels())

    assert posts == Post(
        config.ROOM_ENG,
        "#2 · 0 min · Ravi: dark mode; please\n#1 · 2 h · Asha: please add CSV export",
        thread_id="m9",
    )


def test_no_fixed_reply_addresses_an_agent() -> None:
    # A role mention in a reply wakes that agent: the live refusal once started a reproducer run.
    # Only the escalation and the reopen address @reproducer, on purpose.
    fixed_texts = [v for k, v in vars(messages).items() if k.isupper() and isinstance(v, str)]
    roles = [f"@{role}" for role in (config.REPRODUCER_ROLE, "fixer", "frontdesk")]
    assert [t for t in fixed_texts if any(role in t for role in roles)] == []


def hindi_bug(missing: Sequence[str] = ()) -> Classification:
    return Classification("bug", list(missing), COMPLETE, language="Hindi")


def test_a_hindi_reporter_gets_replies_in_hindi_and_eng_gets_english(store: Store) -> None:
    models = FakeModels(hindi_bug())
    escalate, confirm = handle(msg("@frontdesk share link kaam nahi kar raha"), store, models)

    assert escalate.body.splitlines()[:2] == [  # the report itself is in English
        "BL-1: Share link returns an error",
        "Reporter: Asha (bugline-support, wrote in Hindi)",
    ]
    assert confirm.body == "[Hindi] " + messages.ESCALATED.format(ticket_id="BL-1")
    handle(msg("@frontdesk me too", user="u2", n=2), store, FakeModels(bug(), duplicate="BL-1"))

    closing = FakeModels()
    _, asha, ravi = close_with(verified(), store, closing)

    assert asha.body == "[Hindi] " + fixed("Asha")
    assert ravi.body == fixed("Ravi")  # Ravi wrote in English
    assert closing.calls == [("translate", "Hindi")]


def close_with(message: IncomingMessage, store: Store, models: FakeModels) -> list[Post]:
    return handle(message, store, models, verifiers=VERIFIERS)


def test_ask_and_answer_cross_languages(store: Store) -> None:
    handle(msg("@frontdesk share link kaam nahi kar raha", n=1), store, FakeModels(hindi_bug()))
    asking = FakeModels()
    question = handle(eng("@frontdesk ask BL-1: which browser?", thread="t1"), store, asking)[0]
    assert question.body.startswith("[Hindi] Asha, the team has a question about BL-1")

    answering = FakeModels()
    relay, thanks = handle(msg("@frontdesk Chrome", n=2), store, answering)

    assert relay.body == "Asha answered pm's question on BL-1: [English] Chrome"
    assert thanks.body == "[Hindi] " + messages.ANSWER_PASSED
    assert [c[1] for c in answering.calls] == ["English", "Hindi"]


def test_a_failed_translation_sends_english(store: Store) -> None:
    models = FakeModels(hindi_bug(["group_id"]))
    models.translate_error = RateLimited("quota")
    (ask,) = handle(msg("@frontdesk share link kaam nahi kar raha"), store, models)
    assert ask.body == messages.ask_missing(["group_id"])


def test_rate_guard_replies_are_never_translated(store: Store) -> None:
    store.set_language("u1", "Hindi")
    for _ in range(config.REPLIES_PER_MINUTE):
        store.allow_model_reply("u1")
    models = FakeModels()
    assert handle(msg("@frontdesk hello"), store, models) == [reply(messages.COOLDOWN)]
    assert models.calls == []


# --- state left behind by an earlier message --------------------------------------------------


def test_a_closed_tickets_question_does_not_swallow_still_broken(store: Store) -> None:
    """The reporter never answered `ask`; after the close, `still broken` reopens the ticket."""
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))
    handle(eng("@frontdesk ask BL-1: which browser?", n=8), store, FakeModels())
    close(verified(), store)

    posts = handle(msg("@frontdesk still broken", n=3), store, FakeModels())

    assert posts[-1] == reply(messages.REOPENED.format(ticket_id="BL-1"), n=3)
    assert store.get_ticket("BL-1").status == "open"  # type: ignore[union-attr]


def test_a_message_that_is_not_a_bug_drops_the_unfinished_report(store: Store) -> None:
    room_id = msg("x").room_id
    handle(msg("@frontdesk share link broken"), store, FakeModels(bug(missing=["group_id"])))
    assert store.get_draft(room_id, "u1") is not None

    handle(msg("@frontdesk what does net mean?", n=2), store, FakeModels(kind("question")))

    assert store.get_draft(room_id, "u1") is None


def test_an_old_unfinished_report_is_not_continued(store: Store) -> None:
    handle(msg("@frontdesk share link broken"), store, FakeModels(bug(missing=["group_id"])))
    store.now[0] += config.DRAFT_MAX_AGE_S + 1  # type: ignore[attr-defined]
    models = FakeModels(bug())

    handle(msg("@frontdesk settle-up is a paisa short", n=2), store, models)

    assert models.calls[0] == ("classify", "settle-up is a paisa short", None)


def test_an_unexpected_model_error_still_gets_a_reply(store: Store) -> None:
    posts = handle(msg("@frontdesk share link broken"), store, FakeModels(ValueError("bad JSON")))
    assert posts == [reply(messages.SOMETHING_WRONG)]


def test_a_rate_limited_duplicate_check_keeps_the_complete_report(store: Store) -> None:
    handle(msg("@frontdesk full report", n=1), store, FakeModels(bug()))  # an open ticket to check
    models = FakeModels(bug())
    models.duplicate_error = RateLimited("quota")

    posts = handle(msg("@frontdesk group 1", user="u2", n=2), store, models)

    assert posts == [reply(messages.RATE_LIMITED, n=2)]
    draft = store.get_draft(msg("x").room_id, "u2")
    assert draft is not None and draft.missing == [] and draft.report["group_id"] == "1"
