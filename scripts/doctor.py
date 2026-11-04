"""Check everything the Bugline demo needs before you record: `python scripts/doctor.py`.

It prints one line per check, PASS or FAIL, and on FAIL what to do. The exit code is 1 if any
check failed. Why it exists: a dropped bridge or a coder that is not running is cheap to find
before pressing record and expensive to find two minutes into a take.

It only reads. It signs in to the Gateway the way scripts/bootstrap.py does, calls the ops API
with each agent's own key, and runs `--version`-style commands. `--gemini` adds one short model
call, which spends quota, so it is off by default. `--dump` prints each server response once, to
check field names against a live server.
"""

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from types import ModuleType
from typing import Any, NamedTuple

import httpx

from bootstrap import (
    APP_DIR,
    AgentSpec,
    Gateway,
    Layout,
    Stop,
    expected_policies,
    load_agent_configs,
    load_layout,
    read_options,
    room_members,
)
from common.env import read_env_file
from common.switch_client import Credentials, load_credentials

# Values seen on the live server (Console 0.40.1, server 0.31.0) with --dump.
BRIDGE_RUNNING = "active"  # `status` of a working connection in GET /gateway/collaborations
AGENT_LIVE = "live"  # `agent_statuses` value of a connected agent in GET /gateway/rooms/{id}
# Neither the Gateway nor get_room_detail reports the follow-ups setting, so it is a reminder.
FOLLOW_UPS_REMINDER = "REMINDER type `!follow-ups off` in both rooms (Switch does not report it)"
RERUN = "run scripts/bootstrap.py"


class Check(NamedTuple):
    name: str
    ok: bool
    hint: str = ""  # what to do; printed only on FAIL

    def line(self) -> str:
        return f"PASS {self.name}" if self.ok else f"FAIL {self.name}: {self.hint}"


def start_hint(spec: AgentSpec) -> str:
    if spec.role == "frontdesk":
        return "start agents/frontdesk (python agent.py)"
    return f"start agents/coder with CODER_ROLE={spec.role}"


def configured_room_ids(layout: Layout) -> dict[str, str]:
    """Room key -> the room id in the front desk's .env ("" if unset): the rooms the agents use."""
    env = read_env_file(layout.frontdesk_env)
    return {key: env.get(var, "") for key, var in layout.frontdesk_room_vars.items()}


# --- Switch -----------------------------------------------------------------------------------


def switch_checks(gw: Gateway, layout: Layout, email: str, password: str) -> Iterator[Check]:
    """The server, the bridges, the rooms, the agents' keys, the roles and the access rules."""
    try:
        gw.check_health()
    except Stop as exc:
        yield Check(f"server {gw.api_url}", False, f"{exc} Start the server in Switch Console.")
        return
    yield Check(f"server {gw.api_url}", True)
    try:
        gw.login(email, password)
    except Stop as exc:
        yield Check("admin login", False, str(exc))
        return
    yield Check("admin login", True)

    ids = configured_room_ids(layout)
    if not all(ids.values()):
        yield Check("room ids in the front desk's .env", False, f"missing; {RERUN}")
        return
    coder_eng = read_env_file(layout.coder_env).get(layout.coder_eng_room_var)
    yield Check(
        "room ids in both .env files",
        coder_eng == ids["eng"],
        f"the coders' {layout.coder_eng_room_var} is not the front desk's; {RERUN}",
    )

    rooms = {room["id"]: room for room in gw.get("/rooms")}
    yield from bridge_checks(gw.get("/collaborations"), rooms, ids)
    server_agents = {agent["name"]: agent for agent in gw.get("/agents")}
    agent_ids = {name: agent["id"] for name, agent in server_agents.items()}
    for key, specs in room_members(layout).items():
        yield from room_checks(gw, layout.room_names[key], rooms.get(ids[key]), specs, agent_ids)
    creds = {}
    for spec in layout.agents:
        check, creds[spec.name] = key_check(gw, spec, agent_ids.get(spec.name))
        yield check
    yield from role_checks(gw, layout, creds[layout.agents[0].name], ids["eng"])
    wanted = expected_policies(ids["eng"])
    for spec in layout.agents:
        policy, label = wanted[spec.role]
        current = (server_agents.get(spec.name) or {}).get("addressing_policy")
        yield Check(f"access rule {spec.name} ({label})", current == policy, f"it differs; {RERUN}")


