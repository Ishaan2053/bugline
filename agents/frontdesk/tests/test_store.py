"""Tests for the ticket store and the two rate guards."""

import sqlite3

import pytest

import config
from store import SCHEMA, Store, Subscriber


@pytest.fixture
def store() -> Store:
    return Store(":memory:", clock=lambda: 1_000.0)


def new_ticket(store: Store, reporter: str = "u1", title: str = "Share link fails") -> str:
    return store.open_ticket(reporter, "Asha", "support", title, "500 on /share", {"steps": "x"})


def test_ticket_ids_increment(store: Store) -> None:
    assert [new_ticket(store) for _ in range(3)] == ["BL-1", "BL-2", "BL-3"]
    ticket = store.get_ticket("BL-2")
    assert ticket is not None
    assert ticket.report == {"steps": "x"}
    assert ticket.status == "open"
    assert store.get_ticket("BL-9") is None


def test_open_tickets_lists_only_open(store: Store) -> None:
    new_ticket(store, title="first")
    new_ticket(store, title="second")
    store.close_ticket("BL-1", "https://example.test/pr/1")
    assert [(t.ticket_id, t.title) for t in store.open_tickets()] == [("BL-2", "second")]


def test_open_ticket_guard(store: Store) -> None:
    for _ in range(config.MAX_OPEN_TICKETS - 1):
        new_ticket(store, reporter="u1")
    assert not store.too_many_open_tickets("u1")
    new_ticket(store, reporter="u1")
    assert store.too_many_open_tickets("u1")
    assert not store.too_many_open_tickets("u2")
    store.close_ticket("BL-1", "https://example.test/pr/1")
    assert not store.too_many_open_tickets("u1")


def test_cooldown_three_replies_per_minute(store: Store) -> None:
    assert [store.allow_model_reply("u1", now=t) for t in (0, 10, 20)] == [True, True, True]
    assert not store.allow_model_reply("u1", now=30)
    assert store.allow_model_reply("u2", now=30)  # other users are not affected
    assert not store.allow_model_reply("u1", now=59.9)
    assert store.allow_model_reply("u1", now=60.5)  # the reply at t=0 has left the window


def test_cooldown_uses_store_clock() -> None:
    now = [0.0]
    store = Store(":memory:", clock=lambda: now[0])
    for _ in range(config.REPLIES_PER_MINUTE):
        assert store.allow_model_reply("u1")
    assert not store.allow_model_reply("u1")
    now[0] = 61.0
    assert store.allow_model_reply("u1")


def test_close_notifies_reporter_and_subscribers_once(store: Store) -> None:
    ticket_id = store.open_ticket("u1", "Asha", "support", "Share link", "500", {}, thread_id="m1")
    store.subscribe(ticket_id, "u2", "support", "Ravi", "m2")
    store.subscribe(ticket_id, "u2", "support", "Ravi", "m3")
    store.subscribe(ticket_id, "u1", "support")  # the reporter is already subscribed
    notify = store.close_ticket(ticket_id, "https://example.test/pr/7")
    assert notify == [
        Subscriber("u1", "support", "Asha", "m1"),
        Subscriber("u2", "support", "Ravi", "m2"),
    ]
    ticket = store.get_ticket(ticket_id)
    assert ticket is not None
    assert ticket.status == "closed"
    assert ticket.pr_url == "https://example.test/pr/7"
    assert store.close_ticket(ticket_id, "https://example.test/pr/7") == []
    assert store.close_ticket("BL-99", "https://example.test/pr/7") == []


def test_draft_round_trip(store: Store) -> None:
    assert store.get_draft("support", "u1") is None
    store.save_draft("support", "u1", {"title": "Share link"}, ["group_id"])
    draft = store.get_draft("support", "u1")
    assert draft is not None
    assert draft.report == {"title": "Share link"}
    assert draft.missing == ["group_id"]
    assert store.get_draft("support", "u2") is None
    store.save_draft("support", "u1", {"title": "Share link", "group_id": "1"}, [])
    assert store.get_draft("support", "u1").missing == []
    store.clear_draft("support", "u1")
    assert store.get_draft("support", "u1") is None


def test_mute_and_requests(store: Store) -> None:
    assert not store.is_muted("support", "t1")
    store.mute("support", "t1")
    store.mute("support", "t1")
    assert store.is_muted("support", "t1")
    assert not store.is_muted("support", "t2")
    assert store.log_request("u1", "support", "Export to CSV please") == 1


def test_state_survives_restart(tmp_path) -> None:
    path = tmp_path / "state" / "frontdesk.db"
    first = Store(path)
    new_ticket(first)
    first.close()
    second = Store(path)
    assert new_ticket(second) == "BL-2"


def test_list_tickets_newest_first_with_subscribers(store: Store) -> None:
    for title in ("first", "second", "third"):
        new_ticket(store, title=title)
    store.subscribe("BL-2", "u2", "support", "Ravi")
    assert [t.title for t in store.list_tickets(2)] == ["third", "second"]
    assert store.count_tickets() == 3
    assert [s.name for s in store.subscribers("BL-2")] == ["Asha", "Ravi"]


def test_close_records_who_closed_it(store: Store) -> None:
    new_ticket(store)
    new_ticket(store)
    store.close_ticket("BL-1", "https://example.test/pr/1", closed_by="bugline-repro")
    store.close_ticket("BL-2", "https://example.test/pr/2")
    assert store.get_ticket("BL-1").closed_by == "bugline-repro"  # type: ignore[union-attr]
    assert store.get_ticket("BL-2").closed_by is None  # type: ignore[union-attr]


def test_a_database_without_closed_by_gets_the_column(tmp_path) -> None:
    path = tmp_path / "old.db"
    old_schema = SCHEMA.replace(",\n    closed_by       TEXT", "")
    assert "closed_by" not in old_schema
    with sqlite3.connect(path) as db:
        db.executescript(old_schema)
        db.execute(
            "INSERT INTO tickets (n, ticket_id, reporter_id, reporter_name, support_room_id,"
            " title, summary, report_json, created_at) VALUES (1, 'BL-1', 'u1', 'Asha', 's',"
            " 't', 's', '{}', '2026-11-04T10:00:00+00:00')"
        )
    db.close()
    store = Store(path)
    assert store.get_ticket("BL-1").closed_by is None  # type: ignore[union-attr]
    store.close()
    Store(path).close()  # a second start finds the column and changes nothing
