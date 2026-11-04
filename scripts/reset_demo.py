"""Put the Bugline demo back to a clean start, so every recording take begins at BL-1.

Stop the three agents, then run `python scripts/reset_demo.py --dry-run` to see the plan and
`python scripts/reset_demo.py` to do it. In order:

1. Refuses while any agent is connected to Bugline's rooms: the front desk keeps its SQLite file
   open, and a coder may be running in its clone.
2. Deletes the front desk's database, so tickets restart at BL-1. Its credentials and connection
   ids stay.
3. In each coder's clone: checks out main at origin/main, discarding what the agent left there,
   and deletes local ticket branches, the scratch scripts and any *.db under the demo app.
4. On GitHub: closes open ticket PRs and deletes remote ticket branches, except the PRs in
   --keep (default 18,19, the two the README cites) and their branches.
5. Recreates the demo app's container, which seeds a fresh database, and checks GET /health.

A ticket PR is one whose title starts with a ticket id (switch/docs/fix-policy.md); a ticket
branch is one whose name holds a ticket id, like fix/demo-app-bl-1-share-link.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from bootstrap import (
    APP_DIR,
    REPO_ROOT,
    Gateway,
    Stop,
    load_agent_configs,
    load_layout,
    read_options,
)
from common.conventions import TICKET_ID_RE
from doctor import NoFlags, connected_agents

MAIN = "main"
TICKET_BRANCH_RE = re.compile(TICKET_ID_RE.pattern, re.IGNORECASE)  # branches are lower case
DEMO_APP_SERVICE = "demo-app"  # the service in docker-compose.yml
DEMO_APP_HEALTH = "http://127.0.0.1:8000/health"  # the port docker-compose.yml publishes
HEALTH_WAIT_S = 60


def parse_keep(text: str) -> set[int]:
    """Parse --keep: "18,19" -> {18, 19}; an empty value keeps nothing."""
    return {int(part) for part in text.split(",") if part.strip()}


class Shell:
    """Runs commands and deletes files. In a dry run, only reads run; changes are printed."""

    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run

    def read(self, cmd: list[str], cwd: Path) -> str:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout

    def change(self, cmd: list[str], cwd: Path, note: str = "") -> None:
        self._say("run: " + " ".join(cmd) + (f"  ({note})" if note else ""))
        if not self.dry_run:
            subprocess.run(cmd, cwd=cwd, check=True)

    def remove(self, path: Path) -> None:
        self._say(f"delete {path}")
        if self.dry_run:
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    def _say(self, what: str) -> None:
        print(f"  {'would ' if self.dry_run else ''}{what}")


def reset_frontdesk(shell: Shell, db_path: Path) -> None:
    if db_path.exists():
        shell.remove(db_path)
    else:
        print(f"  {db_path}: already gone")


def reset_clone(shell: Shell, clone: Path) -> None:
    """main at origin/main, no ticket branches, no scratch scripts, no SQLite files."""
    if not clone.is_dir():
        print(f"  {clone}: skipped (no clone there)")
        return
    print(f"  in {clone}")
    shell.change(["git", "fetch", "--prune"], clone)
    shell.change(["git", "checkout", "--force", MAIN], clone)
    shell.change(["git", "reset", "--hard", f"origin/{MAIN}"], clone)
    branches = shell.read(["git", "branch", "--list", "--format=%(refname:short)"], clone)
    for branch in branches.split():
        if TICKET_BRANCH_RE.search(branch):
            shell.change(["git", "branch", "-D", branch], clone)
    app = clone / APP_DIR
    scratch = app / "scratch"
    if scratch.exists():
        shell.remove(scratch)
    for db in sorted(app.rglob("*.db")):
        if ".venv" not in db.parts and scratch not in db.parents:
            shell.remove(db)


def reset_remote(shell: Shell, repo: Path, keep: set[int]) -> None:
    """Close open ticket PRs and delete ticket branches on origin, except kept PRs'."""
    fields = "number,title,headRefName,state"
    listed = shell.read(
        ["gh", "pr", "list", "--state", "all", "--limit", "200", "--json", fields], repo
    )
    prs = [pr for pr in json.loads(listed) if TICKET_ID_RE.match(pr["title"])]
    kept_branches = {pr["headRefName"] for pr in prs if pr["number"] in keep}
    for pr in prs:
        if pr["number"] in keep:
            print(f"  keep PR #{pr['number']} {pr['title']} ({pr['headRefName']})")
        elif pr["state"] == "OPEN":
            shell.change(["gh", "pr", "close", str(pr["number"])], repo, pr["title"])
    heads = shell.read(["git", "ls-remote", "--heads", "origin"], repo)
    for line in heads.splitlines():
        branch = line.partition("refs/heads/")[2]
        if TICKET_BRANCH_RE.search(branch) and branch not in kept_branches:
            shell.change(["git", "push", "origin", "--delete", branch], repo)
    if kept_branches:
        print(
            "  note: a new fix branch must not reuse a kept PR's branch name: "
            + ", ".join(sorted(kept_branches))
        )


def reseed_demo_app(
    shell: Shell, repo: Path, get: Callable[[str], httpx.Response] = httpx.get
) -> None:
    """A new container has a fresh database; the image seeds it on start."""
    cmd = ["docker", "compose", "up", "--build", "--force-recreate", "--detach", DEMO_APP_SERVICE]
    shell.change(cmd, repo)
    if shell.dry_run:
        print(f"  would check GET {DEMO_APP_HEALTH}")
        return
    deadline = time.monotonic() + HEALTH_WAIT_S
    while True:
        try:
            if get(DEMO_APP_HEALTH).is_success:
                print(f"  GET {DEMO_APP_HEALTH}: ok")
                return
        except httpx.HTTPError:
            pass  # the app is still starting
        if time.monotonic() > deadline:
            raise Stop(f"{DEMO_APP_HEALTH} did not answer in {HEALTH_WAIT_S}s; see docker logs")
        time.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument(
        "--keep", type=parse_keep, default="18,19", help="PR numbers to leave open (default 18,19)"
    )
    args = parser.parse_args()
    shell = Shell(args.dry_run)
    try:
        opts = read_options(NoFlags())  # before the config modules, as in bootstrap
        layout = load_layout()
        frontdesk, coder = load_agent_configs()
        if args.dry_run:
            print("Dry run: reads only; every change is printed, not made.\n")

        print("1. Agents")
        gw = Gateway(opts.api_url, dry_run=True)
        gw.check_health()
        gw.login(opts.admin_email, opts.admin_password)
        if live := connected_agents(gw, layout):
            message = f"stop these agents first: {', '.join(live)}"
            if not args.dry_run:
                raise Stop(message)
            print(f"  {message} (a real run refuses)")
        else:
            print("  none connected")

        print("2. Front desk")
        reset_frontdesk(shell, frontdesk.DB_PATH)
        print("3. Coder clones")
        for role in coder.ROLES:
            reset_clone(shell, coder.settings(role).clone)
        print(f"4. GitHub (keeping {', '.join(f'#{n}' for n in sorted(args.keep)) or 'nothing'})")
        reset_remote(shell, REPO_ROOT, args.keep)
        print("5. Demo app")
        reseed_demo_app(shell, REPO_ROOT)
    except (Stop, httpx.HTTPError) as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"\nStopped: {' '.join(exc.cmd)} failed:\n{exc.stderr or ''}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