def bridge_checks(
    bridges: list[dict], rooms: dict[str, dict], ids: dict[str, str]
) -> Iterator[Check]:
    """Each room's chat-app connection is running. A missing room is reported by room_checks."""
    by_id = {bridge["bridge_id"]: bridge for bridge in bridges}
    for room_id in ids.values():
        room = rooms.get(room_id)
        if room is None:
            continue
        bridge = by_id.get(room.get("bridge_id")) or {}
        status, attention = bridge.get("status"), bridge.get("attention")
        hint = f"status is {status!r}" + (f" ({attention})" if attention else "")
        yield Check(
            f"bridge {room.get('bridge_type')} ({room['name']})",
            status == BRIDGE_RUNNING,
            f"{hint}; restart the server in Switch Console; do not disconnect the app",
        )


def room_checks(
    gw: Gateway,
    name: str,
    room: dict | None,
    specs: Iterable[AgentSpec],
    agent_ids: dict[str, str],
) -> Iterator[Check]:
    """The room exists and is not archived; each agent is a member and is connected to it."""
    if room is None or room.get("archived"):
        why = "it is archived" if room else "the room id in .env is not on this server"
        yield Check(f"room {name}", False, f"{why}; {RERUN}")
        return
    yield Check(f"room {name}", True)
    detail = gw.get(f"/rooms/{room['id']}") or {}
    members = detail.get("agent_ids") or []
    statuses = detail.get("agent_statuses") or {}
    for spec in specs:
        agent_id = agent_ids.get(spec.name)
        if agent_id not in members:
            yield Check(f"{spec.name} in {name}", False, f"not a member; {RERUN}")
            continue
        status = statuses.get(agent_id)
        yield Check(
            f"{spec.name} connected to {name}",
            status == AGENT_LIVE,
            f"status is {status!r}; {start_hint(spec)}",
        )


def connected_agents(gw: Gateway, layout: Layout) -> list[str]:
    """Names of the agents connected to Bugline's rooms right now. reset_demo.py refuses on any."""
    names = {agent["id"]: agent["name"] for agent in gw.get("/agents")}
    live = set()
    for room_id in filter(None, configured_room_ids(layout).values()):
        statuses = (gw.get(f"/rooms/{room_id}") or {}).get("agent_statuses") or {}
        live |= {names.get(i, i) for i, status in statuses.items() if status == AGENT_LIVE}
    return sorted(live)


def key_check(
    gw: Gateway, spec: AgentSpec, server_id: str | None
) -> tuple[Check, Credentials | None]:
    """The agent's saved key works: GET /agents/{id}/ops answers with it."""
    name = f"key {spec.name}"
    if not spec.credentials.is_file():
        hint = f"{spec.credentials} is missing; see docs/switch-setup.md, Troubleshooting"
        return Check(name, False, hint), None
    creds = load_credentials(spec.credentials)
    if creds.agent_id != server_id:
        hint = f"the saved id is not the server's {spec.name} ({server_id}); is this the server?"
        return Check(name, False, hint), None
    response = gw.http.get(
        f"/agents/{creds.agent_id}/ops", headers={"Authorization": f"Bearer {creds.api_key}"}
    )
    hint = f"the server answered {response.status_code} to the saved key"
    return Check(name, response.is_success, hint), creds if response.is_success else None


def role_checks(
    gw: Gateway, layout: Layout, frontdesk: Credentials | None, eng_id: str
) -> Iterator[Check]:
    """Each coder holds its role in the eng room. get_room_detail lists the live holders."""
    coders = [spec for spec in layout.agents if spec.role != "frontdesk"]
    if frontdesk is None:
        for spec in coders:
            yield Check(
                f"role {spec.role}", False, "cannot read roles without the front desk's key"
            )
        return
    detail = gw.op(frontdesk, "get_room_detail", read_only=True, room_id=eng_id) or {}
    roles = {role["name"]: role for role in detail.get("roles") or []}
    for spec in coders:
        role = roles.get(spec.role)
        holders = [holder.get("name") for holder in (role or {}).get("held_by") or []]
        if role is None:
            hint = "the room has no such role; it comes from switch/bugline.template.yaml"
        elif not holders:
            hint = f"nobody holds it; {start_hint(spec)}"
        else:
            hint = f"held by {', '.join(holders)}, not {spec.name}"
        yield Check(f"role {spec.role} ({spec.name})", spec.name in holders, hint)


