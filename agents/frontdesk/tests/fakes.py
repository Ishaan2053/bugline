"""A fake Gemini client and response builders, so tests never call the real API."""

import json
from types import SimpleNamespace
from typing import Any

from google.genai import errors, types


def ok(payload: dict[str, Any] | str, tokens: tuple[int, int, int] = (100, 20, 130)) -> Any:
    """A response shaped like the SDK's: `.text` plus `.usage_metadata`."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=tokens[0],
        candidates_token_count=tokens[1],
        total_token_count=tokens[2],
    )
    return SimpleNamespace(text=text, usage_metadata=usage)


def rate_limited() -> errors.ClientError:
    """The error the SDK raises for HTTP 429."""
    return errors.ClientError(
        429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )


def overloaded() -> errors.ServerError:
    """The error the SDK raises for HTTP 503, as Gemini sent it live on Nov 5."""
    message = "This model is currently experiencing high demand."
    return errors.ServerError(
        503, {"error": {"code": 503, "message": message, "status": "UNAVAILABLE"}}
    )


def server_error() -> errors.ServerError:
    """HTTP 500: not in RETRY_STATUSES, so it is raised at once."""
    return errors.ServerError(500, {"error": {"code": 500, "message": "x", "status": "INTERNAL"}})


class FakeClient:
    """Replays queued replies (raising the ones that are exceptions) and records each request."""

    def __init__(self) -> None:
        self.replies: list[Any] = []
        self.requests: list[dict[str, Any]] = []
        self.models = self  # the real client is called as client.models.generate_content(...)

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.requests.append({"model": model, "contents": contents, "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
