"""Run the front desk: `python agent.py` (or `--register` once, `--list-rooms` to find room ids).

Opens one Switch connection per room, hands each addressed message to handlers.py and carries
out the posts it returns. Messages are handled one at a time on a single worker thread: the
Gemini SDK and sqlite3 are blocking, and one thread keeps ticket numbers and drafts consistent
while the event loop keeps answering pings. A message that fails is logged and skipped.
"""

import argparse
import asyncio
import logging
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import config
import handlers
from handlers import Post
from store import Store
from switch_client import (
    IncomingMessage,
    OpError,
    RoomConnection,
    SwitchApi,
    connection_id_for,
    load_credentials,
    register,
)

log = logging.getLogger("frontdesk")

# Ops the agent cannot work without; checked against GET /agents/{id}/ops at startup.
REQUIRED_OPS = ("post_message", "send_targeted_message")


class Poster:
    """Carries out `Post` actions with the connection of the room each one targets."""

    def __init__(self, api: SwitchApi, connections: dict[str, RoomConnection]) -> None:
        self.api = api
        self.connections = connections
        self.sent: deque[str] = deque(maxlen=500)  # our own event ids, so we never answer ourselves

    async def run(self, post: Post) -> None:
        if not (post.target_roles or post.target_names):
            await self._post(post.room, post.body, post.thread_id)
            return
        try:
            result = await self.api.call(
                "send_targeted_message",
                self.connections[post.room].connection_id,
                body=post.body,
                target_roles=list(post.target_roles) or None,
                target_names=list(post.target_names) or None,
                thread_id=post.thread_id,
            )
        except OpError as exc:
            log.warning("targeted message failed (%s); posting it plainly", exc)
            await self._post(post.room, post.body, post.thread_id)
            return
        self._remember(result)
        statuses = result.get("target_statuses") or {}
        log.info("%s -> %s", post.room, statuses or "no live target")
        if post.if_unreachable and not set(statuses.values()) & config.REACHABLE_STATUSES:
            await self._post(post.room, post.if_unreachable, result.get("event_id"))

    async def _post(self, room: str, body: str, thread_id: str | None) -> None:
        connection = self.connections[room]
        try:
            result = await self.api.call(
                "post_message", connection.connection_id, body=body, thread_id=thread_id
            )
        except OpError as exc:
            if exc.status != 409:  # 409: the connection is down; post without it, unthreaded
                raise
            result = await self.api.post_without_connection(connection.room_id, body)
        self._remember(result)
        log.info("%s <- %s", room, body.splitlines()[0][:80])

    def _remember(self, result: dict | None) -> None:
        if result and result.get("event_id"):
            self.sent.append(result["event_id"])


async def dispatch(
    queue: asyncio.Queue[IncomingMessage], store: Store, poster: Poster, worker: ThreadPoolExecutor
) -> None:
    """Handle queued messages one at a time, forever. One bad message never stops the loop."""
    loop = asyncio.get_running_loop()
    while True:
        msg = await queue.get()
        if msg.message_id in poster.sent:
            continue
        log.info("%s: %s says %r", msg.room, msg.sender_name, msg.body[:80])
        try:
            posts = await loop.run_in_executor(worker, handlers.handle, msg, store)
            for post in posts:
                await poster.run(post)
        except Exception:
            log.exception("could not handle message %s", msg.message_id)


async def serve() -> None:
    base_url = config.switch_api_url()
    creds = load_credentials()
    api = SwitchApi(base_url, creds)
    log.info("bridge %s: %s", base_url, await api.health())
    ops = await api.list_ops()
    log.info("%d ops available: %s", len(ops), ", ".join(ops))
    if missing := [op for op in REQUIRED_OPS if op not in ops]:
        raise RuntimeError(f"bridge does not offer {missing}")

    connections = {
        room: RoomConnection(room, room_id, creds, base_url, connection_id_for(room))
        for room, room_id in config.room_ids().items()
    }
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="handlers")
    # sqlite3 objects stay on the thread that made them, so the store is made on the worker.
    store = await asyncio.get_running_loop().run_in_executor(worker, Store)
    queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
    try:
        async with asyncio.TaskGroup() as tasks:
            for connection in connections.values():
                tasks.create_task(connection.run(queue))
            tasks.create_task(dispatch(queue, store, Poster(api, connections), worker))
    finally:
        await api.aclose()
        worker.shutdown(wait=False)


async def list_rooms() -> None:
    api = SwitchApi(config.switch_api_url(), load_credentials())
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
            creds = register(url, key)
            print(f"Registered {config.AGENT_NAME} as agent {creds.agent_id}.")
            print(f"Its id and API key are saved in {config.CREDENTIALS_PATH}.")
        else:
            asyncio.run(list_rooms() if args.list_rooms else serve())
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
