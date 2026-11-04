"""Tests for common.loop: the handler drops only the Proactor's shutdown reset."""

import asyncio
import sys

import pytest
from common.loop import quiet_proactor_shutdown, run

SHUTDOWN_MESSAGE = "Exception in callback _ProactorBasePipeTransport._call_connection_lost()"


class FakeLoop:
    """Records what reaches the default handler."""

    def __init__(self) -> None:
        self.forwarded: list[dict] = []

    def default_exception_handler(self, context: dict) -> None:
        self.forwarded.append(context)


def test_the_proactor_shutdown_reset_is_dropped() -> None:
    loop = FakeLoop()
    context = {"message": SHUTDOWN_MESSAGE, "exception": ConnectionResetError(10054, "reset")}

    quiet_proactor_shutdown(loop, context)

    assert loop.forwarded == []


@pytest.mark.parametrize(
    "context",
    [
        {"message": SHUTDOWN_MESSAGE, "exception": ValueError("not a reset")},
        {"message": "Exception in callback Other.method()", "exception": ConnectionResetError()},
        {"message": "Task exception was never retrieved"},
    ],
    ids=["other exception", "other callback", "no exception"],
)
def test_anything_else_goes_to_the_default_handler(context: dict) -> None:
    loop = FakeLoop()

    quiet_proactor_shutdown(loop, context)

    assert loop.forwarded == [context]


async def _handler() -> object:
    return asyncio.get_running_loop().get_exception_handler()


def test_run_installs_the_handler_on_windows_only(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert run(_handler()) is quiet_proactor_shutdown

    monkeypatch.setattr(sys, "platform", "linux")
    assert run(_handler()) is None
