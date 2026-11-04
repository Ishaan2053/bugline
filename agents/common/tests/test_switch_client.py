"""Tests for the Switch client: a local WebSocket server stands in for the bridge, and
httpx.MockTransport stands in for the HTTP routes. Nothing leaves the machine."""

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from common.switch_client import (
    ConnectionStopped,
    Credentials,
    IncomingMessage,
    OpError,
    RoomConnection,
    SwitchApi,
    connection_id_for,
    register,
)
from websockets.asyncio.server import serve

CREDS = Credentials(agent_id="agent-1", api_key="key-1")


def frame(event: str, data: dict, seq: int | None = None) -> str:
    out = {"event": event, "data": data}
    if seq is not None:
        out["id"] = seq
    return json.dumps(out)


def message(seq: int, body: str, addressed: bool) -> str:
    payload = {
        "addressed": addressed,
        "sender": "@switch-user-ab12:localhost",
        "sender_name": "Asha",
        "sender_kind": "user",
        "message_id": f"m{seq}",
        "body": body,
        "thread_id": None,
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
    assert queued[0] == IncomingMessage(
        "support", "room-s", "@switch-user-ab12:localhost", "Asha", queued[0].body, "m12", None
    )
    assert conn.rooms == ["room-s"] and conn.generation == 3
    request = opens[0]
    assert request.headers["Authorization"] == "Bearer key-1"
    assert urlsplit(request.path).path == "/agents/agent-1/connection/ws"
    assert parse_qs(urlsplit(request.path).query) == {"connection_id": ["c-1"], "rooms": ["room-s"]}


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
