"""Run Claude Code headless (`claude -p`) for one job, and turn its answer into a short reply.

The brief in switch/agent-briefs/ is appended to Claude Code's system prompt from the file at
every run, so it is never copied. The prompt (the message, its sender and the thread so far) goes
in on stdin, which avoids Windows command-line quoting and length limits. Claude Code prints one
JSON object (`--output-format json`) whose `result` is its final message; that is the reply.
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from common.conventions import REPLY_MAX_LINES
from common.switch_client import IncomingMessage

import config


@dataclass(frozen=True)
class ClaudeResult:
    ok: bool
    text: str  # the final answer, or why there is none


def claude_command(settings: config.Settings, claude_path: str) -> list[str]:
    """The full command line for one run. The prompt is not in it; it goes on stdin."""
    return [
        claude_path,
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",  # every job starts clean; the thread is in the prompt
        "--append-system-prompt-file",
        str(settings.brief),
        # Skip the operator's own user settings (their allow rules, plugins, model), so the
        # rules below are the only permissions, on any machine.
        "--setting-sources",
        "project,local",
        "--settings",
        json.dumps(config.CLAUDE_SETTINGS),
        "--permission-mode",
        "dontAsk",  # anything not allowed below is refused, never prompted for
        "--tools",
        ",".join(config.TOOLS),
        "--allowedTools",
        *settings.allowed_tools,
        "--disallowedTools",
        *config.DENIED,
    ]


def build_prompt(settings: config.Settings, msg: IncomingMessage, thread: list[dict]) -> str:
    """The user prompt: who addressed the agent, what they said, and the thread before it."""
    lines = [
        f"You are {settings.agent_name} and hold the role `{settings.role}`.",
        f"{msg.sender_name or msg.sender_id} addressed you in the room:",
        "",
        msg.body,
        "",
    ]
    if thread:
        lines.append("Earlier messages in this thread, oldest first:")
        for entry in thread:
            sender = entry.get("sender_name") or entry.get("sender") or "?"
            body = str(entry.get("body", ""))[:3000].replace("\n", "\n  ")
            lines.append(f"- {sender}: {body}")
    else:
        lines.append("This message starts its thread; there is nothing before it.")
    lines += [
        "",
        "Do what your instructions say for this message. You cannot post in the room yourself:"
        " your final message is posted in this thread as your reply, so write it as the reply,"
        f" under {REPLY_MAX_LINES} lines.",
    ]
    return "\n".join(lines)


async def run_claude(cmd: list[str], prompt: str, cwd: str, timeout_s: float) -> ClaudeResult:
    """Run `cmd` in `cwd` with `prompt` on stdin. Never raises for a failed or slow run."""
    # Claude Code and the commands it runs do not need the Switch keys. CLAUDECODE is dropped so
    # a coder started from inside a Claude Code session can still launch it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("SWITCH_") and k != "CLAUDECODE"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return ClaudeResult(False, f"could not start Claude Code: {exc}")
    try:
        out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout_s)
    except TimeoutError:
        await _kill(proc)
        return ClaudeResult(False, f"Claude Code timed out after {timeout_s / 60:.0f} min")
    return parse_output(proc.returncode, out, err)


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """Stop a run. On Windows, taskkill /T also stops what Claude Code started (python, git)."""
    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/F", "/T", "/PID", str(proc.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
        await killer.wait()
    else:
        proc.kill()
    await proc.wait()


def parse_output(returncode: int | None, out: bytes, err: bytes) -> ClaudeResult:
    """Claude Code's JSON result to a ClaudeResult. Falls back to the raw text if it is not JSON."""
    text = out.decode("utf-8", "replace").strip()
    try:
        data: Any = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        result = str(data.get("result") or "").strip()
        if returncode == 0 and not data.get("is_error") and result:
            return ClaudeResult(True, result)
        return ClaudeResult(False, result or f"Claude Code stopped ({data.get('subtype')})")
    detail = text or err.decode("utf-8", "replace").strip() or f"exit code {returncode}"
    return ClaudeResult(False, detail.splitlines()[-1])


def trim_reply(text: str) -> str:
    """Cap a reply at REPLY_MAX_LINES lines and REPLY_MAX_CHARS characters, marking any cut."""
    lines = text.strip().splitlines() or ["(no answer)"]
    whole = "\n".join(lines)
    if len(lines) <= REPLY_MAX_LINES and len(whole) <= config.REPLY_MAX_CHARS:
        return whole
    kept = "\n".join(lines[: REPLY_MAX_LINES - 2])[: config.REPLY_MAX_CHARS]
    if kept.count("```") % 2:  # close a code block the cut left open
        kept += "\n```"
    return kept + "\n(trimmed; the full answer is in the agent's log)"
