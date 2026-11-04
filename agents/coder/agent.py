"""Run a coder agent: `python agent.py` (or `--register` once), with CODER_ROLE set.

Switch Console cannot run managed coding agents on Windows, so `bugline-repro` and `bugline-fixer`
are custom agents like the front desk. Each holds one connection to the eng room and takes its
role there on every connect. For each message addressed to it, it posts "working on it" in the
thread, runs Claude Code headless in its own working directory with its brief as the system
prompt, and posts Claude Code's answer in the same thread. Jobs run one at a time; a message
that arrives during a job is told it is queued. A failed or slow run posts one line and the
agent carries on.

Who may address the agent is Switch's job (the access rule in Console); the brief is the second
line. The code adds no gate of its own beyond passing the sender's name to Claude Code.
"""

import argparse
import asyncio
import logging
import shutil
import sys
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path

# agents/, so the shared package `common` imports when this runs as `python agent.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.conventions import TICKET_ID_RE, format_ticket_id
from common.loop import run
from common.switch_client import (
    IncomingMessage,
    OpError,
    RoomConnection,
    SwitchApi,
    connection_id_for,
    load_credentials,
    register,
)

import config
from claude_runner import ClaudeResult, build_prompt, claude_command, run_claude, trim_reply

log = logging.getLogger("coder")

# Ops the agent cannot work without; checked against GET /agents/{id}/ops at startup.
REQUIRED_OPS = ("assume_role", "post_message", "read_context")
WORKING = "Working on it. This runs Claude Code and can take a few minutes."

Runner = Callable[[str], Awaitable[ClaudeResult]]


def ticket_in(*texts: str) -> str | None:
    """The first ticket id (`BL-n`) in `texts`, or None."""
    for text in texts:
        if match := TICKET_ID_RE.search(text):
            return format_ticket_id(int(match.group(1)))
    return None


class Coder:
    """Takes the role on each connect, queues addressed messages, and runs one job at a time."""

    def __init__(
        self,
        settings: config.Settings,
        api: SwitchApi,
        connection: RoomConnection,
        runner: Runner,
    ) -> None:
        self.settings = settings
        self.api = api
        self.connection = connection
        self.runner = runner
        self.jobs: asyncio.Queue[IncomingMessage] = asyncio.Queue()
        self.current: str | None = None  # what the running job is about, e.g. "BL-1"

    async def keep_role(self) -> None:
        """Take the role after every (re)connect. Taking a role you already hold is a no-op."""
        while True:
            await self.connection.connected.wait()
            self.connection.connected.clear()
            try:
                await self.api.call(
                    "assume_role", self.connection.connection_id, role=self.settings.role
                )
                log.info("holding the role %s", self.settings.role)
            except OpError as exc:
                log.error("could not take the role %s: %s", self.settings.role, exc)

    async def intake(self, incoming: asyncio.Queue[IncomingMessage]) -> None:
        """Queue every addressed message; tell the sender if it has to wait."""
        while True:
            msg = await incoming.get()
            log.info("%s says %r", msg.sender_name, msg.body[:80])
            if self.current is not None or not self.jobs.empty():
                await self._post(f"Busy with {self.current or 'another request'}, queued.", msg)
            await self.jobs.put(msg)

    async def work(self) -> None:
        """Run queued jobs one at a time, forever. One bad job never stops the loop."""
        while True:
            msg = await self.jobs.get()
            self.current = ticket_in(msg.body) or "another request"
            try:
                await self.handle(msg)
            except Exception:
                log.exception("job for message %s failed", msg.message_id)
                await self._post("Something went wrong on my side; it is in the agent's log.", msg)
            finally:
                self.current = None

    async def handle(self, msg: IncomingMessage) -> None:
        await self._post(WORKING, msg)
        thread = await self.thread_before(msg)
        self.current = ticket_in(msg.body, *(str(e.get("body", "")) for e in thread)) or (
            self.current
        )
        result = await self.runner(build_prompt(self.settings, msg, thread))
        log.info("claude answered (ok=%s):\n%s", result.ok, result.text)
        if result.ok:
            await self._post(trim_reply(result.text), msg)
        else:
            await self._post(f"Could not finish: {result.text[:300]}", msg)

    async def thread_before(self, msg: IncomingMessage) -> list[dict]:
        """The messages in `msg`'s thread before it, oldest first. Empty if it cannot be read."""
        try:
            data = await self.api.call(
                "read_context", self.connection.connection_id, limit=config.THREAD_READ_LIMIT
            )
        except OpError as exc:
            log.warning("could not read the thread: %s", exc)
            return []
        for thread in (data or {}).get("threads", []):
            root = thread.get("root") or {}
            if root.get("id") == msg.thread_root:
                entries = [root, *thread.get("replies", [])]
                return [
                    e
                    for e in entries
                    if e.get("id") != msg.message_id and e.get("kind", "message") == "message"
                ]
        return []

    async def _post(self, body: str, msg: IncomingMessage) -> None:
        """Reply in `msg`'s thread. A failed post is logged, never raised."""
        try:
            await self.api.post(
                self.connection.connection_id, self.connection.room_id, body, msg.thread_root
            )
        except (OpError, OSError) as exc:
            log.error("could not post %r: %s", body[:60], exc)


async def serve(settings: config.Settings) -> None:
    claude_path = shutil.which(settings.claude_bin)
    if not claude_path:
        raise RuntimeError(f"{settings.claude_bin} not found; set CODER_CLAUDE_BIN")
    if not settings.brief.is_file():
        raise RuntimeError(f"brief {settings.brief} not found; set CODER_BRIEF")
    if not settings.clone.is_dir():
        raise RuntimeError(f"{settings.clone} not found; clone the repo there (see README.md)")

    base_url = config.switch_api_url()
    creds = load_credentials(settings.credentials_path)
    api = SwitchApi(base_url, creds)
    log.info("bridge %s: %s", base_url, await api.health())
    ops = await api.list_ops()
    if missing := [op for op in REQUIRED_OPS if op not in ops]:
        raise RuntimeError(f"bridge does not offer {missing}")

    connection_id = connection_id_for(config.ENG_ROOM, settings.connections_path)
    connection = RoomConnection(
        config.ENG_ROOM, config.eng_room_id(), creds, base_url, connection_id
    )
    cmd = claude_command(settings, claude_path)
    log.info("%s in %s runs: %s", settings.agent_name, settings.clone, " ".join(cmd))
    runner = partial(run_claude, cmd, cwd=str(settings.clone), timeout_s=settings.timeout_s)
    coder = Coder(settings, api, connection, runner)
    incoming: asyncio.Queue[IncomingMessage] = asyncio.Queue()
    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(connection.run(incoming))
            tasks.create_task(coder.keep_role())
            tasks.create_task(coder.intake(incoming))
            tasks.create_task(coder.work())
    finally:
        await api.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--register", action="store_true", help="register with Switch once")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise

    try:
        settings = config.settings()
        if args.register:
            url, key = config.switch_api_url(), config.require_env(config.REGISTRATION_KEY_ENV)
            path = settings.credentials_path
            creds = register(url, key, settings.agent_name, settings.description, path)
            print(f"Registered {settings.agent_name} as agent {creds.agent_id}.")
            print(f"Its id and API key are saved in {path}.")
        else:
            run(serve(settings))
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OpError) as exc:  # setup problems: one readable line, no traceback
        log.error("%s", exc)
        return 1
    except Exception:
        log.exception("coder stopped")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
