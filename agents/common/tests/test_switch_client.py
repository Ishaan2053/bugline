"""Tests for the Switch client: a local WebSocket server stands in for the bridge, and
httpx.MockTransport stands in for the HTTP routes. Nothing leaves the machine."""

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from common.conventions import VERDICT_RE, VERIFIED, VERIFY_REQUEST_RE, without_mentions
from common.switch_client import (
    ConnectionStopped,
    Credentials,
    IncomingMessage,
    OpError,
    RoomConnection,
    SwitchApi,
    connection_id_for,
    reached,
    register,
)
from websockets.asyncio.server import serve

CREDS = Credentials(agent_id="agent-1", api_key="key-1")


def frame(event: str, data: dict, seq: int | None = None) -> str:
    out = {"event": event, "data": data}
    if seq is not None:
        out["id"] = seq
    return json.dumps(out)


def message(seq: int, body: str, addressed: bool, sent: float | None = None) -> str:
    """A message event; `sent` is its time in epoch seconds (now when left out)."""
    payload = {
        "addressed": addressed,
        "sender": "@switch-user-ab12:localhost",
        "sender_name": "Asha",
        "sender_kind": "user",
        "sender_role": "owner",
        "message_id": f"m{seq}",
        "body": body,
        "thread_id": None,
        "timestamp": int((time.time() if sent is None else sent) * 1000),
    }
    data = {"type": "message", "room_id": "room-s", "payload": payload, "sequence": seq}
    return frame("message", data, seq)


def run_against(server_script, opens: list) -> tuple[list[IncomingMessage], RoomConnection]:
    """Run a RoomConnection against a local server until it stops; return what it queued."""

    async def main() -> tuple[list[IncomingMessage], RoomConnection]:
        async def handler(ws):
            opens.append(ws.request)
            await server_script(ws, len(opens))

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            conn = RoomConnection("support", "room-s", CREDS, f"http://127.0.0.1:{port}", "c-1")
            queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()

            async def no_wait(_: float) -> None:
                return None

            with pytest.raises(ConnectionStopped):
                await asyncio.wait_for(conn.run(queue, sleep=no_wait), timeout=5)
            return [queue.get_nowait() for _ in range(queue.qsize())], conn

    return asyncio.run(main())


def test_pong_carries_cursor_and_only_addressed_messages_are_queued() -> None:
    pongs: list[dict] = []

    async def script(ws, _attempt: int) -> None:
        state = {"connection_id": "c-1", "generation": 3, "rooms": ["room-s"], "cursor": 10}
        await ws.send(frame("connection_state", state))
        await ws.send(frame("ping", {}))
        pongs.append(json.loads(await ws.recv()))
        await ws.send(message(11, "just chatting", addressed=False))
        await ws.send(message(12, "@frontdesk the share link errors", addressed=True))
        await ws.send(frame("ping", {}))
        pongs.append(json.loads(await ws.recv()))
        await ws.close(4401, "stop the test")

    opens: list = []
    queued, conn = run_against(script, opens)

    assert pongs == [{"type": "pong", "cursor": 10}, {"type": "pong", "cursor": 12}]
    assert [m.body for m in queued] == ["@frontdesk the share link errors"]
    # sender_role is what lets the front desk accept a close from the owner.
    assert queued[0] == IncomingMessage(
        "support",
        "room-s",
        "@switch-user-ab12:localhost",
        "Asha",
        queued[0].body,
        "m12",
        None,
        "owner",
        queued[0].timestamp_ms,
    )
    assert conn.rooms == ["room-s"] and conn.generation == 3
    assert conn.connected.is_set()  # what an agent waits on to take its role
    request = opens[0]
    assert request.headers["Authorization"] == "Bearer key-1"
    assert urlsplit(request.path).path == "/agents/agent-1/connection/ws"
    assert parse_qs(urlsplit(request.path).query) == {"connection_id": ["c-1"], "rooms": ["room-s"]}


