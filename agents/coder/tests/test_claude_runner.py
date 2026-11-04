"""Tests for the Claude Code runner. A short Python script stands in for `claude`, so the
subprocess, stdin and timeout handling are real but nothing calls Claude."""

import asyncio
import json
import sys

from common.conventions import REPLY_MAX_LINES
from common.switch_client import IncomingMessage

import config
from claude_runner import ClaudeResult, build_prompt, claude_command, run_claude, trim_reply

MSG = IncomingMessage("eng", "room-e", "@u:x", "PM", "@reproducer BL-1 please", "m2", "m1")


def fake_claude(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_command_appends_the_brief_and_allows_only_the_roles_tools(settings) -> None:
    cmd = claude_command(settings, "claude")
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--append-system-prompt-file") + 1] == str(settings.brief)
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")]
    denied = cmd[cmd.index("--disallowedTools") + 1 :]
    assert "Bash" in allowed and "Edit(demo-app/scratch/**)" in allowed
    assert "Edit(**)" not in allowed
    # The reproducer never changes the repo; both roles are refused the dangerous git commands.
    assert {"Bash(git push*)", "Bash(git commit*)", "Bash(gh *)"} <= set(denied)
    assert "Bash(gh pr merge *)" in denied
    fixer = config.ROLES["fixer"]
    assert "Edit(**)" in fixer.allowed and "Bash(git push*)" not in fixer.denied


def test_prompt_has_sender_message_and_thread(settings) -> None:
    thread = [
        {"id": "m1", "sender_name": "bugline-frontdesk", "body": "BL-1: Share link\nSteps: x"},
        {"id": "m3", "sender": "@bugline-repro:x", "body": "Verdict: reproduced"},
    ]
    prompt = build_prompt(settings, MSG, thread)
    assert "PM addressed you" in prompt and "@reproducer BL-1 please" in prompt
    assert "- bugline-frontdesk: BL-1: Share link\n  Steps: x" in prompt
    assert "- @bugline-repro:x: Verdict: reproduced" in prompt
    assert "nothing before it" in build_prompt(settings, MSG, [])


def test_run_passes_the_prompt_on_stdin_and_reads_the_json_result(tmp_path, monkeypatch) -> None:
    script = (
        "import json, os, sys;"
        "print(json.dumps({'type': 'result', 'is_error': False,"
        " 'result': 'got: ' + sys.stdin.read() + ' key=' + str('SWITCH_X' in os.environ)}))"
    )
    monkeypatch.setenv("SWITCH_X", "secret")
    result = asyncio.run(run_claude(fake_claude(script), "hello", str(tmp_path), 30))
    assert result == ClaudeResult(True, "got: hello key=False")  # Switch keys are not passed on


def test_timeout_stops_the_run_and_says_so(tmp_path) -> None:
    script = "import time; time.sleep(30)"
    result = asyncio.run(run_claude(fake_claude(script), "", str(tmp_path), 0.5))
    assert not result.ok and "timed out" in result.text


def test_errors_are_results_not_exceptions(tmp_path) -> None:
    error = json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True})
    script = f"print({error!r})"
    result = asyncio.run(run_claude(fake_claude(script), "", str(tmp_path), 30))
    assert result == ClaudeResult(False, "Claude Code stopped (error_max_turns)")

    crash = "import sys; sys.stderr.write('boom\\nlast line'); sys.exit(2)"
    result = asyncio.run(run_claude(fake_claude(crash), "", str(tmp_path), 30))
    assert result == ClaudeResult(False, "last line")

    result = asyncio.run(run_claude(["no-such-claude-binary"], "", str(tmp_path), 30))
    assert not result.ok and "could not start" in result.text


def test_trim_keeps_short_replies_and_caps_long_ones() -> None:
    assert trim_reply("Verdict: reproduced\n") == "Verdict: reproduced"

    long = "\n".join(["```", *[f"line {i}" for i in range(30)], "```"])
    trimmed = trim_reply(long)
    lines = trimmed.splitlines()
    assert len(lines) == REPLY_MAX_LINES
    assert lines[-2] == "```" and lines[-1].startswith("(trimmed")

    wide = trim_reply("x" * 5000)
    assert len(wide) < config.REPLY_MAX_CHARS + 100 and "(trimmed" in wide
