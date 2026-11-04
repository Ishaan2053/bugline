"""Stand Bugline up on a Switch server with one command: `python scripts/bootstrap.py`.

Run it after the chat-app steps in docs/switch-setup.md. By default bugline-support is on Telegram
(the bot must already be in the bugline-support group) and bugline-eng on Slack;
`--support-bridge` and `--eng-bridge` pick other chat apps, such as the Mattermost that Switch
Console bundles. It does everything else, in order, and prints "created", "updated", "exists" or
"skipped (why)" for each thing, so it is safe to run again:

1. Finds the server's API URL and logs in as the Console admin.
2. Reuses the registration key in agents/frontdesk/.env, or creates one there.
3. Registers bugline-frontdesk, bugline-repro and bugline-fixer if their credentials are missing.
4. Finds bugline-support on its chat app's connection. If it is missing, it creates it from
   switch/bugline-support.template.yaml, or, where Switch cannot create chats (Telegram), stops
   and says what to do.
5. The same for bugline-eng, from switch/bugline.template.yaml.
6. Writes the API URL and room ids into agents/frontdesk/.env and agents/coder/.env.
7. Puts the front desk in both rooms and the two coders in bugline-eng.
8. Sets the access rules: front desk open to anyone, reproducer the owner and the owner's agents,
   fixer the owner only and only in bugline-eng.
9. Sets each room's instructions from switch/, links the rooms, and gives the front desk the
   alias `frontdesk` in both.
10. Creates the bugline-kit package (the three files in switch/docs/ as library documents, plus
    the bugline-repo reference) and attaches it to both rooms.
11. Prints what is left by hand.

Why it reads Switch Console's env file: Console on Windows runs the server natively, and a native
server serves no Gateway web UI, so there is no page for keys, access rules or documents. The
Gateway API under <api>/gateway still works, and the script signs in to it with the local admin
account Console made. Console keeps that login in switch-core.env and finds the ports in
ports.json. For a team server, set SWITCH_API_URL, SWITCH_ADMIN_EMAIL and SWITCH_ADMIN_PASSWORD
instead. No password or key is ever printed.

`--dry-run` logs in and reads, but changes nothing: each write is printed instead of sent, and no
file is written. Names, env variable names and file paths come from the agents' config.py files,
so they are defined once.
"""

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
sys.path.insert(0, str(AGENTS_DIR))  # so `common` imports, as it does for the agents

from common.env import read_env_file  # noqa: E402
from common.switch_client import Credentials, OpError, load_credentials, register  # noqa: E402

ROOM_KEYS = ("support", "eng")  # the keys of the front desk's ROOM_NAMES, in setup order
# The template that creates each room where Switch can create chats.
TEMPLATES = {
    "support": REPO_ROOT / "switch" / "bugline-support.template.yaml",
    "eng": REPO_ROOT / "switch" / "bugline.template.yaml",
}
APP_DIR = "demo-app"  # in the repo and in each coder's clone: the app, its tests and its venv
INSTRUCTIONS = {key: REPO_ROOT / "switch" / f"room-instructions-{key}.md" for key in ROOM_KEYS}
LINKS = [("support", "eng", "escalates to"), ("eng", "support", "supports")]
FRONTDESK_ALIAS = "frontdesk"  # both templates give this alias
REFERENCE_NAME = "bugline-repo"  # made by the template's `references:`
KIT_NAME = "bugline-kit"
KIT_DESCRIPTION = "The rules Bugline's agents work by, and the repo they work on"
KIT_INSTRUCTIONS = "The same files are in switch/docs/ in the repo; the repo copy is the source."
# The library documents: file in switch/docs/ -> when to read it. The text is read at run time.
KIT_DOCS = {
    "intake-rules.md": "Read before sorting a message in bugline-support or posting a ticket.",
    "repro-checklist.md": "Read before reproducing a ticket.",
    "fix-policy.md": "Read before fixing an approved ticket.",
}
# One addressing rule, as the Gateway stores it. "Me and my agents" is Switch's default for a new
# agent; the fixer narrows it to the owner alone in bugline-eng.
OWNER_RULE = {
    "rooms": "*",
    "room_groups": "*",
    "users": [],
    "agents": [],
    "owner": True,
    "owner_agents": True,
    "platform": False,
}


