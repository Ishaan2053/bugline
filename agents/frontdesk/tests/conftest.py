"""Shared fixtures: temporary paths for calls.log and the reference docs, and a fake client."""

from pathlib import Path

import pytest
from fakes import FakeClient

import classify
import config


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep tests away from the real calls.log and give them small reference docs."""
    rules = tmp_path / "intake-rules.md"
    rules.write_text("TEST INTAKE RULES", encoding="utf-8")
    faq = tmp_path / "README.md"
    faq.write_text("TEST USER GUIDE", encoding="utf-8")
    monkeypatch.setattr(config, "CALLS_LOG_PATH", tmp_path / "calls.log")
    monkeypatch.setattr(config, "INTAKE_RULES_PATH", rules)
    monkeypatch.setattr(config, "USER_FAQ_PATH", faq)
    return tmp_path


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """Install a FakeClient in place of the Gemini client; the test fills `fake.replies`."""
    client = FakeClient()
    monkeypatch.setattr(classify, "get_client", lambda: client)
    return client
