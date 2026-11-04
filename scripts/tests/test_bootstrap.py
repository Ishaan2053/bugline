"""bootstrap.py against a fake Switch server: a finished setup changes nothing, an empty server is
set up, a dry run sends no write, and a missing Telegram room stops with the manual step."""

import json
from pathlib import Path

import httpx
import pytest

import bootstrap

SUPPORT, ENG, REF, PKG = "room-support", "room-eng", "ref-1", "pkg-1"
AGENT_IDS = {"bugline-frontdesk": "a-fd", "bugline-repro": "a-repro", "bugline-fixer": "a-fixer"}
ROLES = {"bugline-frontdesk": "frontdesk", "bugline-repro": "reproducer", "bugline-fixer": "fixer"}
# POSTs that only read: the login and the front desk's room detail.
READ_POSTS = {"/gateway/auth/login", "/agents/a-fd/ops/get_room_detail"}


def doc_text(name: str) -> str:
    return (bootstrap.REPO_ROOT / "switch" / "docs" / name).read_text(encoding="utf-8")


class FakeSwitch:
    """A Switch server holding either a finished Bugline setup or nothing but the Telegram room."""

    def __init__(self, finished: bool, telegram_room: bool = True) -> None:
        self.finished = finished
        self.requests: list[tuple[str, str]] = []
        self.registered = dict(AGENT_IDS) if finished else {}
        fixer_rule = {**bootstrap.OWNER_RULE, "rooms": [ENG], "owner_agents": False}
        self.policies = {
            "a-fd": None,
            "a-repro": {"rules": [bootstrap.OWNER_RULE]},
            "a-fixer": {"rules": [fixer_rule]},
        }
        self.rooms = []
        if telegram_room:
            self.rooms.append(self.room_row(SUPPORT, "bugline-support", "telegram"))
        if finished:
            self.rooms.append(self.room_row(ENG, "bugline-eng", "slack"))

    @staticmethod
    def room_row(room_id: str, name: str, kind: str) -> dict:
        return {"id": room_id, "name": name, "bridge_type": kind, "bridge_display_name": kind}

    def handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.requests.append((method, path))
        if method == "POST" and path == "/agents":
            name = json.loads(request.content)["name"]
            self.registered[name] = AGENT_IDS[name]
            return httpx.Response(201, json={"id": AGENT_IDS[name], "api_key": "agent-secret"})
        if method == "POST" and path == "/gateway/rooms/from-yaml":
            return httpx.Response(201, json={"room_id": ENG})
        if method == "POST" and path == "/gateway/api-keys":
            return httpx.Response(201, json={"id": "k", "label": "x", "key": "reg-secret"})
        if method == "GET" or path in READ_POSTS:
            return httpx.Response(200, json=self.read(path))
        return httpx.Response(201, json={"id": "new"})

    def read(self, path: str) -> object:
        done = self.finished
        if path == "/health":
            return {"status": "ok"}
        if path == "/gateway/collaborations":
            return [
                {
                    "bridge_id": "b-tg",
                    "bridge_type": "telegram",
                    "display_name": "Bugline Telegram",
                },
                {"bridge_id": "b-sl", "bridge_type": "slack", "display_name": "Bugline Slack"},
            ]
        if path == "/gateway/rooms":
            return self.rooms
        if path == "/gateway/agents":
            return [
                {"id": i, "name": n, "addressing_policy": self.policies[i] if done else None}
                for n, i in self.registered.items()
            ]
        for key, room_id, members in (
            ("support", SUPPORT, ["a-fd"]),
            ("eng", ENG, list(AGENT_IDS.values())),
        ):
            if path == f"/gateway/rooms/{room_id}":
                text = bootstrap.INSTRUCTIONS[key].read_text(encoding="utf-8") if done else "old"
                return {"agent_ids": members if done else [], "instructions": text}
        links = {SUPPORT: (ENG, "escalates to"), ENG: (SUPPORT, "supports")}
        for room_id, (target, label) in links.items():
            if path == f"/gateway/rooms/{room_id}/linked-rooms":
                return [{"target_room_id": target, "label": label}] if done else []
        if path == "/agents/a-fd/ops/get_room_detail":
            return {"result": {"aliases": {"bugline-frontdesk": "frontdesk"} if done else {}}}
        documents = [{"id": f"doc-{n}", "name": n, "scope": "global"} for n in bootstrap.KIT_DOCS]
        if path in ("/gateway/documents", f"/gateway/packages/{PKG}/documents"):
            return documents if done else []
        if path.startswith("/gateway/documents/doc-"):
            name = path.removeprefix("/gateway/documents/doc-")
            return {
                "name": name,
                "description": doc_text(name).splitlines()[0].lstrip("# ").strip(),
                "instructions": bootstrap.KIT_DOCS[name],
                "content": doc_text(name),
            }
        if path == "/gateway/packages":
            return [{"id": PKG, "name": bootstrap.KIT_NAME}] if done else []
        if path == f"/gateway/packages/{PKG}/references":
            return [{"id": REF}]
        if path == f"/gateway/rooms/{ENG}/references":
            return [{"id": REF, "name": bootstrap.REFERENCE_NAME}]
        if path in (f"/gateway/rooms/{SUPPORT}/packages", f"/gateway/rooms/{ENG}/packages"):
            return [{"id": PKG}] if done else []
        return []

    def writes(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p in self.requests if m != "GET" and p not in READ_POSTS]


