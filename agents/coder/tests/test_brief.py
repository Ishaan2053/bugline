"""The coder renders its brief and documents from bugline.toml at start, and its clone, paths and
tool rules follow the configured project."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from common.project import CONFIG_ENV, DEFAULT_PATH

import config
from claude_runner import write_brief

AGENT_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def state(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(config, "STATE_ROOT", tmp_path / "state")
    monkeypatch.delenv("CODER_WORKDIR", raising=False)
    monkeypatch.delenv("CODER_AGENT_NAME", raising=False)
    return tmp_path / "state"


def test_a_document_from_switch_replaces_the_repo_copy(state) -> None:
    settings = config.settings("fixer")  # fix-policy.md, then repro-checklist.md
    text = write_brief(settings, {"fix-policy.md": "POLICY AS EDITED IN SWITCH"}).read_text(
        encoding="utf-8"
    )
    assert "POLICY AS EDITED IN SWITCH" in text
    assert "# Fix policy" not in text  # the repo copy of that one is not used
    assert "# Reproduction checklist" in text  # the one Switch did not give comes from the repo


@pytest.mark.parametrize("role", list(config.ROLES))
def test_each_role_renders_its_brief_and_documents(state, role) -> None:
    settings = config.settings(role)
    path = write_brief(settings)

    text = path.read_text(encoding="utf-8")
    assert path == state / settings.agent_name / "brief.md"
    assert "$" not in text  # every placeholder was filled
    assert config.PROJECT.test_command in text
    assert f"`{settings.agent_name}`" in text and str(settings.clone) in text
    for doc in settings.docs:
        assert doc.read_text(encoding="utf-8").splitlines()[0] in text  # its heading


def test_the_running_agents_own_workdir_wins(state, tmp_path) -> None:
    settings = replace(config.settings("reproducer"), workdir=tmp_path / "elsewhere")
    text = write_brief(settings).read_text(encoding="utf-8")
    assert str(tmp_path / "elsewhere" / config.PROJECT.clone_dir) in text


PROBE = """
import json, sys
sys.path[:0] = [".", ".."]
import config
from claude_runner import write_brief
repro = config.settings("reproducer")
print(json.dumps({
    "name": repro.agent_name,
    "clone": str(repro.clone),
    "allowed": list(repro.allowed_tools),
    "denied": list(repro.denied_tools),
    "brief": write_brief(repro).read_text(encoding="utf-8"),
}))
"""


def test_another_bugline_toml_changes_names_paths_and_the_brief(tmp_path) -> None:
    text = DEFAULT_PATH.read_text(encoding="utf-8")
    for old, new in [
        ('prefix = "BL"', 'prefix = "QA"'),
        ('clone_dir = "bugline"', 'clone_dir = "notes"'),
        ('scratch_dir = "demo-app/scratch"', 'scratch_dir = "demo-app/tmp"'),
        ('test_command = "pytest -q"', 'test_command = "npm test"'),
        ('reproducer = "bugline-repro"', 'reproducer = "qa-repro"'),
    ]:
        assert old in text, old
        text = text.replace(old, new)
    toml = tmp_path / "qa.toml"
    toml.write_text(text, encoding="utf-8")
    env = {**os.environ, CONFIG_ENV: str(toml), "CODER_STATE_DIR": str(tmp_path / "state")}
    for var in ("CODER_WORKDIR", "CODER_AGENT_NAME", "CODER_BRIEF"):
        env.pop(var, None)
    done = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=AGENT_DIR, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)

    assert out["name"] == "qa-repro"
    assert Path(out["clone"]).parts[-2:] == ("qa-repro", "notes")
    assert "Edit(demo-app/tmp/**)" in out["allowed"]
    assert "Edit(demo-app/seed.py)" in out["denied"]
    assert "Verified QA-<n>: <PR url>" in out["brief"]
    assert "demo-app/tmp/qa_<n>.py" in out["brief"] and "npm test" in out["brief"]
    assert "BL-" not in out["brief"]