def test_old_and_repeated_messages_are_not_handed_on(caplog) -> None:
    """What a server that re-delivers history sends: an approval from hours ago, and a message
    that already arrived on this connection."""
    hours_ago = time.time() - 3 * 3600

    async def script(ws, _attempt: int) -> None:
        await ws.send(frame("connection_state", {"rooms": ["room-s"], "cursor": 10}))
        await ws.send(message(11, "@fixer go on BL-3", addressed=True, sent=hours_ago))
        await ws.send(message(12, "@frontdesk the share link errors", addressed=True))
        await ws.send(message(12, "@frontdesk the share link errors", addressed=True))
        await ws.close(4401, "stop the test")

    queued, _ = run_against(script, [])

    assert [m.message_id for m in queued] == ["m12"]
    assert "ignored m11 from Asha, sent 180 min ago" in caplog.text
    assert "m12 was delivered again; ignored" in caplog.text


def test_reconnect_reuses_connection_id_and_resumes_from_cursor() -> None:
    async def script(ws, attempt: int) -> None:
        if attempt == 1:
            state = {"generation": 2, "rooms": ["room-s"], "cursor": 5}
            await ws.send(frame("connection_state", state))
            await ws.close(1011, "server hiccup")
        else:
            await ws.close(4409, "taken over")

    opens: list = []
    run_against(script, opens)

    assert len(opens) == 2
    query = parse_qs(urlsplit(opens[1].path).query)
    assert query == {
        "connection_id": ["c-1"],
        "rooms": ["room-s"],
        "start_from": ["5"],
        "expected_generation": ["2"],
    }


def test_reconnect_before_any_event_starts_at_the_head() -> None:
    """Cursor 0 means nothing was delivered. Sent back as start_from=0 it would replay the
    agent's whole history (seen live on Nov 6, when the server's database restarted)."""

    async def script(ws, attempt: int) -> None:
        if attempt == 1:
            state = {"generation": 2, "rooms": ["room-s"], "cursor": 0}
            await ws.send(frame("connection_state", state))
            await ws.close(1011, "server hiccup")
        else:
            await ws.close(4409, "taken over")

    opens: list = []
    run_against(script, opens)

    query = parse_qs(urlsplit(opens[1].path).query)
    assert "start_from" not in query
    assert query["expected_generation"] == ["2"]


def test_taken_over_eviction_stops() -> None:
    async def script(ws, attempt: int) -> None:
        await ws.send(frame("evicted", {"code": "taken_over", "reason": "another open"}))
        await ws.close(1000)

    opens: list = []
    run_against(script, opens)
    assert len(opens) == 1


# --- HTTP ---------------------------------------------------------------------------------


def mock_api(handler) -> SwitchApi:
    return SwitchApi("http://switch.test", CREDS, transport=httpx.MockTransport(handler))


def test_op_call_sends_bare_args_and_connection_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": {"event_id": "e1"}})

    async def main():
        api = mock_api(handler)
        try:
            return await api.call("post_message", "c-1", body="hi", thread_id=None)
        finally:
            await api.aclose()

    assert asyncio.run(main()) == {"event_id": "e1"}
    request = seen[0]
    assert request.url == "http://switch.test/agents/agent-1/ops/post_message"
    assert request.headers["X-Switch-Connection-Id"] == "c-1"
    assert request.headers["Authorization"] == "Bearer key-1"
    assert json.loads(request.content) == {"body": "hi"}  # None arguments are left out


# What `list_references` answers for a room with the kit attached (shape seen live on Nov 6).
ATTACHED = {
    "documents": [{"id": "d-room", "name": "room-notes.md"}],
    "packages": [
        {
            "name": "bugline-kit",
            "documents": [
                {"id": "d-intake", "name": "intake-rules.md"},
                {"id": "d-fix", "name": "fix-policy.md"},
            ],
        }
    ],
}


def read_documents(names: list[str], respond) -> tuple[dict[str, str], list[tuple[str, dict]]]:
    """Run room_documents against a bridge answering `respond(op, body)`; return it and calls."""
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        op = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        calls.append((op, body))
        return respond(op, body)

    async def main() -> dict[str, str]:
        api = mock_api(handler)
        try:
            return await api.room_documents("c-1", names)
        finally:
            await api.aclose()

    return asyncio.run(main()), calls