def console_dir() -> Path | None:
    """Where Switch Console for Windows keeps its local server's files."""
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "switchdash" / "local-switch-server" if appdata else None


class Stop(Exception):
    """Something only a person can fix. The message says what to do."""


@dataclass(frozen=True)
class AgentSpec:
    role: str  # "frontdesk", "reproducer" or "fixer"
    name: str
    description: str
    credentials: Path


@dataclass(frozen=True)
class Layout:
    """What bootstrap needs from the agents' config modules, so nothing is restated here."""

    agents: tuple[AgentSpec, ...]
    room_names: dict[str, str]  # "support" / "eng" -> room name
    bridge_types: dict[str, str]  # "support" / "eng" -> chat app, e.g. "telegram"
    frontdesk_env: Path
    coder_env: Path
    api_url_var: str
    registration_key_var: str
    frontdesk_room_vars: dict[str, str]  # "support" / "eng" -> env var for the room id
    coder_eng_room_var: str


def _load(name: str, path: Path) -> ModuleType:
    """Import a config.py under its own name; both agents call their settings module `config`."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_agent_configs() -> tuple[ModuleType, ModuleType]:
    """The front desk's and the coders' config modules, for scripts that need more than Layout."""
    return (
        _load("frontdesk_config", AGENTS_DIR / "frontdesk" / "config.py"),
        _load("coder_config", AGENTS_DIR / "coder" / "config.py"),
    )


def load_layout() -> Layout:
    frontdesk, coder = load_agent_configs()
    coders = [coder.settings(role) for role in ("reproducer", "fixer")]
    return Layout(
        agents=(
            AgentSpec(
                "frontdesk",
                frontdesk.AGENT_NAME,
                frontdesk.AGENT_DESCRIPTION,
                frontdesk.CREDENTIALS_PATH,
            ),
            *(AgentSpec(c.role, c.agent_name, c.description, c.credentials_path) for c in coders),
        ),
        room_names=dict(frontdesk.ROOM_NAMES),
        bridge_types=dict(frontdesk.BRIDGE_TYPES),
        frontdesk_env=frontdesk.AGENT_DIR / ".env",
        coder_env=coder.AGENT_DIR / ".env",
        api_url_var=frontdesk.SWITCH_API_URL_ENV,
        registration_key_var=frontdesk.REGISTRATION_KEY_ENV,
        frontdesk_room_vars=dict(frontdesk.ROOM_ID_ENVS),
        coder_eng_room_var=coder.ENG_ROOM_ID_ENV,
    )


def room_members(layout: Layout) -> dict[str, tuple[AgentSpec, ...]]:
    """Who belongs in each room: the front desk in both, the coders in bugline-eng only."""
    return {"support": layout.agents[:1], "eng": layout.agents}


class Gateway:
    """The server's HTTP API: the Gateway as the Console admin (cookie), ops as an agent (key).

    In a dry run, reads go out and writes are printed instead. A read of something a dry run did
    not create (its id is a placeholder like "<bugline-eng>") returns None.
    """

    def __init__(
        self, api_url: str, dry_run: bool, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.api_url = api_url
        self.dry_run = dry_run
        self.transport = transport
        self.http = httpx.Client(base_url=api_url, transport=transport, timeout=120)

    def check_health(self) -> None:
        try:
            body = self.http.get("/health").json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Stop(
                f"{self.api_url} does not answer /health ({exc}); is the server up?"
            ) from exc
        if body != {"status": "ok"}:
            raise Stop(f"{self.api_url}/health answered {body!r}; that is not the API URL")

    def login(self, email: str, password: str) -> None:
        response = self.http.post(
            "/gateway/auth/login", json={"email": email, "password": password}
        )
        if response.status_code in (400, 401, 403):
            raise Stop(
                "the admin login was refused; check SWITCH_ADMIN_EMAIL/SWITCH_ADMIN_PASSWORD"
            )
        self._json(response)

    def get(self, path: str) -> Any:
        if "<" in path:
            return None
        return self._json(self.http.get("/gateway" + path))

    def write(self, method: str, path: str, body: Any = None) -> Any:
        if self.dry_run:
            print(f"      would send {method} /gateway{path}")
            return None
        return self._json(self.http.request(method, "/gateway" + path, json=body))

    def op(self, creds: Credentials, name: str, read_only: bool, **args: Any) -> Any:
        """Invoke an agent operation as that agent. Only a dry run's writes are skipped."""
        if self.dry_run and not read_only:
            print(f"      would call op {name} as the front desk")
            return None
        response = self.http.post(
            f"/agents/{creds.agent_id}/ops/{name}",
            json=args,
            headers={"Authorization": f"Bearer {creds.api_key}"},
        )
        return (self._json(response) or {}).get("result")

    def done(self, verb: str) -> str:
        """A status for a change: the verb, or the verb marked as not sent in a dry run."""
        return f"{verb} (dry run, not sent)" if self.dry_run else verb

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if response.is_error:
            request = response.request
            detail = response.text[:300]
            raise Stop(
                f"{request.method} {request.url.path} answered {response.status_code}: {detail}"
            )
        return response.json() if response.content else None


