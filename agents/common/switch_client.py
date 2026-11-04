"""The Switch agent protocol for Bugline's agents: register once, one WebSocket per room, ops.

Switch has no Python client library, so this follows the protocol pages of the docs
(docs.switchagents.ai: agent-protocol, agent-connection, agent-events). One connection covers one
room, so an agent opens one `RoomConnection` per room it works in, and every op call carries the
connection id of the room it acts in. The front desk and the coder agents both use this module;
it knows nothing about tickets, Gemini or Claude Code, and each agent passes in its own name and
file paths.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

log = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 30.0
RECONNECT_START_S = 1.0  # WebSocket reconnect backoff, doubled up to the cap
RECONNECT_CAP_S = 30.0
# send_targeted_message statuses that mean the target will see the message.
REACHABLE_STATUSES = frozenset({"live", "awaiting_manual_poll"})


@dataclass(frozen=True)
class Credentials:
    agent_id: str
    api_key: str


@dataclass(frozen=True)
class IncomingMessage:
    """An addressed `message` event, cut down to the fields the handlers use."""

    room: str  # the agent's own key for the room, as given to RoomConnection
    room_id: str
    sender_id: str  # opaque participant id; compare it, never parse it
    sender_name: str
    body: str
    message_id: str  # pass as thread_id to reply under this message
    thread_id: str | None  # thread root, or None for a top-level message
    # The sending person's role in the workspace ("owner", "admin" or "member"), which Switch
    # reads fresh for each message. None for an agent, or for a chat account no Switch user claimed.
    sender_role: str | None = None

    @property
    def thread_root(self) -> str:
        return self.thread_id or self.message_id


class OpError(Exception):
    """A Switch HTTP call failed. `status` is the HTTP status (409: dead connection id)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status


class ConnectionStopped(Exception):
    """The server refused or ended a connection in a way that retrying will not fix."""


# --- registration and local state -----------------------------------------------------------


def register(
    base_url: str,
    registration_key: str,
    name: str,
    description: str,
    path: Path,
    transport: httpx.BaseTransport | None = None,
) -> Credentials:
    """Register the agent once with `POST /agents` and save its id and API key to `path`.

    Refuses if credentials already exist: registering again is a 409, and `overwrite` would
    issue a new key and break the old one, so it is never used.
    """
    if path.exists():
        raise RuntimeError(f"{path} exists; the agent is already registered")
    body = {
        "name": name,
        "description": description,
        "connector_type": "custom",
        "integration_profile": {
            "connection_model": "session_addressable",
            "message_exchange": True,
            "pre_invocation_mediation": [],
            "post_invocation_mediation": [],
            "event_reporting": [],
        },
    }
    with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT_S) as client:
        response = client.post(
            f"{base_url}/agents",
            json=body,
            headers={"Authorization": f"Bearer {registration_key}"},
        )
    _raise_for_status(response)
    data = response.json()
    creds = Credentials(agent_id=data["id"], api_key=data["api_key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": creds.agent_id, "api_key": creds.api_key}), encoding="utf-8")
    return creds


def load_credentials(path: Path) -> Credentials:
    if not path.exists():
        raise RuntimeError(f"{path} not found; run `python agent.py --register` first")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Credentials(agent_id=data["id"], api_key=data["api_key"])


def connection_id_for(room: str, path: Path) -> str:
    """The connection id for a room key, created once and reused on every reconnect and restart."""
    ids = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if room not in ids:
        ids[room] = str(uuid.uuid4())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    return ids[room]


# --- operations -----------------------------------------------------------------------------


