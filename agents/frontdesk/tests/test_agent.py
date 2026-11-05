"""Tests for how agent.py carries out posts (op choice, threading and the two fallbacks), how it
finds the verifier's name and the eng room at start, and where the intake rules come from."""

import asyncio
import json

import httpx
import pytest
from common.switch_client import Credentials, RoomConnection, SwitchApi

import classify
import config
from agent import (
    Poster,
    escalation_room,
    refresh_intake_rules,
    support_rooms,
    verifier_names,
)
from handlers import Post

CREDS = Credentials("agent-1", "key-1")


def run_posts(posts: list[Post], respond) -> tuple[list[tuple[str, str, dict]], Poster]:
    """Carry out `posts` against a mock bridge; return (path, connection id, body) per request."""
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path, request.headers.get("X-Switch-Connection-Id", ""), body))
        return respond(request.url.path, body)

    connections = {
        room: RoomConnection(room, f"room-{room}", CREDS, "http://switch.test", f"c-{room}")
        for room in (config.ROOM_SUPPORT, config.ROOM_ENG)
    }

    async def main() -> Poster:
        api = SwitchApi("http://switch.test", CREDS, transport=httpx.MockTransport(handler))
        poster = Poster(api, connections)
        for post in posts:
            await poster.run(post)
        await api.aclose()
        return poster

    return seen, asyncio.run(main())


def ok(result: dict) -> httpx.Response:
    return httpx.Response(200, json={"result": result})


ESCALATE = Post(config.ROOM_ENG, "BL-1: x", target_roles=("reproducer",), if_unreachable="nobody")


def test_reply_uses_post_message_with_the_room_connection_and_thread() -> None:
    seen, poster = run_posts(
        [Post(config.ROOM_SUPPORT, "hi", thread_id="m1")], lambda path, body: ok({"event_id": "e1"})
    )
    assert seen == [
        ("/agents/agent-1/ops/post_message", "c-support", {"body": "hi", "thread_id": "m1"})
    ]
    assert "e1" in poster.sent  # so the agent never answers its own message


def test_live_reproducer_gets_the_targeted_message_only() -> None:
    seen, _ = run_posts(
        [ESCALATE], lambda path, body: ok({"event_id": "e2", "target_statuses": {"repro": "live"}})
    )
    assert seen == [
        (
            "/agents/agent-1/ops/send_targeted_message",
            "c-eng",
            {"body": "BL-1: x", "target_roles": ["reproducer"]},
        )
    ]


def test_no_live_reproducer_adds_a_note_in_the_thread() -> None:
    seen, _ = run_posts(
        [ESCALATE], lambda path, body: ok({"event_id": "e3", "target_statuses": {}})
    )
    assert seen[1] == (
        "/agents/agent-1/ops/post_message",
        "c-eng",
        {"body": "nobody", "thread_id": "e3"},
    )


def test_dead_connection_falls_back_to_the_unthreaded_message_route() -> None:
    def respond(path: str, body: dict) -> httpx.Response:
        if path.endswith("/post_message"):
            return httpx.Response(409, json={"detail": "unknown connection"})
        return httpx.Response(200, json={"ok": True, "event_id": "e4"})

    seen, _ = run_posts([Post(config.ROOM_SUPPORT, "hi", thread_id="m1")], respond)
    assert seen[1] == ("/agents/agent-1/message", "", {"room_id": "room-support", "content": "hi"})


def test_one_failed_post_does_not_stop_the_ones_after_it(caplog) -> None:
    """A close posts `Closed BL-n` in eng, then "fixed" to each subscriber. Eng failing must not
    keep the reporters from hearing."""
    posts = [
        Post(config.ROOM_ENG, "Closed BL-1, telling the reporter.", thread_id="t1"),
        Post(config.ROOM_SUPPORT, "Asha, BL-1 is fixed", thread_id="m1"),
        Post(config.ROOM_SUPPORT, "Ravi, BL-1 is fixed", thread_id="m2"),
    ]

    def respond(path: str, body: dict) -> httpx.Response:
        if body.get("thread_id") == "t1":
            return httpx.Response(500, json={"detail": "server error"})
        return ok({"event_id": body["thread_id"] + "-reply"})

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["body"])
        return respond(request.url.path, body)

    connections = {
        room: RoomConnection(room, f"room-{room}", CREDS, "http://switch.test", f"c-{room}")
        for room in (config.ROOM_SUPPORT, config.ROOM_ENG)
    }

    async def main() -> None:
        api = SwitchApi("http://switch.test", CREDS, transport=httpx.MockTransport(handler))
        await Poster(api, connections).run_each(posts)
        await api.aclose()

    asyncio.run(main())
    assert seen == [post.body for post in posts]
    assert "could not post to eng" in caplog.text


def lookup(monkeypatch: pytest.MonkeyPatch, agent_id: str, respond) -> frozenset[str]:
    """Run verifier_names with SWITCH_REPRODUCER_AGENT_ID set to `agent_id` ("" for unset)."""
    monkeypatch.setenv(config.VERIFIER_AGENT_ID_ENV, agent_id)
    transport = httpx.MockTransport(lambda request: respond(request.url.path))

    async def main() -> frozenset[str]:
        api = SwitchApi("http://switch.test", CREDS, transport=transport)
        try:
            return await verifier_names(api)
        finally:
            await api.aclose()

    return asyncio.run(main())


