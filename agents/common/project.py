"""The project Bugline works on, read once from bugline.toml.

Every name the agents and scripts use for the project lives in that file: the repo and where the
coders clone it, the test command, the scratch folder, the user guide, the ticket prefix, the
fields of a bug report, and the room and agent names. This module reads it with the stdlib
`tomllib`, checks it, and fails at start with a message that names the bad key. The file is
bugline.toml at the repo root, or the one BUGLINE_CONFIG names.

The switch/ documents and the coders' briefs hold $placeholders for these names. `render` fills
them, so the same document reads right for whichever project is configured.
"""

import functools
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from string import Template
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ENV = "BUGLINE_CONFIG"
DEFAULT_PATH = REPO_ROOT / "bugline.toml"

# The keys each table must have. Every one is a non-empty string unless _LISTS names it.
_TABLES = {
    "project": (
        "name",
        "product",
        "about",
        "repo_url",
        "default_branch",
        "clone_dir",
        "app_dir",
        "test_command",
        "scratch_dir",
        "user_guide",
        "protected_paths",
    ),
    "tickets": ("prefix",),
    "report": ("summary", "fields"),
    "rooms": ("support", "eng", "support_bridge", "eng_bridge"),
    "agents": ("frontdesk", "reproducer", "fixer"),
}
_LISTS = {"protected_paths", "fields"}
_FIELD_KEYS = {"name", "label", "heading", "about", "required"}
PREFIX_RE = re.compile(r"[A-Z]{1,5}")
FIELD_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
AGENT_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")  # what Switch accepts for an agent name
TITLE = "title"  # the one field every report has: the ticket's first line


class ProjectError(ValueError):
    """bugline.toml is missing, is not TOML, or has a bad value. The message says which."""


@dataclass(frozen=True)
class Field:
    """One field of a bug report."""

    name: str  # the key in the model's JSON and in the ticket store
    label: str  # how the front desk asks for it: "your group id"
    heading: str  # its name on the ticket: "Group: 1"
    about: str  # what goes in it, for the model and the room
    required: bool = True


@dataclass(frozen=True)
class Project:
    path: Path  # the bugline.toml this came from
    name: str
    product: str
    about: str
    repo_url: str
    default_branch: str
    clone_dir: str
    app_dir: str
    test_command: str
    scratch_dir: str
    user_guide: str
    protected_paths: tuple[str, ...]
    ticket_prefix: str
    fields: tuple[Field, ...]
    summary_field: str
    rooms: dict[str, str]  # "support" / "eng" -> room name
    bridges: dict[str, str]  # "support" / "eng" -> chat app, e.g. "telegram"
    agents: dict[str, str]  # "frontdesk" / "reproducer" / "fixer" -> agent name

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    @property
    def required_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.required)

    @property
    def ticket_slug(self) -> str:
        """The prefix in branch and file names: "BL" -> "bl" (verify-bl-1, bl_1.py)."""
        return self.ticket_prefix.lower()

    @property
    def repo_web(self) -> str:
        """The repo's web address: repo_url without ".git"."""
        return self.repo_url.removesuffix(".git")

    @property
    def user_guide_path(self) -> Path:
        """The user guide on this machine. It is relative to bugline.toml, not to the clone."""
        return self.path.parent / self.user_guide

    @property
    def app_area(self) -> str:
        """The app's folder name, for branch names: "demo-app" -> fix/demo-app-bl-1-...

        The project name stands in when the app is the whole repo (app_dir ".").
        """
        return PurePosixPath(self.app_dir).name or self.name

    @property
    def scratch_module(self) -> str:
        """The scratch folder as a Python package path from app_dir: "scratch"."""
        scratch, app = PurePosixPath(self.scratch_dir), PurePosixPath(self.app_dir)
        relative = scratch.relative_to(app) if scratch.is_relative_to(app) else scratch
        return ".".join(relative.parts)

    def values(self) -> dict[str, str]:
        """The $placeholders `render` fills, by name."""
        return {
            "name": self.name,
            "product": self.product,
            "about": self.about,
            "repo_url": self.repo_url,
            "repo_web": self.repo_web,
            "default_branch": self.default_branch,
            "clone_dir": self.clone_dir,
            "app_dir": self.app_dir,
            "app_area": self.app_area,
            "test_command": self.test_command,
            "scratch_dir": self.scratch_dir,
            "scratch_module": self.scratch_module,
            "user_guide": self.user_guide,
            "protected_paths": ", ".join(f"`{p}`" for p in self.protected_paths),
            "ticket_prefix": self.ticket_prefix,
            "ticket_slug": self.ticket_slug,
            "support_room": self.rooms["support"],
            "eng_room": self.rooms["eng"],
            "frontdesk_agent": self.agents["frontdesk"],
            "reproducer_agent": self.agents["reproducer"],
            "fixer_agent": self.agents["fixer"],
            "report_fields": self._fields_table(),
            "report_lines": "\n".join(f"{f.heading}: <{f.name}>" for f in self.ticket_fields()),
        }

    def ticket_fields(self) -> tuple[Field, ...]:
        """The fields a ticket lists under its first line: all but the title, in order."""
        return tuple(f for f in self.fields if f.name != TITLE)

    def render(self, text: str, **extra: str) -> str:
        """Fill the $placeholders in `text` with values() and `extra`.

        An unknown placeholder raises KeyError, so a typo in a document fails at start.
        """
        return Template(text).substitute(self.values(), **extra)

    def _fields_table(self) -> str:
        rows = [
            f"| `{f.name}` | {f.about}{'' if f.required else ' (optional)'} |" for f in self.fields
        ]
        return "\n".join(["| Field | What it holds |", "| --- | --- |", *rows])


