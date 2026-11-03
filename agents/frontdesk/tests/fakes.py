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
