"""Tests for the Gemini calls, using a fake client so no request leaves the machine."""

import logging
import os

import pytest
from fakes import ok, rate_limited

import classify
import config
from classify import RateLimited, Report
from store import Draft, Store

BUG = {
    "kind": "bug",
    "missing": ["group_id"],
    "report": {
        "title": "Share link returns an error",
        "steps": "Open the share link",
        "expected": "Group summary",
        "actual": "Server error",
        "group_id": "",
    },
}


@pytest.fixture
def tickets():
    store = Store(":memory:")
    store.open_ticket("u1", "Asha", "support", "Share link 500", "ZeroDivisionError", {})
    store.open_ticket("u2", "Ravi", "support", "Totals off by one", "rounding", {})
    return store.open_tickets()


def test_classify_parses_schema(fake) -> None:
    fake.replies = [ok(BUG)]
    result = classify.classify("the share link gives an error")
    assert result.kind == "bug"
    assert result.missing == ["group_id"]
    assert result.report == Report(**BUG["report"])
    request = fake.requests[0]
    assert request["model"] == config.MODEL_LITE
    assert request["config"].response_json_schema == classify.CLASSIFY_SCHEMA
    assert "TEST INTAKE RULES" in request["contents"]
    assert "the share link gives an error" in request["contents"]


def test_classify_includes_draft(fake) -> None:
    fake.replies = [ok({**BUG, "missing": []})]
    draft = Draft(report=BUG["report"], missing=["group_id"])
    result = classify.classify("group 1", draft=draft)
    assert result.missing == []
    assert '"missing": [\n    "group_id"' in fake.requests[0]["contents"]


def test_duplicate_match(fake, tickets) -> None:
    fake.replies = [ok({"duplicate_of": "BL-1", "confidence": 0.9})]
    assert classify.check_duplicate(Report(title="Share link broken"), tickets) == "BL-1"
    assert "BL-2: Totals off by one | rounding" in fake.requests[0]["contents"]


def test_duplicate_below_threshold_is_no_match(fake, tickets) -> None:
    fake.replies = [ok({"duplicate_of": "BL-1", "confidence": 0.69})]
    assert classify.check_duplicate(Report(title="Share link broken"), tickets) is None


def test_duplicate_unknown_ticket_is_no_match(fake, tickets) -> None:
    fake.replies = [ok({"duplicate_of": "BL-7", "confidence": 0.95})]
    assert classify.check_duplicate(Report(title="Share link broken"), tickets) is None


def test_duplicate_skips_call_without_open_tickets(fake) -> None:
    assert classify.check_duplicate(Report(title="anything"), []) is None
    assert fake.requests == []


def test_backoff_then_rate_limited(fake) -> None:
    fake.replies = [rate_limited() for _ in range(config.BACKOFF_TRIES)]
    delays: list[float] = []
    with pytest.raises(RateLimited):
        classify.call_model(config.MODEL_LITE, "hi", purpose="test", sleep=delays.append)
    assert delays == [2.0, 4.0, 8.0, 16.0]
    assert len(fake.requests) == config.BACKOFF_TRIES


def test_backoff_recovers_and_caps(fake, monkeypatch) -> None:
    monkeypatch.setattr(config, "BACKOFF_TRIES", 7)
    fake.replies = [rate_limited() for _ in range(6)] + [ok("fine")]
    delays: list[float] = []
    assert classify.call_model(config.MODEL_LITE, "hi", purpose="test", sleep=delays.append) == (
        "fine"
    )
    assert delays == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_calls_log_line(fake, isolated_paths) -> None:
    fake.replies = [rate_limited(), ok(BUG, tokens=(321, 45, 400))]
    classify.call_model(
        config.MODEL_LITE, "hi", classify.CLASSIFY_SCHEMA, purpose="classify", sleep=lambda s: None
    )
    lines = (isolated_paths / "calls.log").read_text(encoding="utf-8").splitlines()
    assert [line.split("\t")[1:] for line in lines] == [
        [config.MODEL_LITE, "classify", "429", "0", "0", "0"],
        [config.MODEL_LITE, "classify", "ok", "321", "45", "400"],
    ]


def test_answer_uses_default_model_and_stays_short(fake) -> None:
    fake.replies = [ok("\n".join(f"line {i}" for i in range(15)))]
    answer = classify.answer_question("how do I settle up?")
    assert len(answer.splitlines()) == config.REPLY_MAX_LINES
    assert fake.requests[0]["model"] == config.MODEL_DEFAULT
    assert "TEST USER GUIDE" in fake.requests[0]["contents"]


def test_missing_reference_doc_warns(fake, monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.setattr(config, "INTAKE_RULES_PATH", tmp_path / "nope.md")
    fake.replies = [ok(BUG)]
    with caplog.at_level(logging.WARNING):
        classify.classify("the share link gives an error")
    assert "reference doc not found" in caplog.text


@pytest.mark.live
@pytest.mark.skipif(
    not (os.environ.get(config.GEMINI_KEY_ENV) and os.environ.get("BUGLINE_LIVE") == "1"),
    reason="live Gemini call; set GEMINI_API_KEY and BUGLINE_LIVE=1",
)
def test_live_classify() -> None:
    result = classify.classify(
        "When I open the share link for our Goa trip group it just says Internal Server Error."
        " I expected to see the group summary."
    )
    print(f"\nlive classification: {result}")
    assert result.kind == "bug"