# --- this machine -----------------------------------------------------------------------------


def command_ok(cmd: list[str]) -> bool:
    """True if the command runs and exits 0. shutil.which finds .cmd/.exe shims on Windows."""
    path = shutil.which(cmd[0])
    if not path:
        return False
    try:
        done = subprocess.run([path, *cmd[1:]], capture_output=True, timeout=30, check=False)
    except OSError, subprocess.TimeoutExpired:
        return False
    return done.returncode == 0


def local_checks(
    coders: list[Any], run: Callable[[list[str]], bool] = command_ok
) -> Iterator[Check]:
    """Claude Code, the GitHub CLI and Git work, and each coder has its clone with the app venv."""
    for name, cmd, hint in (
        (
            "claude",
            [coders[0].claude_bin, "--version"],
            "install Claude Code or set CODER_CLAUDE_BIN",
        ),
        ("gh", ["gh", "auth", "status"], "run `gh auth login`"),
        ("git", ["git", "--version"], "install Git"),
    ):
        yield Check(f"tool {name}", run(cmd), hint)
    for coder in coders:
        venv = coder.clone / APP_DIR / ".venv"
        if not coder.clone.is_dir():
            hint = f"{coder.clone} is missing; clone the repo there (README, part B, step 2)"
        else:
            hint = f"{venv} is missing; make the demo app's venv in the clone"
        yield Check(f"clone {coder.agent_name} ({coder.clone})", venv.is_dir(), hint)


def gemini_check(frontdesk: ModuleType) -> Check:
    """One short call to the lite model with the front desk's key. Spends a little quota."""
    name = f"gemini {frontdesk.MODEL_LITE}"
    try:
        from google import genai  # the front desk's dependency; not in scripts/requirements.txt
    except ImportError:
        return Check(name, False, "google-genai is missing; run doctor with the front desk's venv")
    try:
        client = genai.Client(api_key=frontdesk.gemini_api_key())
        client.models.generate_content(model=frontdesk.MODEL_LITE, contents="Reply with: ok")
    except Exception as exc:  # any failure is the answer: bad key, 404 model, 429 quota
        return Check(name, False, str(exc)[:200])
    return Check(name, True)


# --- output -----------------------------------------------------------------------------------


def report(checks: Iterable[Check]) -> bool:
    """Print each check as it finishes. True if all passed. A server error mid-way is a FAIL."""
    ok = True
    try:
        for check in checks:
            print(check.line(), flush=True)
            ok = ok and check.ok
    except (Stop, httpx.HTTPError) as exc:
        print(f"FAIL stopped early: {exc}")
        ok = False
    return ok


def dump_once() -> Callable[[httpx.Response], None]:
    """An httpx response hook that prints each path's JSON the first time it is seen."""
    seen: set[str] = set()

    def hook(response: httpx.Response) -> None:
        path = response.request.url.path
        if path in seen or path.endswith("/auth/login"):  # the login answer is not needed
            return
        seen.add(path)
        response.read()
        body = response.json() if response.content else None
        print(f"--- {response.request.method} {path} ({response.status_code})")
        print(json.dumps(body, indent=2))

    return hook


class NoFlags(argparse.Namespace):
    """bootstrap.read_options also reads bootstrap's own flags; doctor has none, so each is None."""

    def __getattr__(self, name: str) -> None:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gemini", action="store_true", help="make one lite-model call too")
    parser.add_argument("--dump", action="store_true", help="print each server response once")
    args = parser.parse_args()
    try:
        # Options before the config modules, as in bootstrap: those load the agents' .env files.
        opts = read_options(NoFlags())
    except Stop as exc:
        print(f"FAIL server: {exc}")
        return 1
    layout = load_layout()
    frontdesk, coder = load_agent_configs()
    coders = [coder.settings(role) for role in coder.ROLES]

    gw = Gateway(opts.api_url, dry_run=True)  # dry run: a write can never go out
    if args.dump:
        gw.http.event_hooks["response"].append(dump_once())
    ok = report(switch_checks(gw, layout, opts.admin_email, opts.admin_password))
    print(FOLLOW_UPS_REMINDER)
    ok = report(local_checks(coders)) and ok
    if args.gemini:
        ok = report([gemini_check(frontdesk)]) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