def say(thing: str, status: str) -> None:
    print(f"  {thing}: {status}")


def set_env_values(path: Path, values: dict[str, str], dry_run: bool) -> str:
    """Set KEY=value lines in an agent's .env, made from its .env.example if missing.

    Returns the status to print. Only key names are printed, never values.
    """
    existed = path.is_file()
    source = path if existed else path.with_name(".env.example")
    lines = source.read_text(encoding="utf-8").splitlines()
    changed = []
    for key, value in values.items():
        line = f"{key}={value}"
        index = next((i for i, old in enumerate(lines) if old.startswith(f"{key}=")), None)
        if index is None:
            lines.append(line)
        elif lines[index] != line:
            lines[index] = line
        else:
            continue
        changed.append(key)
    if existed and not changed:
        return "exists"
    if not dry_run:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    verb = "updated" if existed else "created"
    status = f"{verb} ({', '.join(changed)})"
    return f"{status} (dry run, not written)" if dry_run else status


# --- the steps ------------------------------------------------------------------------------------


def registration_key(gw: Gateway, layout: Layout, needed: bool) -> str | None:
    """The registration key from agents/frontdesk/.env, or a new one written there."""
    var = layout.registration_key_var
    key = read_env_file(layout.frontdesk_env).get(var)
    if key:
        say(var, "exists (agents/frontdesk/.env)")
        return key
    if not needed:
        say(var, "skipped (every agent already has credentials)")
        return None
    created = gw.write("POST", "/api-keys", {"label": "bugline-bootstrap"})
    if created:
        set_env_values(layout.frontdesk_env, {var: created["key"]}, dry_run=False)
    say(var, gw.done("created (saved in agents/frontdesk/.env)"))
    return created["key"] if created else None


def register_agents(gw: Gateway, layout: Layout, key: str | None) -> dict[str, str]:
    """Register each agent without credentials; return agent name -> id."""
    on_server = {agent["name"]: agent["id"] for agent in gw.get("/agents")}
    for spec in layout.agents:
        if spec.credentials.is_file():
            saved = load_credentials(spec.credentials).agent_id
            if on_server.get(spec.name) != saved:
                raise Stop(
                    f"{spec.credentials} holds agent id {saved}, but the server's {spec.name} "
                    f"is {on_server.get(spec.name)}. Is this the right server?"
                )
            say(spec.name, "exists")
        elif spec.name in on_server:
            raise Stop(
                f"{spec.name} is registered, but {spec.credentials} is missing. Its API key was "
                "shown once: restore the file, or delete the agent in Switch Console and run again."
            )
        elif gw.dry_run:
            say(spec.name, gw.done("created"))
            on_server[spec.name] = f"<{spec.name}>"
        else:
            # The same call as `python agent.py --register` in each agent's folder.
            try:
                creds = register(
                    gw.api_url,
                    key or "",
                    spec.name,
                    spec.description,
                    spec.credentials,
                    gw.transport,
                )
            except OpError as exc:
                raise Stop(f"registering {spec.name} failed: {exc}") from exc
            on_server[spec.name] = creds.agent_id
            say(spec.name, f"created (credentials in {spec.credentials})")
    return {spec.name: on_server[spec.name] for spec in layout.agents}


