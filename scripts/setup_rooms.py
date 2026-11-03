"""Finish the Switch setup that the room template cannot do.

Run it after the template has made bugline-eng (or after you made that room by hand) and after the
Telegram bot has been added to the bugline-support group. It works through the agent operations
API as the front desk agent, using its id and API key, and does this:

1. Checks that the bridge answers GET /health and offers the operations used below.
2. Finds bugline-support and bugline-eng among the front desk's rooms.
3. Invites bugline-repro and bugline-fixer to bugline-eng if they are not in it.
4. Sets each room's instructions from switch/room-instructions-*.md and gives the front desk the
   alias `frontdesk` in both rooms.
5. Creates the GitHub reference to this repo once and attaches it to both rooms.
6. Links the rooms: bugline-support -> bugline-eng "escalates to", bugline-eng -> bugline-support
   "supports".
7. Reports roles missing from bugline-eng.

It only calls operations that take a room id. Operations bound to a connection's room would need a
WebSocket claiming that room, which would take it away from the running front desk. So roles and
room documents are not made here; docs/switch-setup.md covers them.

Settings come from environment variables, or from scripts/.env (see scripts/.env.example).
`--dry-run` prints every call and sends nothing. Only the standard library is used.

Written from the Switch docs and the server 0.31 source; not yet run against a live server.
Unverified:
- The shapes of the list_rooms and list_all_references results (a list, or an object holding
  one) and of `aliases` and `roles` in get_room_detail. The code accepts either.
- Whether update_room(aliases=...) adds to or replaces a room's aliases.
- Whether link_rooms on an existing link updates it or fails, and whether
  attach_reference_to_room on an attached reference fails. Both are called on every run, and a
  failure is printed and skipped, so a re-run is safe either way.
- Whether the front desk, as its owner's agent, has write access to rooms the owner made.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path(__file__).resolve().parent / ".env"

FRONTDESK = "bugline-frontdesk"
FRONTDESK_ALIAS = "frontdesk"
ENG_AGENTS = ["bugline-repro", "bugline-fixer"]
ENG_ROLES = ["reproducer", "fixer"]
REFERENCE_NAME = "bugline-repo"  # same name as in switch/bugline.template.yaml, so it is reused
INSTRUCTIONS = {
    "support": REPO_ROOT / "switch" / "room-instructions-support.md",
    "eng": REPO_ROOT / "switch" / "room-instructions-eng.md",
}
LINKS = [("support", "eng", "escalates to"), ("eng", "support", "supports")]
OPERATIONS = [
    "list_rooms",
    "get_room_detail",
    "invite_agent_to_room",
    "update_room",
    "list_reference_types",
    "list_all_references",
    "create_reference",
    "attach_reference_to_room",
    "link_rooms",
]


class SwitchError(Exception):
    """A call failed, or the server is not set up the way this script needs."""


@dataclass(frozen=True)
class Settings:
    api_url: str
    agent_id: str
    api_key: str
    support_room: str  # room name or id
    eng_room: str
    repo_url: str


class Switch:
    """Calls to the bridge as the front desk agent. In dry-run mode it prints and sends nothing."""

    def __init__(self, settings: Settings, dry_run: bool) -> None:
        self.base_url = settings.api_url.rstrip("/")
        self.agent_id = settings.agent_id
        self.api_key = settings.api_key
        self.dry_run = dry_run

    def health(self) -> None:
        print("  GET /health")
        if self.dry_run:
            return
        body = self._request("GET", "/health")
        if body != {"status": "ok"}:
            raise SwitchError(f"/health answered {body!r}; SWITCH_API_URL is not the bridge")
        print("    ok")

    def check_operations(self, needed: list[str]) -> None:
        print(f"  GET /agents/{self.agent_id}/ops")
        if self.dry_run:
            return
        offered = self._request("GET", f"/agents/{self.agent_id}/ops").get("operations", {})
        missing = [name for name in needed if name not in offered]
        if missing:
            raise SwitchError(f"the server does not offer: {', '.join(missing)}")
        print(f"    ok, all {len(needed)} present")

    def op(self, operation: str, /, **args: Any) -> Any:
        """Invoke one operation and return its result, or None in dry-run mode.

        `operation` is positional-only so an argument called `name` (create_reference has one)
        goes to the server instead of clashing with it.
        """
        shown = ", ".join(f"{key}={_short(value)}" for key, value in args.items())
        print(f"  op {operation}({shown})")
        if self.dry_run:
            return None
        path = f"/agents/{self.agent_id}/ops/{operation}"
        return self._request("POST", path, args).get("result")

    def attempt(self, operation: str, /, **args: Any) -> Any:
        """Like op, for a write that may already be done: a failure is printed, not raised."""
        try:
            result = self.op(operation, **args)
        except SwitchError as exc:
            print(f"    skipped: {exc}")
            return None
        if not self.dry_run:
            print("    ok")
        return result

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        request = urllib.request.Request(
            self.base_url + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            raise SwitchError(f"{method} {path} answered {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            raise SwitchError(f"cannot reach {self.base_url}: {exc.reason}") from None


def _short(value: Any) -> str:
    """A call argument as printed: long strings become their length, the rest is JSON."""
    if isinstance(value, str) and len(value) > 60:
        return f"<{len(value)} chars>"
    return json.dumps(value)


def _items(result: Any, key: str) -> list:
    """A list result, whether the op returned the list itself or an object holding it."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get(key) or []
    return []


