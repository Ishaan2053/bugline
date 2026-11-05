"""Tests for how agent.py carries out posts (op choice, threading and the two fallbacks) and how
it finds the verifier's name at start."""

import asyncio
import json

import httpx
import pytest
from common.switch_client import Credentials, RoomConnection, SwitchApi

import config
from agent import Poster, verifier_names
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
