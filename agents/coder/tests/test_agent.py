"""Tests for the coder's Switch side: a mock bridge (httpx.MockTransport) records every op call,
and a fake runner stands in for Claude Code."""

import asyncio
import json

import httpx
from common.switch_client import Credentials, IncomingMessage, RoomConnection, SwitchApi

from agent import WORKING, Coder
from claude_runner import ClaudeResult

CREDS = Credentials("agent-r", "key-r")
TICKET = {"id": "t1", "kind": "message", "sender_name": "bugline-frontdesk", "body": "BL-1: Share"}


def message(n: int, body: str, thread_id: str | None = "t1") -> IncomingMessage:
    return IncomingMessage("eng", "room-e", "@pm:x", "PM", body, f"m{n}", thread_id)


class FakeSwitch:
    """Answers ops like the bridge and records (op, connection id, body) for each call."""

    def __init__(self, threads: list[dict] | None = None) -> None:
        self.calls: list[tuple[str, str | None, dict]] = []
        self.threads = threads or []

    def handler(self, request: httpx.Request) -> httpx.Response:
        op = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content) if request.content else {}
        self.calls.append((op, request.headers.get("X-Switch-Connection-Id"), body))
        if op == "read_context":
            return httpx.Response(200, json={"result": {"threads": self.threads}})
        return httpx.Response(200, json={"result": {"event_id": f"e{len(self.calls)}"}})

    def posts(self) -> list[tuple[str, str | None]]:
        return [(b["body"], b.get("thread_id")) for op, _, b in self.calls if op == "post_message"]


def make_coder(settings, fake: FakeSwitch, runner) -> Coder:
    api = SwitchApi("http://switch.test", CREDS, transport=httpx.MockTransport(fake.handler))
    connection = RoomConnection("eng", "room-e", CREDS, "http://switch.test", "c-eng")
    return Coder(settings, api, connection, runner)


async def until(condition, timeout: float = 5) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


async def running(coder: Coder):
    """Start intake and work; return the incoming queue and the tasks to cancel."""
    incoming: asyncio.Queue[IncomingMessage] = asyncio.Queue()
    tasks = [asyncio.create_task(coder.intake(incoming)), asyncio.create_task(coder.work())]
    return incoming, tasks


async def stop(coder: Coder, tasks) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await coder.api.aclose()


def test_role_is_taken_on_every_connect(settings) -> None:
    fake = FakeSwitch()

    async def main() -> None:
        coder = make_coder(settings, fake, None)
        task = asyncio.create_task(coder.keep_role())
        coder.connection.connected.set()
        await until(lambda: len(fake.calls) == 1)
        coder.connection.connected.set()  # a reconnect
        await until(lambda: len(fake.calls) == 2)
        await stop(coder, [task])

    asyncio.run(main())
    assert fake.calls == [("assume_role", "c-eng", {"role": "reproducer"})] * 2


def test_working_then_answer_in_the_thread_with_the_thread_in_the_prompt(settings) -> None:
    fake = FakeSwitch(threads=[{"root": TICKET, "replies": []}])
    prompts: list[str] = []

    async def runner(prompt: str) -> ClaudeResult:
        prompts.append(prompt)
        return ClaudeResult(True, "Verdict: reproduced\n")

    async def main() -> None:
        coder = make_coder(settings, fake, runner)
        incoming, tasks = await running(coder)
        await incoming.put(message(2, "@reproducer go"))
        await until(lambda: len(fake.posts()) == 2)
        await stop(coder, tasks)

    asyncio.run(main())
    assert fake.posts() == [(WORKING, "t1"), ("Verdict: reproduced", "t1")]
    assert "- bugline-frontdesk: BL-1: Share" in prompts[0]
    assert ("read_context", "c-eng", {"limit": 100}) in fake.calls


def test_a_message_during_a_job_is_queued_and_runs_after(settings) -> None:
    fake = FakeSwitch(threads=[{"root": TICKET, "replies": []}])
    release = asyncio.Event()
    started: list[str] = []

    async def runner(prompt: str) -> ClaudeResult:
        started.append(prompt)
        if len(started) == 1:
            await release.wait()
        return ClaudeResult(True, f"answer {len(started)}")

    async def main() -> None:
        coder = make_coder(settings, fake, runner)
        incoming, tasks = await running(coder)
        await incoming.put(message(2, "@reproducer go"))
        await until(lambda: len(started) == 1)
        await incoming.put(message(3, "@reproducer and this one", thread_id=None))
        await until(lambda: len(fake.posts()) == 2)
        assert len(started) == 1  # the second job waits
        release.set()
        await until(lambda: len(fake.posts()) == 5)
        await stop(coder, tasks)

    asyncio.run(main())
    assert fake.posts() == [
        (WORKING, "t1"),
        ("Busy with BL-1, queued.", "m3"),
        ("answer 1", "t1"),
        (WORKING, "m3"),
        ("answer 2", "m3"),
    ]


def test_failed_run_and_crashing_runner_post_one_line_and_the_loop_goes_on(settings) -> None:
    fake = FakeSwitch()
    results = [ClaudeResult(False, "Claude Code timed out after 30 min"), RuntimeError("bug")]

    async def runner(prompt: str) -> ClaudeResult:
        result = results.pop(0) if results else ClaudeResult(True, "fine")
        if isinstance(result, Exception):
            raise result
        return result

    async def main() -> None:
        coder = make_coder(settings, fake, runner)
        incoming, tasks = await running(coder)
        for n in (1, 2, 3):
            await incoming.put(message(n, "@reproducer go", thread_id=None))
        await until(lambda: ("fine", "m3") in fake.posts())
        await stop(coder, tasks)

    asyncio.run(main())
    answers = [body for body, _ in fake.posts() if body != WORKING and not body.startswith("Busy")]
    assert answers == [
        "Could not finish: Claude Code timed out after 30 min",
        "Something went wrong on my side; it is in the agent's log.",
        "fine",
    ]
