"""Every Gemini call the front desk makes: classify a message, check for a duplicate, answer.

`call_model` is the only function that talks to the API. It retries HTTP 429 with exponential
backoff, raises `RateLimited` when it gives up, and writes one line per attempt to calls.log so
we can count model calls per loop. Prompts live in prompts/*.md; the intake rules and the user
guide are read from the repo at call time and inserted, so no rule is written twice.
"""

import functools
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, make_dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any, Literal, get_args

from google import genai
from google.genai import errors, types

import config
from store import Draft, Ticket

log = logging.getLogger(__name__)

Kind = Literal["bug", "question", "request", "off-topic"]
KINDS: tuple[str, ...] = get_args(Kind)


class RateLimited(Exception):
    """Gemini kept answering 429 after every retry. The caller tells the user to wait."""


# The report fields come from bugline.toml ([report] fields), in the order a ticket shows them.
REPORT_FIELDS: tuple[str, ...] = config.PROJECT.field_names
# Only these can be missing: a report without an optional field is still complete.
REQUIRED_FIELDS: tuple[str, ...] = config.PROJECT.required_fields

# A bug report as the model extracted it: one string per configured field, "" when unknown.
# Built from the field names, so Report(title=..., steps=...) and asdict() work for any project.
Report = make_dataclass(
    "Report",
    [(name, str, field(default="")) for name in REPORT_FIELDS],
    frozen=True,
    module=__name__,
)
Report.__doc__ = "A bug report as the model extracted it. Unknown fields are empty strings."


@dataclass(frozen=True)
class Classification:
    kind: Kind
    missing: list[str]
    report: Report


# JSON schemas from CLAUDE.md section 6, built once from the types above.
CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "missing": {"type": "array", "items": {"type": "string", "enum": list(REQUIRED_FIELDS)}},
        "report": {
            "type": "object",
            "properties": {name: {"type": "string"} for name in REPORT_FIELDS},
            "required": list(REPORT_FIELDS),
        },
    },
    "required": ["kind", "missing", "report"],
}

DUPLICATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "duplicate_of": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["duplicate_of", "confidence"],
}


@functools.cache
def get_client() -> genai.Client:
    """One shared Gemini client, created on first use. Tests replace this function."""
    return genai.Client(api_key=config.gemini_api_key())


def call_model(
    model: str,
    prompt: str,
    schema: dict[str, Any] | None = None,
    *,
    purpose: str,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | str:
    """Send one prompt. With a schema, return the parsed JSON object; without, return the text.

    On HTTP 429 wait BACKOFF_START_S, doubling up to BACKOFF_CAP_S, for BACKOFF_TRIES attempts
    in total, then raise RateLimited. Other API errors are raised unchanged.
    """
    cfg = None
    if schema is not None:
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json", response_json_schema=schema
        )
    delay = config.BACKOFF_START_S
    for attempt in range(1, config.BACKOFF_TRIES + 1):
        try:
            response = get_client().models.generate_content(
                model=model, contents=prompt, config=cfg
            )
            break
        except errors.APIError as exc:
            if exc.code != 429:
                raise
            _log_call(model, purpose, None, status="429")
            if attempt == config.BACKOFF_TRIES:
                raise RateLimited(f"{model} still rate-limited after {attempt} tries") from exc
            sleep(delay)
            delay = min(delay * 2, config.BACKOFF_CAP_S)
    _log_call(model, purpose, response.usage_metadata, status="ok")
    text = response.text or ""
    return json.loads(text) if schema is not None else text.strip()


def classify(message: str, draft: Draft | None = None) -> Classification:
    """Decide what kind of message this is and pull out a bug report if there is one.

    With a draft (an earlier incomplete report from the same user), the model merges the new
    message into it.
    """
    prompt = _prompt(
        "classify",
        intake_rules=_intake_rules(),
        draft=json.dumps(asdict(draft), indent=2) if draft else "none",
        message=message,
    )
    data = call_model(config.MODEL_LITE, prompt, CLASSIFY_SCHEMA, purpose="classify")
    assert isinstance(data, dict)
    if data["kind"] not in KINDS:
        raise ValueError(f"model returned unknown kind {data['kind']!r}")
    report = data.get("report") or {}
    return Classification(
        kind=data["kind"],
        missing=[name for name in data.get("missing", []) if name in REQUIRED_FIELDS],
        report=Report(**{name: str(report.get(name) or "") for name in REPORT_FIELDS}),
    )


def check_duplicate(report: Report, open_tickets: Sequence[Ticket]) -> str | None:
    """Return the id of the open ticket this report duplicates, or None.

    Skips the model call when nothing is open. A match counts only if the model is at least
    DUPLICATE_MIN_CONFIDENCE sure and names a ticket that is actually open.
    """
    if not open_tickets:
        return None
    ticket_lines = "\n".join(f"- {t.ticket_id}: {t.title} | {t.summary}" for t in open_tickets)
    prompt = _prompt("duplicate", tickets=ticket_lines, report=json.dumps(asdict(report), indent=2))
    data = call_model(config.MODEL_LITE, prompt, DUPLICATE_SCHEMA, purpose="duplicate")
    assert isinstance(data, dict)
    match = data.get("duplicate_of")
    if not match or float(data.get("confidence", 0)) < config.DUPLICATE_MIN_CONFIDENCE:
        return None
    return match if match in {t.ticket_id for t in open_tickets} else None


def answer_question(question: str) -> str:
    """Answer a user's question from the user guide and intake rules, in at most 10 lines."""
    prompt = _prompt(
        "answer",
        max_lines=str(config.REPLY_MAX_LINES),
        user_faq=_reference(config.USER_FAQ_PATH),
        intake_rules=_intake_rules(),
        question=question,
    )
    text = call_model(config.MODEL_DEFAULT, prompt, purpose="answer")
    assert isinstance(text, str)
    # The prompt asks for short replies; this makes sure of it.
    return "\n".join(text.splitlines()[: config.REPLY_MAX_LINES])


def _prompt(name: str, **values: str) -> str:
    """Load prompts/<name>.md and fill its $placeholders: `values`, then the project's names."""
    template = (config.PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return Template(template).substitute(config.PROJECT.values(), **values)


def _intake_rules() -> str:
    """The intake rules with the project's names and report fields filled in."""
    return config.PROJECT.render(_reference(config.INTAKE_RULES_PATH))


def _reference(path: Path) -> str:
    """Text of a reference doc, or "" with a warning if it is missing."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("reference doc not found: %s", path)
        return ""


def _log_call(
    model: str, purpose: str, usage: types.GenerateContentResponseUsageMetadata | None, status: str
) -> None:
    """Append one tab-separated line: time, model, purpose, status, prompt/output/total tokens.

    Output tokens are the visible answer; total also counts the model's thinking tokens.
    """
    tokens = [0, 0, 0]
    if usage:
        tokens = [
            usage.prompt_token_count or 0,
            usage.candidates_token_count or 0,
            usage.total_token_count or 0,
        ]
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    columns = [stamp, model, purpose, status, *map(str, tokens)]
    path = config.CALLS_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("\t".join(columns) + "\n")