def make_layout(tmp_path: Path, registered: bool) -> bootstrap.Layout:
    """Agents and .env files in tmp_path: all set up, or nothing but the .env.example files."""
    agents = []
    for name, role in ROLES.items():
        credentials = tmp_path / name / "credentials.json"
        if registered:
            credentials.parent.mkdir()
            credentials.write_text(json.dumps({"id": AGENT_IDS[name], "api_key": "k"}))
        agents.append(bootstrap.AgentSpec(role, name, f"{name} agent", credentials))
    fd_env, coder_env = tmp_path / "frontdesk" / ".env", tmp_path / "coder" / ".env"
    for path in (fd_env, coder_env):
        path.parent.mkdir()
        path.with_name(".env.example").write_text("SWITCH_API_URL=\n")
    if registered:
        url = "SWITCH_API_URL=http://switch"
        fd_env.write_text(
            f"{url}\nSWITCH_REGISTRATION_KEY=reg\n"
            f"SWITCH_SUPPORT_ROOM_ID={SUPPORT}\nSWITCH_ENG_ROOM_ID={ENG}\n"
        )
        coder_env.write_text(f"{url}\nSWITCH_ENG_ROOM_ID={ENG}\n")
    return bootstrap.Layout(
        agents=tuple(agents),
        room_names={"support": "bugline-support", "eng": "bugline-eng"},
        frontdesk_env=fd_env,
        coder_env=coder_env,
        api_url_var="SWITCH_API_URL",
        registration_key_var="SWITCH_REGISTRATION_KEY",
        frontdesk_room_vars={"support": "SWITCH_SUPPORT_ROOM_ID", "eng": "SWITCH_ENG_ROOM_ID"},
        coder_eng_room_var="SWITCH_ENG_ROOM_ID",
    )


def run(fake: FakeSwitch, layout: bootstrap.Layout, dry_run: bool) -> None:
    opts = bootstrap.Options("http://switch", "admin@example.com", "pw", None, None, dry_run)
    gw = bootstrap.Gateway("http://switch", dry_run, httpx.MockTransport(fake.handle))
    bootstrap.run(gw, layout, opts)


def test_finished_setup_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    fake = FakeSwitch(finished=True)
    run(fake, make_layout(tmp_path, registered=True), dry_run=False)

    assert fake.writes() == []
    out = capsys.readouterr().out
    for word in ("created", "updated", "added", "attached", "would"):
        assert word not in out
    assert out.count(": exists") == 31


def test_empty_server_is_set_up(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    fake = FakeSwitch(finished=False)
    layout = make_layout(tmp_path, registered=False)
    run(fake, layout, dry_run=False)

    writes = fake.writes()
    assert ("POST", "/gateway/api-keys") in writes
    assert writes.count(("POST", "/agents")) == 3
    assert ("POST", "/gateway/rooms/from-yaml") in writes
    assert ("POST", "/gateway/packages") in writes
    assert ("PUT", "/gateway/agents/a-fixer/addressing-policy") in writes
    assert ("POST", "/agents/a-fd/ops/update_room") in writes
    assert "SWITCH_REGISTRATION_KEY=reg-secret" in layout.frontdesk_env.read_text()
    assert f"SWITCH_ENG_ROOM_ID={ENG}" in layout.coder_env.read_text()
    out = capsys.readouterr().out
    assert "reg-secret" not in out and "agent-secret" not in out


def test_dry_run_sends_no_write(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    fake = FakeSwitch(finished=False)
    layout = make_layout(tmp_path, registered=False)
    run(fake, layout, dry_run=True)

    assert fake.writes() == []
    assert not layout.frontdesk_env.exists() and not layout.coder_env.exists()
    assert not any(spec.credentials.exists() for spec in layout.agents)
    out = capsys.readouterr().out
    assert "would send POST /gateway/rooms/from-yaml" in out
    assert "would send POST /gateway/packages" in out
    assert "bugline-eng on Bugline Slack: created from the template (dry run, not sent)" in out


def test_missing_telegram_room_stops_with_the_manual_step(tmp_path: Path) -> None:
    fake = FakeSwitch(finished=True, telegram_room=False)
    with pytest.raises(bootstrap.Stop, match="Add the bot to the Telegram group"):
        run(fake, make_layout(tmp_path, registered=True), dry_run=False)
    assert fake.writes() == []


def test_set_env_values_changes_only_what_differs(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# comment\nA=1\nB=2\n")
    assert bootstrap.set_env_values(path, {"A": "1"}, dry_run=False) == "exists"
    assert bootstrap.set_env_values(path, {"B": "3", "C": "4"}, dry_run=False) == "updated (B, C)"
    assert path.read_text() == "# comment\nA=1\nB=3\nC=4\n"
