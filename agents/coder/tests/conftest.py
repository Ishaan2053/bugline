"""Shared fixtures: settings for a reproducer whose brief and working directory are temporary."""

from pathlib import Path

import pytest

import config


@pytest.fixture
def settings(tmp_path: Path) -> config.Settings:
    brief = tmp_path / "reproducer.md"
    brief.write_text("TEST BRIEF", encoding="utf-8")
    role = config.ROLES["reproducer"]
    return config.Settings(
        role="reproducer",
        agent_name=role.agent_name,
        description=role.description,
        brief=brief,
        workdir=tmp_path,
        allowed_tools=role.allowed,
        denied_tools=role.denied,
    )