def find_rooms(sw: Switch, wanted: dict[str, str]) -> dict[str, str]:
    """Map each room key ("support", "eng") to its Switch id, matching by name or id."""
    result = sw.op("list_rooms")
    if sw.dry_run:
        return {key: f"<{value} id>" for key, value in wanted.items()}
    rooms = _items(result, "rooms")
    found = {}
    for key, value in wanted.items():
        matches = [room for room in rooms if value in (room.get("id"), room.get("name"))]
        if len(matches) != 1:
            names = ", ".join(str(room.get("name")) for room in rooms) or "none"
            raise SwitchError(
                f"{len(matches)} rooms match {value!r}; the front desk is in: {names}. "
                "Invite the front desk to the room, or put the room id in scripts/.env."
            )
        found[key] = matches[0]["id"]
        print(f"    {key}: {value} is {found[key]}")
    return found


def ensure_eng_members(sw: Switch, room_id: str, detail: dict) -> None:
    present = set(detail.get("agent_names") or [])
    for agent in ENG_AGENTS:
        if agent in present:
            print(f"    {agent} is already a member")
        else:
            sw.attempt("invite_agent_to_room", room_id=room_id, agent_name=agent)


def ensure_room_settings(sw: Switch, room_id: str, detail: dict, instructions: Path) -> None:
    """Room instructions from the repo file, and the front desk alias. Sends only what differs."""
    changes: dict[str, Any] = {}
    text = instructions.read_text(encoding="utf-8")
    if detail.get("instructions") != text:
        changes["instructions"] = text
    # The shape of `aliases` is not documented, so look for the alias anywhere in it.
    if f'"{FRONTDESK_ALIAS}"' not in json.dumps(detail.get("aliases") or {}):
        changes["aliases"] = {FRONTDESK: FRONTDESK_ALIAS}
    if changes:
        sw.op("update_room", room_id=room_id, **changes)
        if not sw.dry_run:
            print("    ok")
    else:
        print("    instructions and alias already set")


def ensure_reference(sw: Switch, repo_url: str) -> str:
    """Id of the bugline-repo reference, created only if neither the template nor a run made it."""
    types = sw.op("list_reference_types")
    if not sw.dry_run and "github" not in json.dumps(types):
        raise SwitchError("this server has no github reference type")
    found = sw.op("list_all_references", name_contains=REFERENCE_NAME)
    for reference in _items(found, "references"):
        if reference.get("name") == REFERENCE_NAME:
            print(f"    reusing {REFERENCE_NAME} ({reference['id']})")
            return reference["id"]
    created = sw.op(
        "create_reference",
        type="github",
        name=REFERENCE_NAME,
        description="The Bugline repo, including the demo app the agents fix",
        instructions="Room rules are in switch/, shared documents in switch/docs/.",
        value={"urls": [repo_url]},
    )
    return created["id"] if created else f"<{REFERENCE_NAME} id>"


def report_roles(detail: dict) -> None:
    roles = detail.get("roles") or []
    present = {role if isinstance(role, str) else role.get("name") for role in roles}
    missing = [role for role in ENG_ROLES if role not in present]
    if missing:
        print(f"    missing: {', '.join(missing)}. Add them as docs/switch-setup.md says.")
    else:
        print("    reproducer and fixer are defined")


def run(sw: Switch, settings: Settings) -> None:
    print("1. Bridge")
    sw.health()
    sw.check_operations(OPERATIONS)

    print("2. Rooms")
    rooms = find_rooms(sw, {"support": settings.support_room, "eng": settings.eng_room})
    details = {
        key: sw.op("get_room_detail", room_id=room_id) or {} for key, room_id in rooms.items()
    }

    print("3. Agents in bugline-eng")
    ensure_eng_members(sw, rooms["eng"], details["eng"])

    print("4. Room instructions and front desk alias")
    for key, room_id in rooms.items():
        ensure_room_settings(sw, room_id, details[key], INSTRUCTIONS[key])

    print("5. Repo reference")
    reference_id = ensure_reference(sw, settings.repo_url)
    for room_id in rooms.values():
        sw.attempt("attach_reference_to_room", room_id=room_id, reference_id=reference_id)

    print("6. Room links")
    for source, target, label in LINKS:
        sw.attempt(
            "link_rooms", source_room_id=rooms[source], target_room_id=rooms[target], label=label
        )

    print("7. Roles in bugline-eng")
    report_roles(details["eng"])

    print(
        "\nStill by hand (docs/switch-setup.md): `!follow-ups off` in both rooms, the fixer's"
        "\naccess rule, the front desk's 'Anyone' setting, and the bugline-kit package."
    )


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines into the environment, without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def read_settings(dry_run: bool) -> Settings:
    """Settings from the environment. A dry run fills missing secrets with placeholders."""

    def required(name: str) -> str:
        value = os.environ.get(name, "")
        if value:
            return value
        if dry_run:
            return f"<{name}>"
        raise SwitchError(f"{name} is not set; copy scripts/.env.example to scripts/.env")

    return Settings(
        api_url=required("SWITCH_API_URL"),
        agent_id=required("FRONTDESK_AGENT_ID"),
        api_key=required("FRONTDESK_API_KEY"),
        support_room=os.environ.get("SUPPORT_ROOM") or "bugline-support",
        eng_room=os.environ.get("ENG_ROOM") or "bugline-eng",
        repo_url=os.environ.get("REPO_URL") or "https://github.com/Ishaan2053/bugline",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Finish the Bugline Switch setup.")
    parser.add_argument("--dry-run", action="store_true", help="print every call, send nothing")
    args = parser.parse_args()
    load_env_file(ENV_FILE)
    try:
        settings = read_settings(args.dry_run)
        if args.dry_run:
            print(f"Dry run against {settings.api_url}: nothing is sent.\n")
        run(Switch(settings, args.dry_run), settings)
    except SwitchError as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
