"""Tests for project.py: the shipped bugline.toml loads, another file changes every derived name,
and a bad file fails with a message that names the bad key."""

import importlib
import tomllib
from pathlib import Path

import pytest
from common import conventions, project
from common.project import CONFIG_ENV, DEFAULT_PATH, ProjectError, load_project, parse

QA_TOML = """
[project]
name = "qa"
product = "a notes app"
about = "People write notes."
repo_url = "https://github.com/example/notes.git"
default_branch = "trunk"
clone_dir = "notes"
app_dir = "."
test_command = "npm test"
scratch_dir = "scratch"
user_guide = "guide.md"
protected_paths = ["db/schema.sql"]

[tickets]
prefix = "QA"

[report]
summary = "actual"
fields = [
  { name = "title", label = "a one-line summary", about = "Under 10 words" },
  { name = "steps", label = "the steps you took", about = "What you did" },
  { name = "actual", label = "what happened", about = "What went wrong", required = false },
]

[rooms]
support = "qa-help"
eng = "qa-eng"
support_bridge = "mattermost"
eng_bridge = "mattermost"

[agents]
frontdesk = "qa-desk"
reproducer = "qa-repro"
fixer = "qa-fix"
"""


@pytest.fixture
def qa_file(tmp_path: Path) -> Path:
    path = tmp_path / "qa.toml"
    path.write_text(QA_TOML, encoding="utf-8")
    return path


def test_the_shipped_file_names_the_demo() -> None:
    shipped = load_project()
    assert shipped.path == DEFAULT_PATH
    assert shipped.ticket_prefix == "BL" and shipped.ticket_slug == "bl"
    assert shipped.field_names == ("title", "group_id", "steps", "expected", "actual")
    assert [f.heading for f in shipped.ticket_fields()] == ["Group", "Steps", "Expected", "Actual"]
    assert shipped.user_guide_path == DEFAULT_PATH.parent / "demo-app" / "README.md"
    assert shipped.repo_web == "https://github.com/Ishaan2053/bugline"
    assert shipped.app_area == "demo-app" and shipped.scratch_module == "scratch"


def test_another_file_changes_every_derived_name(qa_file, monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(qa_file))
    qa = load_project()
    assert qa.field_names == ("title", "steps", "actual")
    assert qa.required_fields == ("title", "steps")
    assert qa.agents["fixer"] == "qa-fix" and qa.rooms["support"] == "qa-help"
    assert qa.app_area == "qa"  # the app is the whole repo, so the project name stands in
    assert qa.user_guide_path == qa_file.parent / "guide.md"
    assert qa.render("$ticket_prefix-1 in $eng_room") == "QA-1 in qa-eng"
    assert "| `actual` | What went wrong (optional) |" in qa.values()["report_fields"]
    assert qa.values()["report_lines"] == "Steps: <steps>\nActual: <actual>"

    try:
        importlib.reload(conventions)  # conventions reads the prefix at import
        assert conventions.format_ticket_id(1) == "QA-1"
        assert conventions.TICKET_ID_RE.search("see QA-12").group(1) == "12"  # type: ignore[union-attr]
        assert not conventions.TICKET_ID_RE.search("BL-12")
        assert conventions.VERDICT_RE.match("Verified QA-3: https://github.com/a/b/pull/4")
    finally:
        monkeypatch.delenv(CONFIG_ENV)
        importlib.reload(conventions)
    assert conventions.format_ticket_id(1) == "BL-1"


def test_render_refuses_an_unknown_placeholder() -> None:
    with pytest.raises(KeyError):
        load_project().render("$no_such_name")


def bad(edit: str, old: str, tmp_path: Path) -> str:
    """parse() of QA_TOML with `old` replaced by `edit`; returns the error message."""
    data = tomllib.loads(QA_TOML.replace(old, edit))
    with pytest.raises(ProjectError) as caught:
        parse(data, tmp_path / "bad.toml")
    return str(caught.value)


@pytest.mark.parametrize(
    ("old", "edit", "says"),
    [
        ('prefix = "QA"', 'prefix = "qa1"', "1 to 5 capital letters"),
        ('prefix = "QA"', 'prefix = "QA"\ncolour = "red"', "unknown key(s) in [tickets]"),
        ('clone_dir = "notes"', 'clone_dir = ""', "clone_dir must be a non-empty string"),
        ('clone_dir = "notes"\n', "", "[project] is missing ['clone_dir']"),
        ('summary = "actual"', 'summary = "nope"', "summary 'nope' is not a field name"),
        ('name = "title"', 'name = "headline"', "must include 'title'"),
        ('about = "What you did"', 'about = "x", colour = "red"', "unknown key(s) ['colour']"),
        ('fixer = "qa-fix"', 'fixer = "QA Fix"', "[agents] fixer 'QA Fix'"),
        ("[agents]", "[extras]\nx = 1\n[agents]", "unknown table(s) ['extras']"),
    ],
)
def test_bad_values_name_the_key(tmp_path, old, edit, says) -> None:
    assert says in bad(edit, old, tmp_path)


def test_a_missing_file_says_how_to_fix_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / "nope.toml"))
    with pytest.raises(ProjectError, match=CONFIG_ENV):
        load_project()


def test_the_file_is_read_once(qa_file, monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(qa_file))
    first = load_project()
    qa_file.write_text("not toml at all", encoding="utf-8")
    assert load_project() is first
    project._load.cache_clear()
    with pytest.raises(ProjectError, match="not valid TOML"):
        load_project()