def test_room_documents_reads_packaged_documents_by_name() -> None:
    def respond(op: str, body: dict) -> httpx.Response:
        if op == "list_references":
            return httpx.Response(200, json={"result": ATTACHED})
        loaded = [{"id": i, "content": f"text of {i}"} for i in body["ids"]]
        return httpx.Response(200, json={"result": loaded})

    docs, calls = read_documents(["intake-rules.md", "not-attached.md"], respond)

    assert docs == {"intake-rules.md": "text of d-intake"}  # a missing name is left out
    assert calls == [("list_references", {}), ("load_internal_documents", {"ids": ["d-intake"]})]


def test_room_documents_is_empty_when_switch_cannot_answer() -> None:
    docs, _ = read_documents(["intake-rules.md"], lambda op, body: httpx.Response(500, json={}))
    assert docs == {}
    docs, calls = read_documents([], lambda op, body: httpx.Response(500, json={}))
    assert (docs, calls) == ({}, [])  # nothing wanted, nothing asked


def test_targeted_message_and_who_it_reached() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        result = {"event_id": "e1", "target_statuses": {"bugline-repro": "no_session"}}
        return httpx.Response(200, json={"result": result})

    async def main():
        api = mock_api(handler)
        try:
            return await api.send_targeted("c-1", "please verify BL-1", "t1", roles=("reproducer",))
        finally:
            await api.aclose()

    result = asyncio.run(main())
    assert seen == [
        {"body": "please verify BL-1", "target_roles": ["reproducer"], "thread_id": "t1"}
    ]
    assert not reached(result)
    assert reached({"target_statuses": {"a": "no_session", "b": "awaiting_manual_poll"}})
    assert not reached({"event_id": "e2"})  # a role nobody holds lists no one


def test_verify_request_and_verdict_lines() -> None:
    pr = "https://github.com/Ishaan2053/bugline/pull/21"
    request = VERIFY_REQUEST_RE.search(f"Please verify BL-3 on PR {pr} (branch fix/x)")
    assert request and request["number"] == "3" and request["pr_url"] == pr
    text = without_mentions(f"@bugline-frontdesk @frontdesk, Verified BL-3: {pr}\npytest: ok")
    verdict = VERDICT_RE.match(text)
    assert verdict and (verdict["verdict"], verdict["number"], verdict["rest"]) == (
        "Verified",
        "3",
        pr,
    )
    no = VERDICT_RE.match("Not verified BL-3: the share test still fails")
    assert no and no["verdict"].lower() == f"not {VERIFIED}"
    assert VERDICT_RE.match("I think Verified BL-3: x") is None  # the verdict starts the message


def test_op_error_and_op_discovery() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            ops = {"post_message": {}, "send_targeted_message": {}, "read_context": {}}
            return httpx.Response(200, json={"operations": ops})
        return httpx.Response(409, json={"detail": "unknown connection"})

    async def main():
        api = mock_api(handler)
        try:
            ops = await api.list_ops()
            with pytest.raises(OpError) as caught:
                await api.call("post_message", "dead", body="hi")
            return ops, caught.value
        finally:
            await api.aclose()

    ops, error = asyncio.run(main())
    assert ops == ["post_message", "read_context", "send_targeted_message"]
    assert error.status == 409
    assert "unknown connection" in str(error)


def test_register_saves_credentials_once(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "agent-9", "api_key": "secret"})

    path = tmp_path / "state" / "credentials.json"
    creds = register(
        "http://switch.test",
        "reg-key",
        "bugline-test",
        "A test agent",
        path,
        httpx.MockTransport(handler),
    )

    assert creds == Credentials("agent-9", "secret")
    assert json.loads(path.read_text()) == {"id": "agent-9", "api_key": "secret"}
    body = json.loads(seen[0].content)
    assert body["name"] == "bugline-test" and body["description"] == "A test agent"
    assert body["integration_profile"]["connection_model"] == "session_addressable"
    assert "overwrite" not in body
    assert seen[0].headers["Authorization"] == "Bearer reg-key"
    with pytest.raises(RuntimeError, match="already registered"):
        register("http://switch.test", "reg-key", "bugline-test", "", path)
    assert len(seen) == 1


def test_connection_ids_are_stable_per_room(tmp_path: Path) -> None:
    path = tmp_path / "connections.json"
    support = connection_id_for("support", path)
    eng = connection_id_for("eng", path)
    assert support != eng
    assert connection_id_for("support", path) == support
