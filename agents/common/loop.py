"""Run an agent's asyncio entry point without the Windows Proactor's noise at shutdown.

On Windows, when an agent stops, the Proactor loop can log a `ConnectionResetError` from
`_ProactorBasePipeTransport._call_connection_lost`: the other end already closed the socket, so
the transport's own `shutdown()` call fails. It is harmless, but it ends the log on a traceback.
`run` installs a loop exception handler that drops exactly that error and passes everything else
to the default handler. The loop stays a Proactor loop, because the coders need it to start
Claude Code as a subprocess. On other platforms `run` is plain `asyncio.run`.
"""

import asyncio
import sys
from collections.abc import Awaitable
from typing import Any

# How asyncio names the failing callback in the error's message ("Exception in callback ...").
PROACTOR_SHUTDOWN_CALLBACK = "_ProactorBasePipeTransport._call_connection_lost"


def quiet_proactor_shutdown(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Loop exception handler: drop the Proactor's shutdown reset, hand anything else on."""
    if isinstance(context.get("exception"), ConnectionResetError) and (
        PROACTOR_SHUTDOWN_CALLBACK in context.get("message", "")
    ):
        return
    loop.default_exception_handler(context)


def _windows_loop() -> asyncio.AbstractEventLoop:
    """A new default loop (Proactor on Windows) with the quiet handler installed."""
    loop = asyncio.EventLoop()
    loop.set_exception_handler(quiet_proactor_shutdown)
    return loop


def run[T](main: Awaitable[T]) -> T:
    """`asyncio.run(main)`, with the quiet handler on Windows."""
    factory = _windows_loop if sys.platform == "win32" else None
    return asyncio.run(main, loop_factory=factory)
