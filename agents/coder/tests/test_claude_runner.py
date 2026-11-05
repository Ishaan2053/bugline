"""Tests for the Claude Code runner. A short Python script stands in for `claude`, so the
subprocess, stdin and timeout handling are real but nothing calls Claude."""

import asyncio
import json
import subprocess
import sys

from common.conventions import REPLY_MAX_LINES
from common.switch_client import IncomingMessage

import config
from claude_runner import (
    ClaudeResult,
    build_prompt,
    claude_command,
    parse_output,
    restore_clone,
    run_claude,
    trim_reply,
)

MSG = IncomingMessage("eng", "room-e", "@u:x", "PM", "@reproducer BL-1 please", "m2", "m1")


def fake_claude(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def test_command_appends_the_brief_and_allows_only_the_roles_tools(settings) -> None:
    cmd = claude_command(settings, "claude")
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--append-system-prompt-file") + 1] == str(settings.rendered_brief)
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")]
    denied = cmd[cmd.index("--disallowedTools") + 1 :]
    clone = config.anchored("Edit(x)", settings.clone).removesuffix("/x)")  # "Edit(//<clone>"
    assert "Bash" in allowed and f"{clone}/demo-app/scratch/**)" in allowed
    assert not [rule for rule in allowed if rule.endswith("/**)") and "scratch" not in rule]
    assert f"{clone}/demo-app/seed.py)" in denied  # deny rules are anchored too
    # Only this file's settings: no user settings, no project CLAUDE.md.
    assert cmd[cmd.index("--setting-sources") + 1] == "local"
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


def test_refused_tool_calls_are_logged(caplog) -> None:
    denial = {"tool_name": "Write", "tool_use_id": "t1", "tool_input": {"file_path": "x/y.py"}}
    out = json.dumps({"is_error": False, "result": "done", "permission_denials": [denial]})
    with caplog.at_level("WARNING"):
        assert parse_output(0, out.encode(), b"") == ClaudeResult(True, "done")
    assert 'Claude Code was refused Write {"file_path": "x/y.py"}' in caplog.text


def test_trim_keeps_short_replies_and_caps_long_ones() -> None:
    assert trim_reply("Verdict: reproduced\n") == "Verdict: reproduced"

    long = "\n".join(["```", *[f"line {i}" for i in range(30)], "```"])
    trimmed = trim_reply(long)
    lines = trimmed.splitlines()
    assert len(lines) == REPLY_MAX_LINES
    assert lines[-2] == "```" and lines[-1].startswith("(trimmed")

    wide = trim_reply("x" * 5000)
    assert len(wide) < config.REPLY_MAX_CHARS + 100 and "(trimmed" in wide


def git(clone, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=clone,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def test_restore_clone_drops_what_an_unfinished_run_left(tmp_path) -> None:
    """A timed-out fixer: on its ticket branch, a tracked file edited, a new test file written."""
    clone = tmp_path / "clone"
    clone.mkdir()
    git(clone, "init", "-q", "-b", config.PROJECT.default_branch)
    (clone / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    (clone / "app.py").write_text("ok\n", encoding="utf-8")
    git(clone, "add", ".")
    git(clone, "commit", "-q", "-m", "start")
    git(clone, "checkout", "-q", "-b", "fix/bl-1")
    (clone / "app.py").write_text("half-finished\n", encoding="utf-8")
    (clone / "test_new.py").write_text("x\n", encoding="utf-8")
    (clone / "scratch").mkdir()
    (clone / "scratch" / "bl_1.py").write_text("kept\n", encoding="utf-8")

    asyncio.run(restore_clone(clone))

    assert git(clone, "branch", "--show-current") == config.PROJECT.default_branch
    assert (clone / "app.py").read_text(encoding="utf-8") == "ok\n"
    assert not (clone / "test_new.py").exists()
    assert (clone / "scratch" / "bl_1.py").exists()  # ignored files stay


def test_restore_clone_without_a_clone_does_nothing(tmp_path) -> None:
    asyncio.run(restore_clone(tmp_path / "missing"))
