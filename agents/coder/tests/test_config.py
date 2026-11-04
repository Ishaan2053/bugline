"""Tests for the coder's settings: the default working directory on each platform."""

import sys
from pathlib import Path

import pytest

import config


@pytest.fixture(autouse=True)
def no_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODER_WORKDIR", raising=False)
    monkeypatch.delenv("CODER_AGENT_NAME", raising=False)


def test_workdir_defaults_to_the_home_folder_off_windows(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    settings = config.settings("reproducer")

    assert settings.workdir == tmp_path / "bugline-agents" / "bugline-repro"
    assert settings.clone == tmp_path / "bugline-agents" / "bugline-repro" / "bugline"


def test_workdir_defaults_to_the_c_drive_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert config.settings("fixer").workdir == Path(r"C:\bugline-agents") / "bugline-fixer"


def test_coder_workdir_wins_over_the_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("CODER_WORKDIR", str(tmp_path))

    assert config.settings("reproducer").workdir == tmp_path
