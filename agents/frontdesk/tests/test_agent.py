"""Tests for how agent.py carries out posts: op choice, threading and the two fallbacks."""

import asyncio
import json

import httpx

import config
from agent import Poster
from handlers import Post
from switch_client import Credentials, RoomConnection, SwitchApi

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