def test_the_verifier_is_named_by_the_agent_id_bootstrap_wrote(monkeypatch) -> None:
    def respond(path: str) -> httpx.Response:
        assert path == "/agents/agent-1/ops/get_agent_detail"
        return ok({"id": "a-repro", "name": "bugline-repro"})

    assert lookup(monkeypatch, "a-repro", respond) == {"bugline-repro"}


def test_no_verifier_id_or_a_failed_lookup_leaves_only_the_owner(monkeypatch, caplog) -> None:
    def respond(path: str) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such agent"})

    assert lookup(monkeypatch, "", respond) == frozenset()
    assert "SWITCH_REPRODUCER_AGENT_ID is not set" in caplog.text
    assert lookup(monkeypatch, "a-gone", respond) == frozenset()
    assert "only the room owner can close" in caplog.text


def find_eng(links: list[dict]) -> str:
    """Run escalation_room against a bridge whose support room has `links`."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("X-Switch-Connection-Id", "")))
        return ok(links)

    support = RoomConnection(config.ROOM_SUPPORT, "room-support", CREDS, "http://s.test", "c-sup")

    async def main() -> str:
        support.connected.set()
        api = SwitchApi("http://switch.test", CREDS, transport=httpx.MockTransport(handler))
        try:
            return await escalation_room(api, support)
        finally:
            await api.aclose()
            assert seen == [("/agents/agent-1/ops/list_linked_rooms", "c-sup")]

    return asyncio.run(main())


def link(label: str, room: str, access: str = "member") -> dict:
    return {"target_room_id": room, "label": label, "access": access}


def test_reports_go_where_the_escalates_to_link_points() -> None:
    links = [link("related", "room-x"), link(config.ESCALATION_LINK, "room-eng")]
    assert find_eng(links) == "room-eng"


@pytest.mark.parametrize(
    "links",
    [
        [],  # the link was removed
        [link(config.ESCALATION_LINK, "room-eng", access="not_member")],
        [link(config.ESCALATION_LINK, "room-a"), link(config.ESCALATION_LINK, "room-b")],
    ],
)
def test_without_exactly_one_usable_link_the_front_desk_stops(links: list[dict]) -> None:
    with pytest.raises(RuntimeError, match="bootstrap"):
        find_eng(links)


def refresh(monkeypatch: pytest.MonkeyPatch, respond) -> str:
    """Run refresh_intake_rules against a bridge answering `respond(op)`; return the rules the
    model would get."""
    monkeypatch.setattr(classify, "intake_rules_from_switch", None)
    transport = httpx.MockTransport(lambda request: respond(request.url.path.rsplit("/", 1)[-1]))
    support = RoomConnection(config.ROOM_SUPPORT, "room-support", CREDS, "http://s.test", "c-sup")

    async def main() -> None:
        api = SwitchApi("http://switch.test", CREDS, transport=transport)
        try:
            await refresh_intake_rules(api, support)
        finally:
            await api.aclose()

    asyncio.run(main())
    return classify._intake_rules()


def test_the_intake_rules_come_from_the_kit_in_switch(monkeypatch) -> None:
    name = config.INTAKE_RULES_PATH.name

    def respond(op: str) -> httpx.Response:
        if op == "list_references":
            return ok({"packages": [{"documents": [{"id": "d1", "name": name}]}]})
        return ok([{"id": "d1", "content": "RULES AS EDITED IN SWITCH"}])

    assert refresh(monkeypatch, respond) == "RULES AS EDITED IN SWITCH"


def test_without_switch_the_intake_rules_are_the_repo_copy(monkeypatch) -> None:
    rules = refresh(monkeypatch, lambda op: httpx.Response(500, json={"detail": "down"}))
    assert rules == "TEST INTAKE RULES"  # conftest points the repo copy at this text


def test_support_rooms_are_the_rooms_eng_links_back_to() -> None:
    supports = config.SUPPORT_LINK
    links = [
        link(supports, "r-tg") | {"target_room_name": "Telegram room"},
        link(supports, "r-mm") | {"target_room_name": "Mattermost room"},
        link(supports, "r-x", access="not_member") | {"target_room_name": "Not mine"},
        link("related", "r-y") | {"target_room_name": "Related"},
    ]
    eng = RoomConnection(config.ROOM_ENG, "room-eng", CREDS, "http://s.test", "c-eng")
    transport = httpx.MockTransport(lambda request: ok(links))

    async def main() -> dict[str, str]:
        eng.connected.set()
        api = SwitchApi("http://switch.test", CREDS, transport=transport)
        try:
            return await support_rooms(api, eng)
        finally:
            await api.aclose()

    assert asyncio.run(main()) == {"r-tg": "Telegram room", "r-mm": "Mattermost room"}


def test_a_post_to_a_room_without_a_connection_uses_the_plain_route() -> None:
    """A subscriber of an old ticket whose support room is no longer linked still hears."""
    seen, _ = run_posts(
        [Post("room-gone", "Asha, BL-1 is fixed", thread_id="m1")],
        lambda path, body: httpx.Response(200, json={"ok": True, "event_id": "e9"}),
    )
    assert seen == [
        ("/agents/agent-1/message", "", {"room_id": "room-gone", "content": "Asha, BL-1 is fixed"})
    ]
