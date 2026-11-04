"""The front desk follows bugline.toml: with another file, its schema, ticket ids and escalation
use that file's prefix, names and report fields. Run in a fresh interpreter, because the config
modules read the file once at import, the way the agent does at start."""

import json
import os
import subprocess
import sys
from pathlib import Path

from common.project import CONFIG_ENV, DEFAULT_PATH

import config
import messages
from classify import REPORT_FIELDS, Report

AGENT_DIR = Path(__file__).resolve().parent.parent

# A copy of the shipped file with prefix QA, other room and agent names, and four report fields
# (no group_id). Each pair is (text in bugline.toml, its replacement).
EDITS = [
    ('prefix = "BL"', 'prefix = "QA"'),
    ('support = "bugline-support"', 'support = "qa-help"'),
    ('frontdesk = "bugline-frontdesk"', 'frontdesk = "qa-desk"'),
]

PROBE = """
import json, sys
sys.path[:0] = [".", ".."]
from dataclasses import asdict
import classify, config, messages
report = classify.Report(**{name: name.upper() for name in classify.REPORT_FIELDS})
print(json.dumps({
    "missing_enum": classify.CLASSIFY_SCHEMA["properties"]["missing"]["items"]["enum"],
    "ticket": config.format_ticket_id(1),
    "agent": config.AGENT_NAME,
    "escalation": messages.escalation(config.format_ticket_id(1), report, "Asha").splitlines(),
    "ask": messages.ask_missing(["steps", "actual"]),
    "guide": str(config.USER_FAQ_PATH),
}))
"""


def qa_config(tmp_path: Path) -> Path:
    text = DEFAULT_PATH.read_text(encoding="utf-8")
    for old, new in EDITS:
        assert old in text, old
        text = text.replace(old, new)
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines if not line.lstrip().startswith('{ name = "group_id"')]
    assert len(kept) == len(lines) - 1
    path = tmp_path / "qa.toml"
    path.write_text("".join(kept), encoding="utf-8")
    return path


def test_another_bugline_toml_changes_ids_fields_and_names(tmp_path: Path) -> None:
    env = {**os.environ, CONFIG_ENV: str(qa_config(tmp_path))}
    env.pop("FRONTDESK_USER_FAQ", None)
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=AGENT_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(done.stdout)

    assert out["missing_enum"] == ["title", "steps", "expected", "actual"]
    assert out["ticket"] == "QA-1"
    assert out["agent"] == "qa-desk"
    assert out["escalation"] == [
        "QA-1: TITLE",
        "Reporter: Asha (qa-help)",
        "Steps: STEPS",
        "Expected: EXPECTED",
        "Actual: ACTUAL",
        "@reproducer please reproduce and post your verdict in this thread.",
    ]
    assert out["ask"] == (
        "Thanks. To pass this to the team I need the steps you took and what happened instead."
        " Reply here and mention me."
    )
    assert Path(out["guide"]) == tmp_path / "demo-app" / "README.md"  # relative to the toml


def test_the_intake_rules_show_the_ticket_the_front_desk_posts() -> None:
    rules = (config.REPO_ROOT / "switch" / "docs" / "intake-rules.md").read_text(encoding="utf-8")
    rendered = config.PROJECT.render(rules)
    placeholders = Report(**{name: f"<{name}>" for name in REPORT_FIELDS})
    shape = messages.escalation(f"{config.TICKET_PREFIX}-<n>", placeholders, "<name>")
    assert f"```\n{shape}\n```" in rendered
    for name in REPORT_FIELDS:
        assert f"| `{name}` |" in rendered
