"""Run the front desk: `python agent.py` (or `--register` once, `--list-rooms` to find room ids).

Connects to the support room, finds the eng room through the support room's `escalates to`
link, and connects there too: one Switch connection per room. It hands each addressed message
to handlers.py and carries out the posts it returns. Messages are handled one at a time on a
single worker thread: the Gemini SDK and sqlite3 are blocking, and one thread keeps ticket
numbers and drafts consistent while the event loop keeps answering pings. A message that fails
is logged and skipped.
"""

import argparse
import asyncio
import logging
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

# agents/, so the shared package `common` imports when this runs as `python agent.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.loop import run
from common.switch_client import (
    IncomingMessage,
    OpError,
    RoomConnection,
    SwitchApi,
    connection_id_for,
    load_credentials,
    reached,
    register,
)

import config
import handlers
from handlers import Post
from store import Store

log = logging.getLogger("frontdesk")

# Ops the agent cannot work without; checked against GET /agents/{id}/ops at startup.
REQUIRED_OPS = ("post_message", "send_targeted_message", "list_linked_rooms")


class Poster:
    """Carries out `Post` actions with the connection of the room each one targets."""

    def __init__(self, api: SwitchApi, connections: dict[str, RoomConnection]) -> None:
        self.api = api
        self.connections = connections
        self.sent: deque[str] = deque(maxlen=500)  # our own event ids, so we never answer ourselves

    async def run_each(self, posts: list[Post]) -> None:
        """Carry out `posts` in order. One that fails is logged, and the rest still go out: a
        close's `Closed BL-n` reply must not take the reporters' "fixed" messages down with it."""
        for post in posts:
            try:
                await self.run(post)
            except Exception:
                log.exception("could not post to %s: %r", post.room, post.body[:80])

    async def run(self, post: Post) -> None:
        if not (post.target_roles or post.target_names):
            await self._post(post.room, post.body, post.thread_id)
            return
        try:
            result = await self.api.send_targeted(
                self.connections[post.room].connection_id,
                post.body,
                post.thread_id,
                roles=post.target_roles,
                names=post.target_names,
            )
        except OpError as exc:
            log.warning("targeted message failed (%s); posting it plainly", exc)
            await self._post(post.room, post.body, post.thread_id)
            return
        self._remember(result)
        log.info("%s -> %s", post.room, result.get("target_statuses") or "no live target")
        if post.if_unreachable and not reached(result):
            await self._post(post.room, post.if_unreachable, result.get("event_id"))

    async def _post(self, room: str, body: str, thread_id: str | None) -> None:
        connection = self.connections[room]
        result = await self.api.post(connection.connection_id, connection.room_id, body, thread_id)
        self._remember(result)
        log.info("%s <- %s", room, body.splitlines()[0][:80])

    def _remember(self, result: dict | None) -> None:
        if result and result.get("event_id"):
            self.sent.append(result["event_id"])


async def verifier_names(api: SwitchApi) -> frozenset[str]:
    """The name of the agent whose `Verified BL-n` closes a ticket: the reproducer.

    Bootstrap writes its agent id to .env. A message names its sender by participant id, not agent
    id, so the front desk asks Switch once for the name that agent id has. If the id is missing or
    the lookup fails, no agent can close a ticket and only the room owner can.
    """
    agent_id = config.verifier_agent_id()
    if not agent_id:
        log.warning(
            "%s is not set, so only the room owner can close tickets; run scripts/bootstrap.py",
            config.VERIFIER_AGENT_ID_ENV,
        )
        return frozenset()
    try:
        name = ((await api.call("get_agent_detail", agent_id=agent_id)) or {}).get("name")
    except OpError as exc:
        log.warning("could not look up agent %s (%s); only the room owner can close", agent_id, exc)
        return frozenset()
    log.info("tickets close on `Verified` from %s or from the room owner", name)
    return frozenset({name} if name else ())