def load_project() -> Project:
    """The project from BUGLINE_CONFIG, or bugline.toml at the repo root. Read once per path."""
    return _load(Path(os.environ.get(CONFIG_ENV) or DEFAULT_PATH))


@functools.cache
def _load(path: Path) -> Project:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError as exc:
        raise ProjectError(f"{path} not found; set {CONFIG_ENV} or restore bugline.toml") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProjectError(f"{path} is not valid TOML: {exc}") from exc
    return parse(data, path)


def parse(data: dict[str, Any], path: Path) -> Project:
    """Check the parsed TOML and build a Project. Raises ProjectError naming the bad key."""
    tables = {name: _table(data, name, keys, path) for name, keys in _TABLES.items()}
    if extra := sorted(set(data) - set(_TABLES)):
        raise ProjectError(f"{path}: unknown table(s) {extra}; expected {sorted(_TABLES)}")
    project, report, agents = tables["project"], tables["report"], tables["agents"]

    prefix = tables["tickets"]["prefix"]
    if not PREFIX_RE.fullmatch(prefix):
        raise ProjectError(f"{path}: [tickets] prefix {prefix!r} must be 1 to 5 capital letters")
    for role, name in agents.items():
        if not AGENT_NAME_RE.fullmatch(name):
            raise ProjectError(
                f"{path}: [agents] {role} {name!r} must match {AGENT_NAME_RE.pattern}"
            )
    fields = tuple(_field(row, i, path) for i, row in enumerate(report["fields"]))
    names = [f.name for f in fields]
    if len(set(names)) != len(names):
        raise ProjectError(f"{path}: [report] fields repeat a name: {names}")
    if TITLE not in names:
        raise ProjectError(f"{path}: [report] fields must include {TITLE!r}, the ticket's title")
    if report["summary"] not in names:
        raise ProjectError(f"{path}: [report] summary {report['summary']!r} is not a field name")

    return Project(
        path=path,
        name=project["name"],
        product=project["product"],
        about=project["about"],
        repo_url=project["repo_url"],
        default_branch=project["default_branch"],
        clone_dir=project["clone_dir"],
        app_dir=project["app_dir"],
        test_command=project["test_command"],
        scratch_dir=project["scratch_dir"],
        user_guide=project["user_guide"],
        protected_paths=tuple(_strings(project["protected_paths"], "protected_paths", path)),
        ticket_prefix=prefix,
        fields=fields,
        summary_field=report["summary"],
        rooms={key: tables["rooms"][key] for key in ("support", "eng")},
        bridges={key: tables["rooms"][f"{key}_bridge"] for key in ("support", "eng")},
        agents=dict(agents),
    )


def _table(data: dict[str, Any], name: str, keys: tuple[str, ...], path: Path) -> dict[str, Any]:
    """Table `name`, with exactly `keys`, each a non-empty string (or a list where _LISTS says)."""
    table = data.get(name)
    if not isinstance(table, dict):
        raise ProjectError(f"{path}: missing table [{name}]")
    if unknown := sorted(set(table) - set(keys)):
        raise ProjectError(f"{path}: unknown key(s) in [{name}]: {unknown}")
    if missing := [key for key in keys if key not in table]:
        raise ProjectError(f"{path}: [{name}] is missing {missing}")
    for key in keys:
        value = table[key]
        if key in _LISTS:
            if not isinstance(value, list) or (key == "fields" and not value):
                raise ProjectError(f"{path}: [{name}] {key} must be a non-empty list")
        elif not isinstance(value, str) or not value.strip():
            raise ProjectError(f"{path}: [{name}] {key} must be a non-empty string")
    return table


def _strings(values: list[Any], key: str, path: Path) -> list[str]:
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise ProjectError(f"{path}: [project] {key} must hold only non-empty strings")
    return values


def _field(row: Any, index: int, path: Path) -> Field:
    where = f"{path}: [report] fields[{index}]"
    if not isinstance(row, dict):
        raise ProjectError(
            f"{where} must be a table like {{ name = ..., label = ..., about = ... }}"
        )
    if unknown := sorted(set(row) - _FIELD_KEYS):
        raise ProjectError(f"{where} has unknown key(s) {unknown}")
    for key in ("name", "label", "about", "heading"):
        if key in row and not (isinstance(row[key], str) and row[key].strip()):
            raise ProjectError(f"{where} {key} must be a non-empty string")
        if key not in row and key != "heading":
            raise ProjectError(f"{where} is missing {key!r}")
    if not FIELD_NAME_RE.fullmatch(row["name"]):
        raise ProjectError(f"{where} name {row['name']!r} must match {FIELD_NAME_RE.pattern}")
    required = row.get("required", True)
    if not isinstance(required, bool):
        raise ProjectError(f"{where} required must be true or false")
    if row["name"] == TITLE and not required:
        raise ProjectError(f"{where}: {TITLE!r} is always required")
    return Field(
        name=row["name"],
        label=row["label"],
        heading=row.get("heading") or row["name"].replace("_", " ").capitalize(),
        about=row["about"],
        required=required,
    )