def app_name(bridge_type: str) -> str:
    """A chat app's name for people: "telegram" -> "Telegram"."""
    return bridge_type.capitalize()


def pick_bridge(bridges: list[dict], bridge_type: str, display_name: str | None, flag: str) -> dict:
    """The one connection of this type, or the one with this display name. `flag` names the
    command-line option that picks a connection, for the message when there are several."""
    found = [b for b in bridges if b.get("bridge_type") == bridge_type]
    names = ", ".join(repr(b.get("display_name")) for b in found) or "none"
    if display_name:
        found = [b for b in found if b.get("display_name") == display_name]
    if len(found) != 1:
        app = app_name(bridge_type)
        hint = f"Pass {flag} with one of them." if names != "none" else f"Connect {app} first."
        raise Stop(
            f"Expected one {app} connection, found {names}. {hint} See docs/switch-setup.md."
        )
    return found[0]


def ensure_room(
    gw: Gateway, key: str, wanted: str, bridge: dict, rooms: list[dict], members: dict[str, str]
) -> str:
    """The room named (or with the id) `wanted` on this connection; created from TEMPLATES[key]
    if missing and Switch can create chats there. `members` is role -> agent name for the template.

    The lookup checks the connection as well as the name, so one server can hold bugline-eng on
    Slack and bugline-eng on Mattermost side by side.
    """
    where = bridge["display_name"]
    for room in rooms:
        if room.get("bridge_id") == bridge["bridge_id"] and wanted in (room["id"], room["name"]):
            say(f"{room['name']} on {where}", "exists")
            return room["id"]
    # Field names as GET /gateway/collaborations returns them (server 0.31). Telegram is the one
    # chat app without channel creation: a bot cannot create a Telegram chat.
    app = app_name(bridge["bridge_type"])
    if not bridge.get("channel_creation_supported"):
        raise Stop(
            f"No room {wanted!r} on {where}, and Switch cannot create {app} chats. Add the bot to "
            f"the {app} group {wanted}, make it an admin, and post one message there so Switch "
            "creates the room. Then run this again."
        )
    if not bridge.get("channel_creation_enabled"):
        raise Stop(
            f"No room {wanted!r} on {where}, and that connection does not allow creating channels. "
            "Turn on 'Allow creating channels from Switch' for it in Switch Console, then run "
            "this again."
        )
    template = TEMPLATES[key]
    inputs = {"room": wanted, "bridge": where, **members}
    body = {
        "yaml": template.read_text(encoding="utf-8"),
        "inputs": inputs,
        "template_name": wanted,
    }
    result = gw.write("POST", "/rooms/from-yaml", body)
    say(f"{wanted} on {where}", gw.done("created from the template"))
    for failure in (result or {}).get("failures") or []:
        print(f"      warning: {failure}")
    return result["room_id"] if result else f"<{wanted}>"


def write_env_files(layout: Layout, api_url: str, room_ids: dict[str, str], dry_run: bool) -> None:
    frontdesk = {layout.api_url_var: api_url}
    frontdesk |= {layout.frontdesk_room_vars[key]: room_ids[key] for key in room_ids}
    coder = {layout.api_url_var: api_url, layout.coder_eng_room_var: room_ids["eng"]}
    for label, path, values in (
        ("agents/frontdesk/.env", layout.frontdesk_env, frontdesk),
        ("agents/coder/.env", layout.coder_env, coder),
    ):
        say(label, set_env_values(path, values, dry_run))


def ensure_members(gw: Gateway, room: str, room_id: str, agent_ids: dict[str, str]) -> None:
    present = set((gw.get(f"/rooms/{room_id}") or {}).get("agent_ids") or [])
    missing = [name for name, agent_id in agent_ids.items() if agent_id not in present]
    if missing:
        gw.write("POST", f"/rooms/{room_id}/agents", {"agent_ids": [agent_ids[n] for n in missing]})
    for name in agent_ids:
        say(f"{name} in {room}", gw.done("added") if name in missing else "exists")