async def escalation_room(api: SwitchApi, support: RoomConnection) -> str:
    """The eng room's id: where the support room's `escalates to` link points.

    Asked of Switch once the support connection is up, since the op works on a connected room.
    The link must be the only one with that label and point at a room the front desk is in;
    otherwise the front desk stops, because it would not know where to send reports.
    """
    await support.connected.wait()
    links = await api.call("list_linked_rooms", support.connection_id) or []
    targets = [
        link["target_room_id"]
        for link in links
        if link.get("label") == config.ESCALATION_LINK and link.get("access") == "member"
    ]
    if len(targets) != 1:
        raise RuntimeError(
            f"{config.ROOM_NAMES[config.ROOM_SUPPORT]} has {len(targets)}"
            f" '{config.ESCALATION_LINK}' links to a room this agent is in; it needs exactly one."
            " Run scripts/bootstrap.py"
        )
    log.info("reports go where the '%s' link points: room %s", config.ESCALATION_LINK, targets[0])
    return targets[0]


async def dispatch(
    queue: asyncio.Queue[IncomingMessage],
    store: Store,
    poster: Poster,
    worker: ThreadPoolExecutor,
    verifiers: frozenset[str] = frozenset(),
) -> None:
    """Handle queued messages one at a time, forever. One bad message never stops the loop."""
    loop = asyncio.get_running_loop()
    handle = partial(handlers.handle, verifiers=verifiers)
    while True:
        msg = await queue.get()
        if msg.message_id in poster.sent:
            continue
        log.info("%s: %s says %r", msg.room, msg.sender_name, msg.body[:80])
        try:
            posts = await loop.run_in_executor(worker, handle, msg, store)
        except Exception:
            log.exception("could not handle message %s", msg.message_id)
            continue
        await poster.run_each(posts)


async def serve() -> None:
    base_url = config.switch_api_url()
    creds = load_credentials(config.CREDENTIALS_PATH)
    api = SwitchApi(base_url, creds)
    log.info("bridge %s: %s", base_url, await api.health())
    ops = await api.list_ops()
    log.info("%d ops available: %s", len(ops), ", ".join(ops))
    if missing := [op for op in REQUIRED_OPS if op not in ops]:
        raise RuntimeError(f"bridge does not offer {missing}")
    verifiers = await verifier_names(api)

    def connection(room: str, room_id: str) -> RoomConnection:
        return RoomConnection(
            room, room_id, creds, base_url, connection_id_for(room, config.CONNECTIONS_PATH)
        )

    support = connection(config.ROOM_SUPPORT, config.support_room_id())
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="handlers")
    # sqlite3 objects stay on the thread that made them, so the store is made on the worker.
    store = await asyncio.get_running_loop().run_in_executor(worker, Store)
    queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(support.run(queue))
            eng = connection(config.ROOM_ENG, await escalation_room(api, support))
            tasks.create_task(eng.run(queue))
            connections = {config.ROOM_SUPPORT: support, config.ROOM_ENG: eng}
            tasks.create_task(dispatch(queue, store, Poster(api, connections), worker, verifiers))
    finally:
        await api.aclose()
        worker.shutdown(wait=False)


async def list_rooms() -> None:
    api = SwitchApi(config.switch_api_url(), load_credentials(config.CREDENTIALS_PATH))
    try:
        rooms = await api.call("list_rooms")
        if isinstance(rooms, dict):  # the result shape is not documented; accept {"rooms": [...]}
            rooms = rooms.get("rooms", [])
        for room in rooms or []:
            print(f"{room.get('id')}  {room.get('name')}")
    finally:
        await api.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--register", action="store_true", help="register with Switch once")
    parser.add_argument("--list-rooms", action="store_true", help="print the agent's room ids")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise

    try:
        if args.register:
            url, key = config.switch_api_url(), config.require_env(config.REGISTRATION_KEY_ENV)
            creds = register(
                url, key, config.AGENT_NAME, config.AGENT_DESCRIPTION, config.CREDENTIALS_PATH
            )
            print(f"Registered {config.AGENT_NAME} as agent {creds.agent_id}.")
            print(f"Its id and API key are saved in {config.CREDENTIALS_PATH}.")
        else:
            run(list_rooms() if args.list_rooms else serve())
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OpError) as exc:  # setup problems: one readable line, no traceback
        log.error("%s", exc)
        return 1
    except Exception:
        log.exception("front desk stopped")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
