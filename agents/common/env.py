"""Environment helpers for agents and scripts: read a .env file, fail clearly on a missing value."""

import os
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    """The KEY=VALUE lines of `path` (comments skipped), or {} if there is no such file."""
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("\"'")
    return values


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from `path` into the environment, for runs outside Docker.

    Variables that are already set win, so the shell and Docker's env_file override the file.
    """
    for key, value in read_env_file(path).items():
        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    """Value of env var `name`. Raises if it is not set, so the failure is obvious at start."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; see the agent's .env.example")
    return value