def expected_policies(eng_id: str) -> dict[str, tuple[dict | None, str]]:
    """Role -> (the addressing policy the Gateway should hold, a label for it).

    scripts/doctor.py compares the live rules against the same table.
    """
    fixer_rule = {**OWNER_RULE, "rooms": [eng_id], "owner_agents": False}
    return {
        "frontdesk": (None, "anyone"),
        "reproducer": ({"rules": [OWNER_RULE]}, "the owner and the owner's agents"),
        "fixer": ({"rules": [fixer_rule]}, "the owner only, in bugline-eng only"),
    }


def ensure_access_rules(gw: Gateway, layout: Layout, ids: dict[str, str], eng_id: str) -> None:
    wanted = expected_policies(eng_id)
    current = {agent["id"]: agent.get("addressing_policy") for agent in gw.get("/agents")}
    for spec in layout.agents:
        policy, label = wanted[spec.role]
        agent_id = ids[spec.name]
        if agent_id in current and current[agent_id] == policy:
            say(f"{spec.name} ({label})", "exists")
            continue
        gw.write("PUT", f"/agents/{agent_id}/addressing-policy", {"policy": policy})
        say(f"{spec.name} ({label})", gw.done("updated"))


def ensure_instructions(gw: Gateway, room: str, room_id: str, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if (gw.get(f"/rooms/{room_id}") or {}).get("instructions") == text:
        say(f"{room} instructions", "exists")
        return
    gw.write("PATCH", f"/rooms/{room_id}", {"instructions": text})
    say(f"{room} instructions", gw.done(f"updated from {path.relative_to(REPO_ROOT)}"))


def ensure_link(
    gw: Gateway, names: dict[str, str], ids: dict[str, str], link: tuple[str, str, str]
) -> None:
    source, target, label = link
    existing = gw.get(f"/rooms/{ids[source]}/linked-rooms") or []
    thing = f"{names[source]} -> {names[target]} {label!r}"
    if any(row["target_room_id"] == ids[target] and row["label"] == label for row in existing):
        say(thing, "exists")
        return
    gw.write(
        "POST",
        f"/rooms/{ids[source]}/linked-rooms",
        {"target_room_id": ids[target], "label": label},
    )
    say(thing, gw.done("created"))


def ensure_alias(
    gw: Gateway, creds: Credentials | None, name: str, room: str, room_id: str
) -> None:
    """The Gateway has no alias route, so this runs as the front desk through the ops API."""
    thing = f"@{FRONTDESK_ALIAS} in {room}"
    if creds is None or "<" in room_id:
        say(thing, "skipped (dry run: the front desk or the room does not exist yet)")
        return
    detail = gw.op(creds, "get_room_detail", read_only=True, room_id=room_id) or {}
    if (detail.get("aliases") or {}).get(name) == FRONTDESK_ALIAS:
        say(thing, "exists")
        return
    gw.op(creds, "update_room", read_only=False, room_id=room_id, aliases={name: FRONTDESK_ALIAS})
    say(thing, gw.done("created"))


def ensure_document(gw: Gateway, existing: dict[str, dict], filename: str, when: str) -> str:
    """One library document whose text is the repo file. Returns its id."""
    content = (REPO_ROOT / "switch" / "docs" / filename).read_text(encoding="utf-8")
    fields = {
        "name": filename,
        "description": content.splitlines()[0].lstrip("# ").strip(),
        "instructions": when,
        "content": content,
    }
    if filename not in existing:
        created = gw.write("POST", "/documents", fields)
        say(f"document {filename}", gw.done("created"))
        return created["id"] if created else f"<{filename}>"
    doc_id = existing[filename]["id"]
    current = gw.get(f"/documents/{doc_id}")
    changes = {key: value for key, value in fields.items() if current.get(key) != value}
    if changes:
        gw.write("PATCH", f"/documents/{doc_id}", changes)
    say(f"document {filename}", gw.done(f"updated ({', '.join(changes)})") if changes else "exists")
    return doc_id


def ensure_member(gw: Gateway, package_id: str, kind: str, member_id: str, label: str) -> None:
    """Add a document or reference to the package unless it is in it already."""
    present = {row["id"] for row in gw.get(f"/packages/{package_id}/{kind}") or []}
    if member_id in present:
        say(f"{label} in {KIT_NAME}", "exists")
        return
    gw.write("POST", f"/packages/{package_id}/{kind}/{member_id}")
    say(f"{label} in {KIT_NAME}", gw.done("added"))


def ensure_kit(gw: Gateway, names: dict[str, str], room_ids: dict[str, str]) -> None:
    documents = {d["name"]: d for d in gw.get("/documents") if d.get("scope") == "global"}
    doc_ids = {name: ensure_document(gw, documents, name, when) for name, when in KIT_DOCS.items()}

    package = next((p for p in gw.get("/packages") if p["name"] == KIT_NAME), None)
    if package:
        package_id = package["id"]
        say(f"package {KIT_NAME}", "exists")
    else:
        body = {"name": KIT_NAME, "description": KIT_DESCRIPTION, "instructions": KIT_INSTRUCTIONS}
        created = gw.write("POST", "/packages", body)
        package_id = created["id"] if created else f"<{KIT_NAME}>"
        say(f"package {KIT_NAME}", gw.done("created"))

    for name, doc_id in doc_ids.items():
        ensure_member(gw, package_id, "documents", doc_id, name)
    eng_refs = gw.get(f"/rooms/{room_ids['eng']}/references") or []
    reference = next((r for r in eng_refs if r["name"] == REFERENCE_NAME), None)
    if reference:
        ensure_member(gw, package_id, "references", reference["id"], REFERENCE_NAME)
    else:
        say(f"{REFERENCE_NAME} in {KIT_NAME}", "skipped (not in bugline-eng; the template adds it)")

    for key, room_id in room_ids.items():
        attached = {p["id"] for p in gw.get(f"/rooms/{room_id}/packages") or []}
        if package_id in attached:
            say(f"{KIT_NAME} in {names[key]}", "exists")
        else:
            gw.write("POST", f"/rooms/{room_id}/packages/{package_id}")
            say(f"{KIT_NAME} in {names[key]}", gw.done("attached"))


@dataclass(frozen=True)
class Options:
    api_url: str
    admin_email: str
    admin_password: str
    support_room: str | None
    dry_run: bool
    # Room key -> a flag's value, or nothing to use the default: the chat app (bridge type) and
    # the display name of the connection to use when there are several of that type.
    bridge_types: dict[str, str | None]
    connections: dict[str, str | None]


def run(gw: Gateway, layout: Layout, opts: Options) -> None:
    names = layout.room_names
    kinds = {key: opts.bridge_types.get(key) or kind for key, kind in layout.bridge_types.items()}
    print("1. Server")
    gw.check_health()
    gw.login(opts.admin_email, opts.admin_password)
    say(f"API {opts.api_url}", "ok, logged in as the admin")

    print("2. Registration key")
    needed = any(not spec.credentials.is_file() for spec in layout.agents)
    reg_key = registration_key(gw, layout, needed)

    print("3. Agents")
    agent_ids = register_agents(gw, layout, reg_key)

    print("4-5. Rooms")
    bridges, rooms = gw.get("/collaborations"), gw.get("/rooms")
    rooms = [room for room in rooms if not room.get("archived_at")]
    wanted = {"support": opts.support_room or names["support"], "eng": names["eng"]}
    members = room_members(layout)
    room_ids = {}
    for key in ROOM_KEYS:
        flag = f"--{key}-connection"
        bridge = pick_bridge(bridges, kinds[key], opts.connections.get(key), flag)
        roles = {spec.role: spec.name for spec in members[key]}
        room_ids[key] = ensure_room(gw, key, wanted[key], bridge, rooms, roles)

    print("6. Agent settings files")
    write_env_files(layout, opts.api_url, room_ids, opts.dry_run)

    print("7. Agents in rooms")
    for key, specs in members.items():
        ensure_members(gw, names[key], room_ids[key], {s.name: agent_ids[s.name] for s in specs})

    print("8. Access rules")
    ensure_access_rules(gw, layout, agent_ids, room_ids["eng"])

    print("9. Room instructions, links and aliases")
    for key, room_id in room_ids.items():
        ensure_instructions(gw, names[key], room_id, INSTRUCTIONS[key])
    for link in LINKS:
        ensure_link(gw, names, room_ids, link)
    frontdesk = layout.agents[0]
    creds = load_credentials(frontdesk.credentials) if frontdesk.credentials.is_file() else None
    for key, room_id in room_ids.items():
        ensure_alias(gw, creds, frontdesk.name, names[key], room_id)

    print(f"10. {KIT_NAME}")
    ensure_kit(gw, names, room_ids)

    print("11. Still by hand")
    support, eng = (f"{names[key]} ({app_name(kinds[key])})" for key in ROOM_KEYS)
    print(f"  - Type `!follow-ups off` in {support} and {eng}.")
    print("  - Start the three agents, each in its own terminal (README, 'Reproduce it', part B):")
    print("      cd agents\\frontdesk; .\\.venv\\Scripts\\python agent.py")
    print(
        "      cd agents\\coder; $env:CODER_ROLE = 'reproducer'; .\\.venv\\Scripts\\python agent.py"
    )
    print("      cd agents\\coder; $env:CODER_ROLE = 'fixer'; .\\.venv\\Scripts\\python agent.py")


def read_options(args: argparse.Namespace) -> Options:
    """API URL and admin login: environment first, then Switch Console's own files."""
    local = console_dir()
    api_url = os.environ.get("SWITCH_API_URL", "")
    if not api_url and local and (local / "ports.json").is_file():
        ports = json.loads((local / "ports.json").read_text(encoding="utf-8"))
        api_url = f"http://127.0.0.1:{ports['api']}"
    if not api_url:
        raise Stop("No API URL: set SWITCH_API_URL, or start the local server in Switch Console.")
    console_env = read_env_file(local / "native" / "run" / "switch-core.env") if local else {}
    email = os.environ.get("SWITCH_ADMIN_EMAIL") or console_env.get("GATEWAY_ADMIN_EMAIL")
    password = os.environ.get("SWITCH_ADMIN_PASSWORD") or console_env.get("GATEWAY_ADMIN_PASSWORD")
    if not (email and password):
        raise Stop("No admin login: set SWITCH_ADMIN_EMAIL and SWITCH_ADMIN_PASSWORD.")
    return flag_options(args, api_url.rstrip("/"), email, password)


def flag_options(args: argparse.Namespace, api_url: str, email: str, password: str) -> Options:
    """Options from the command-line flags. A flag that was not given is None, which means the
    default; scripts/doctor.py passes a namespace where every flag is None."""
    return Options(
        api_url,
        email,
        password,
        args.support_room,
        bool(args.dry_run),
        bridge_types={key: getattr(args, f"{key}_bridge") for key in ROOM_KEYS},
        connections={key: getattr(args, f"{key}_connection") for key in ROOM_KEYS},
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="read, but change nothing")
    parser.add_argument("--support-room", help="name or id of the support room (bugline-support)")
    # No defaults shown: they are BRIDGE_TYPES in agents/frontdesk/config.py, which main() loads
    # only after read_options.
    for key in ROOM_KEYS:
        parser.add_argument(
            f"--{key}-bridge", help=f"chat app of the {key} room: telegram, slack, mattermost, ..."
        )
        parser.add_argument(
            f"--{key}-connection",
            help=f"display name of the {key} room's connection, if that app has several",
        )
    # The old name, from when bugline-eng could only be on Slack.
    parser.add_argument(
        "--slack-connection", dest="eng_connection", deprecated=True, help="use --eng-connection"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        # Options first: loading the agents' config modules reads their .env files into the
        # environment, and a stale SWITCH_API_URL there must not win over ports.json.
        opts = read_options(args)
        layout = load_layout()
        if opts.dry_run:
            print("Dry run: reads only; every change is printed, not sent.\n")
        run(Gateway(opts.api_url, opts.dry_run), layout, opts)
    except (Stop, httpx.HTTPError) as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
