"""reset_demo.py --dry-run against a temp clone and origin with ticket branches: it plans to delete
exactly the ticket branches, PRs and files, leaves the --keep PRs and their branches, and changes
nothing."""

import json
import subprocess
from pathlib import Path

import pytest

import reset_demo

KEPT = "fix/demo-app-bl-1-share-link"  # a branch from before the time stamp
DROPPED = "fix/demo-app-bl-7-broken-thing-11071432"  # fix-policy.md: <slug>-<stamp>
VERIFY = "verify-bl-7"  # the reproducer's local copy of a PR (repro-checklist.md)
OTHER = "feat/scripts-other"
PRS = [
    {"number": 18, "title": "BL-1: share link works", "headRefName": KEPT, "state": "OPEN"},
    {"number": 30, "title": "BL-7: broken thing", "headRefName": DROPPED, "state": "OPEN"},
    {"number": 31, "title": "scripts: other", "headRefName": OTHER, "state": "OPEN"},
    {"number": 2, "title": "BL-3: merged long ago", "headRefName": "gone", "state": "MERGED"},
]


def git(cwd: Path, *args: str) -> str:
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


class FakeGh(reset_demo.Shell):
    """Real git; `gh pr list` answers from PRS."""

    def read(self, cmd: list[str], cwd: Path) -> str:
        return json.dumps(PRS) if cmd[0] == "gh" else super().read(cmd, cwd)


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone with three branches pushed to a bare origin, scratch scripts and SQLite files."""
    origin, work = tmp_path / "origin.git", tmp_path / "bugline"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-b", "main", str(work))
    (work / "README.md").write_text("demo\n")
    git(work, "add", ".")
    git(work, "commit", "-m", "start")
    git(work, "remote", "add", "origin", str(origin))
    for branch in (KEPT, DROPPED, OTHER):
        git(work, "branch", branch)
    git(work, "push", "origin", "--all")
    git(work, "branch", VERIFY)  # local only
    app = work / reset_demo.APP_DIR
    (app / "scratch").mkdir(parents=True)
    (app / "scratch" / "repro_bl_7.py").write_text("print(1)\n")
    (app / "bugline.db").write_text("")
    (app / ".venv").mkdir()
    (app / ".venv" / "cache.db").write_text("")
    return work


def plan(clone: Path, keep: set[int], capsys: pytest.CaptureFixture) -> str:
    shell = FakeGh(dry_run=True)
    db = clone.parent / "frontdesk.db"
    db.write_text("")
    reset_demo.reset_frontdesk(shell, db)
    reset_demo.reset_clone(shell, clone)
    reset_demo.reset_remote(shell, clone, keep)
    assert db.exists()
    return capsys.readouterr().out


def test_dry_run_plans_the_ticket_cleanup(clone: Path, capsys: pytest.CaptureFixture) -> None:
    out = plan(clone, {18}, capsys)

    assert "would delete" in out and "frontdesk.db" in out
    assert "would run: git reset --hard origin/main" in out
    assert f"would run: git branch -D {KEPT}" in out  # local ticket branches all go
    assert f"would run: git branch -D {DROPPED}" in out
    assert f"would run: git branch -D {VERIFY}" in out
    assert f"git branch -D {OTHER}" not in out
    assert "scratch" in out and "bugline.db" in out and "cache.db" not in out
    assert "would run: gh pr close 30  (BL-7: broken thing)" in out
    assert "keep PR #18" in out
    assert "gh pr close 18" not in out and "gh pr close 31" not in out
    assert f"would run: git push origin --delete {DROPPED}" in out
    assert f"--delete {KEPT}" not in out and f"--delete {OTHER}" not in out

    # A dry run changes nothing.
    assert set(git(clone, "branch", "--format=%(refname:short)").split()) >= {KEPT, DROPPED}
    assert DROPPED in git(clone, "ls-remote", "--heads", "origin")
    assert (clone / reset_demo.APP_DIR / "scratch" / "repro_bl_7.py").exists()


def test_keep_leaves_those_prs_and_branches(clone: Path, capsys: pytest.CaptureFixture) -> None:
    out = plan(clone, {18, 30}, capsys)

    assert "gh pr close" not in out
    assert "git push origin --delete" not in out
    assert "keep PR #30" in out


def test_parse_keep() -> None:
    assert reset_demo.parse_keep("18,19") == {18, 19}
    assert reset_demo.parse_keep("") == set()
