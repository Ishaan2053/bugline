"""doctor.py against the fake Switch server from test_bootstrap: a running setup passes, a free role
or stopped agents fail with what to do, and the local checks find a missing clone."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_bootstrap import AGENT_IDS, FakeSwitch, make_layout

import doctor

BRIDGE_IDS = {"telegram": "b-tg", "slack": "b-sl"}  # as FakeSwitch lists the connections


class RunningSwitch(FakeSwitch):
    """The finished setup, plus what doctor reads: bridge status, agent presence, role holders."""

    def __init__(self, live: bool = True, **holders: list[str]) -> None:
        """`live=False` is every agent stopped; `fixer=[]` frees one role."""
        super().__init__(finished=True)
        self.live = live
        held = {"reproducer": ["bugline-repro"], "fixer": ["bugline-fixer"]}
        self.holders = {role: names if live else [] for role, names in held.items()} | holders

    def read(self, path: str) -> object:
        body = super().read(path)
        if path == "/gateway/collaborations":
            for bridge in body:
                bridge["status"] = "active"
        elif path == "/gateway/rooms":
            for room in body:
                room["bridge_id"] = BRIDGE_IDS[room["bridge_type"]]
        elif path.startswith("/gateway/rooms/") and "agent_ids" in body:
            status = "live" if self.live else "offline"
            body["agent_statuses"] = {agent_id: status for agent_id in body["agent_ids"]}
        elif path == "/agents/a-fd/ops/get_room_detail":
            body["result"]["roles"] = [
                {"name": role, "held_by": [{"name": name} for name in names]}
                for role, names in self.holders.items()
            ]
        return body


def check(fake: FakeSwitch, tmp_path: Path, capsys: pytest.CaptureFixture) -> tuple[bool, str]:
    gw = doctor.Gateway("http://switch", True, httpx.MockTransport(fake.handle))
    ok = doctor.report(doctor.switch_checks(gw, make_layout(tmp_path, registered=True), "a", "pw"))
    assert fake.writes() == []  # doctor only reads
    return ok, capsys.readouterr().out


def test_running_setup_passes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ok, out = check(RunningSwitch(), tmp_path, capsys)

    assert ok, out
    assert "FAIL" not in out
    assert "PASS bridge telegram (bugline-support)" in out
    assert "PASS bugline-fixer connected to bugline-eng" in out
    assert "PASS role fixer (bugline-fixer)" in out
    assert "PASS access rule bugline-fixer (the owner only, in bugline-eng only)" in out


def test_free_role_fails_with_the_fix(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ok, out = check(RunningSwitch(fixer=[]), tmp_path, capsys)

    assert not ok
    hint = "nobody holds it; start agents/coder with CODER_ROLE=fixer"
    assert f"FAIL role fixer (bugline-fixer): {hint}" in out
    assert "PASS role reproducer (bugline-repro)" in out


def test_stopped_agents_fail_roles_and_connections(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    ok, out = check(RunningSwitch(live=False), tmp_path, capsys)

    assert not ok
    assert "FAIL bugline-frontdesk connected to bugline-support: status is 'offline'" in out
    assert out.count("connected to") == 4 and "PASS bugline-repro connected" not in out
    assert out.count("FAIL role") == 2


def test_connected_agents(tmp_path: Path) -> None:
    layout = make_layout(tmp_path, registered=True)
    for live, expected in ((True, sorted(AGENT_IDS)), (False, [])):
        fake = RunningSwitch(live=live)
        gw = doctor.Gateway("http://switch", True, httpx.MockTransport(fake.handle))
        assert doctor.connected_agents(gw, layout) == expected


def test_local_checks_find_a_missing_clone(tmp_path: Path) -> None:
    ready = tmp_path / "bugline-repro" / "bugline"
    (ready / doctor.APP_DIR / ".venv").mkdir(parents=True)
    coders = [
        SimpleNamespace(agent_name="bugline-repro", clone=ready, claude_bin="claude"),
        SimpleNamespace(agent_name="bugline-fixer", clone=tmp_path / "nope", claude_bin="claude"),
    ]
    checks = list(doctor.local_checks(coders, run=lambda cmd: cmd[0] != "gh"))

    by_name = {c.name.split(" (")[0]: c for c in checks}
    assert by_name["tool claude"].ok and by_name["tool git"].ok
    assert not by_name["tool gh"].ok
    assert by_name["clone bugline-repro"].ok
    assert not by_name["clone bugline-fixer"].ok
    assert "clone the repo there" in by_name["clone bugline-fixer"].hint
