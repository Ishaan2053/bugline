"""Tests for the coder's Switch side: a mock bridge (httpx.MockTransport) records every op call,
and a fake runner stands in for Claude Code."""

import asyncio
import json
from dataclasses import replace

import httpx
from common.switch_client import Credentials, IncomingMessage, RoomConnection, SwitchApi

from agent import NO_FRONTDESK, NO_REPRODUCER, WORKING, Coder
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


PR = "https://github.com/Ishaan2053/bugline/pull/21"
VERIFY = f"@reproducer please verify BL-1 on PR {PR} (branch fix/demo-app-bl-1-share-11071432)"


def answer(settings, reply: str, statuses: dict | None = None) -> FakeSwitch:
    """Have the coder answer `reply` to one message; the bridge reports `statuses` for targets."""
    fake = FakeSwitch()

    def handler(request: httpx.Request) -> httpx.Response:
        response = fake.handler(request)
        if request.url.path.endswith("/send_targeted_message"):
            result = {"event_id": "t", "target_statuses": statuses or {}}
            return httpx.Response(200, json={"result": result})
        return response

    async def main() -> None:
        api = SwitchApi("http://switch.test", CREDS, transport=httpx.MockTransport(handler))
        connection = RoomConnection("eng", "room-e", CREDS, "http://switch.test", "c-eng")
        coder = Coder(settings, api, connection, None)
        await coder.answer(reply, message(2, "@x go"))
        await api.aclose()

    asyncio.run(main())
    return fake


def as_role(settings, role: str, frontdesk: str = "bugline-frontdesk"):
    return replace(settings, role=role, frontdesk_name=frontdesk)


def test_fixer_hands_the_pr_to_the_reproducer_role(settings) -> None:
    reply = f"{VERIFY}\nTest: test_share_for_member_with_no_expenses"
    fake = answer(as_role(settings, "fixer"), reply, {"bugline-repro": "live"})
    body = reply.removeprefix("@reproducer ")
    assert fake.calls == [
        (
            "send_targeted_message",
            "c-eng",
            {"body": body, "target_roles": ["reproducer"], "thread_id": "t1"},
        )
    ]


def test_nobody_holding_reproducer_gets_a_note_in_the_thread(settings) -> None:
    fake = answer(as_role(settings, "fixer"), VERIFY, {})
    assert fake.posts() == [(NO_REPRODUCER, "t1")]


def test_reproducer_sends_its_verdict_to_the_front_desk_by_name(settings) -> None:
    settings = as_role(settings, "reproducer")
    for verdict in (f"Verified BL-1: {PR}", "Not verified BL-1: test_share still fails"):
        fake = answer(settings, f"@frontdesk {verdict}", {"bugline-frontdesk": "live"})
        assert fake.calls == [
            (
                "send_targeted_message",
                "c-eng",
                {"body": verdict, "target_names": ["bugline-frontdesk"], "thread_id": "t1"},
            )
        ]
    offline = answer(settings, f"@frontdesk Verified BL-1: {PR}", {"bugline-frontdesk": "offline"})
    assert offline.posts() == [(NO_FRONTDESK.format(name="bugline-frontdesk"), "t1")]


def test_without_the_front_desk_name_a_verdict_is_posted_plainly(settings) -> None:
    reply = f"@frontdesk Verified BL-1: {PR}"
    fake = answer(as_role(settings, "reproducer", frontdesk=""), reply)
    assert [op for op, _, _ in fake.calls] == ["post_message"]
    assert fake.posts() == [(reply, "t1")]


def test_other_replies_and_the_wrong_role_post_plainly(settings) -> None:
    repro = as_role(settings, "reproducer")
    verdict = "Ran: python -m scratch.bl_1\nVerdict: reproduced"
    assert [op for op, _, _ in answer(repro, verdict).calls] == ["post_message"]
    # Only the reproducer's verdict and the fixer's verify request hand work on.
    fixer_verdict = answer(as_role(settings, "fixer"), f"@frontdesk Verified BL-1: {PR}")
    assert [op for op, _, _ in fixer_verdict.calls] == ["post_message"]
    repro_verify = answer(repro, VERIFY)
    assert [op for op, _, _ in repro_verify.calls] == ["post_message"]


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


def test_a_dropped_connection_while_posting_is_logged_not_raised(settings, caplog) -> None:
    """On Nov 6 the server's database restarted mid-post; the error ended the whole coder."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection dropped", request=request)

    api = SwitchApi("http://switch.test", CREDS, transport=httpx.MockTransport(handler))
    connection = RoomConnection("eng", "room-e", CREDS, "http://switch.test", "c-eng")
    coder = Coder(settings, api, connection, None)

    async def main() -> None:
        await coder._post("Busy with BL-1, queued.", message(1, "@fixer go on BL-2"))
        await api.aclose()

    asyncio.run(main())
    assert "could not post 'Busy with BL-1, queued.'" in caplog.text