class SwitchApi:
    """HTTP calls made with the agent's API key: health, op discovery, ops, plain messages."""

    def __init__(
        self, base_url: str, creds: Credentials, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.agent_id = creds.agent_id
        self._http = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=HTTP_TIMEOUT_S,
            headers={"Authorization": f"Bearer {creds.api_key}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> dict[str, Any]:
        """`GET /health` answers {"status": "ok"} only on the bridge, so it checks the URL."""
        return await self._request("GET", "/health")

    async def list_ops(self) -> list[str]:
        data = await self._request("GET", f"/agents/{self.agent_id}/ops")
        return sorted(data.get("operations", {}))

    async def call(self, op: str, connection_id: str | None = None, **args: Any) -> Any:
        """Invoke an op. The body is the bare arguments; None values are left out.

        `connection_id` binds the call to that connection's room, which room-scoped ops such as
        post_message need.
        """
        headers = {"X-Switch-Connection-Id": connection_id} if connection_id else {}
        body = {key: value for key, value in args.items() if value is not None}
        data = await self._request(
            "POST", f"/agents/{self.agent_id}/ops/{op}", json=body, headers=headers
        )
        return data.get("result")

    async def post(
        self, connection_id: str, room_id: str, body: str, thread_id: str | None = None
    ) -> dict[str, Any]:
        """`post_message` in the connection's room. If the connection is down (409), post through
        `post_without_connection` instead, which cannot thread but does not lose the message."""
        try:
            return await self.call("post_message", connection_id, body=body, thread_id=thread_id)
        except OpError as exc:
            if exc.status != 409:
                raise
            return await self.post_without_connection(room_id, body)

    async def send_targeted(
        self,
        connection_id: str,
        body: str,
        thread_id: str | None = None,
        roles: tuple[str, ...] = (),
        names: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """`send_targeted_message`: Switch puts `@role` / `@name` in front of `body` and answers
        `{"event_id", "target_statuses": {agent name: status}}`, which `reached` reads."""
        result = await self.call(
            "send_targeted_message",
            connection_id,
            body=body,
            target_roles=list(roles) or None,
            target_names=list(names) or None,
            thread_id=thread_id,
        )
        return result or {}

    async def post_without_connection(self, room_id: str, content: str) -> dict[str, Any]:
        """`POST /agents/{id}/message`: posts with no live connection, but cannot thread."""
        return await self._request(
            "POST",
            f"/agents/{self.agent_id}/message",
            json={"room_id": room_id, "content": content},
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._http.request(method, url, **kwargs)
        _raise_for_status(response)
        return response.json()


def reached(result: dict[str, Any]) -> bool:
    """Whether any agent a targeted message named will see it. A role nobody holds lists no one."""
    statuses = result.get("target_statuses") or {}
    return bool(set(statuses.values()) & REACHABLE_STATUSES)


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        detail = str(response.json().get("detail", response.text))
    except ValueError:
        detail = response.text
    raise OpError(response.status_code, detail)


# --- the WebSocket per room -----------------------------------------------------------------

# Eviction codes after which reconnecting is wrong: another process owns the connection, or the
# server closed it for a reason a person must look at (agent deleted, room not servable).
STOP_EVICTIONS = {"taken_over", "closed"}
# 4400 bad parameters, 4401 bad key, 4403 room not servable, 4409 taken over or already claimed.
STOP_CLOSE_CODES = range(4400, 4500)


class RoomConnection:
    """One WebSocket that claims one room, answers pings, and queues addressed messages.

    Reading runs in its own task and only puts messages on a queue, so a slow handler (a model
    call with backoff can take a minute) never delays a pong; the server drops a connection that
    has not answered for 6 seconds.
    """

    def __init__(
        self, room: str, room_id: str, creds: Credentials, base_url: str, connection_id: str
    ) -> None:
        self.room = room
        self.room_id = room_id
        self.connection_id = connection_id
        self.cursor: int | None = None  # sequence of the last event seen; sent with every pong
        self.generation: int | None = None
        self.rooms: list[str] = []
        self._creds = creds
        self._ws_base = base_url.replace("http", "ws", 1)  # http->ws, https->wss
        self._eviction: str | None = None
        # Set on every connection_state, so an agent can redo per-connection setup (taking its
        # role) after each reconnect. Whoever waits on it clears it.
        self.connected = asyncio.Event()

    def url(self) -> str:
        """Connection id and room go in the query; a reconnect resumes from the cursor."""
        query: dict[str, Any] = {"connection_id": self.connection_id, "rooms": self.room_id}
        if self.cursor is not None:
            query["start_from"] = self.cursor
        if self.generation is not None:
            query["expected_generation"] = self.generation
        return f"{self._ws_base}/agents/{self._creds.agent_id}/connection/ws?{urlencode(query)}"

    async def run(
        self,
        queue: asyncio.Queue[IncomingMessage],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Stay connected forever, reconnecting with backoff. Raises ConnectionStopped when the
        server says retrying will not help."""
        delay = RECONNECT_START_S
        headers = {"Authorization": f"Bearer {self._creds.api_key}"}
        while True:
            code: int | None = None
            self._eviction = None
            try:
                async with connect(self.url(), additional_headers=headers) as ws:
                    await self._read(ws, queue)
                    code = ws.close_code
                    delay = RECONNECT_START_S  # the server ended a working connection
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
            except (OSError, InvalidHandshake, TimeoutError) as exc:
                log.warning("%s: cannot connect: %s", self.room, exc)
            if self._eviction in STOP_EVICTIONS or code in STOP_CLOSE_CODES:
                raise ConnectionStopped(
                    f"{self.room}: stopped (eviction={self._eviction}, close code={code})"
                )
            log.warning("%s: disconnected (code %s); reconnecting in %.0fs", self.room, code, delay)
            await sleep(delay)
            delay = min(delay * 2, RECONNECT_CAP_S)

    async def _read(self, ws: Any, queue: asyncio.Queue[IncomingMessage]) -> None:
        async for raw in ws:
            try:
                frame = json.loads(raw)
            except ValueError:
                log.warning("%s: ignoring a frame that is not JSON: %.80r", self.room, raw)
                continue
            event, data = frame.get("event"), frame.get("data") or {}
            if event == "ping":
                await ws.send(json.dumps({"type": "pong", "cursor": self.cursor}))
            elif event == "connection_state":
                self.rooms, self.cursor = data.get("rooms", []), data.get("cursor")
                self.generation = data.get("generation")
                log.info("%s: connected, rooms=%s cursor=%s", self.room, self.rooms, self.cursor)
                if self.room_id not in self.rooms:
                    log.warning("%s: the server did not give us room %s", self.room, self.room_id)
                self.connected.set()
            elif event == "gap":
                self.cursor = data.get("resumed_at", self.cursor)
                log.warning("%s: missed events (%s); resumed at %s", self.room, data, self.cursor)
            elif event in ("evicted", "refused"):
                self._eviction = data.get("code")
                log.error("%s: %s %s", self.room, event, data)
            elif "id" in frame:  # a domain event: message, command, room_join
                self.cursor = frame["id"]
                message = self._parse(data) if event == "message" else None
                if message:
                    await queue.put(message)

    def _parse(self, data: dict[str, Any]) -> IncomingMessage | None:
        """Only messages addressed to this agent are handed on; the rest is room chatter."""
        payload = data.get("payload") or {}
        if payload.get("addressed") is not True:
            return None
        return IncomingMessage(
            room=self.room,
            room_id=data.get("room_id") or self.room_id,
            sender_id=payload.get("sender", ""),
            sender_name=payload.get("sender_name") or "",
            body=payload.get("body", ""),
            message_id=payload.get("message_id", ""),
            thread_id=payload.get("thread_id"),
            sender_role=payload.get("sender_role"),
        )
