"""Anthropic adapter — the live model path.

This is the ONLY module in the project permitted to import an HTTP client, and
it is imported lazily so the prototype runs with no network, no key and no extra
dependency when ``SPT_LLM_PROVIDER=stub`` (the default).

Swapping provider means writing one more class with the same two members
(``model_id`` and ``invoke``) and adding a branch in ``build_adapter`` — no
calling code changes (NFR-17 / C-18).
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx  # the single permitted HTTP dependency, confined to this module

from .. import config
from .base import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

EXTRACT_SYSTEM = """You extract language errors a tutor described in a lesson note.

Rules you must follow exactly:
- Report ONLY errors the note explicitly describes. Never infer an error from the
  absence of a mention, and never add general knowledge about Spanish learners.
- One entry per distinct error. If the note mentions the same error twice, return
  one entry with two source references.
- `category` MUST be one of the supplied taxonomy keys. Never invent a category.
- `quoted_text` MUST be copied verbatim from the note, and `span_start`/`span_end`
  MUST be the character offsets of that exact substring.
- If the note describes no identifiable error, return an empty list.

Return ONLY valid JSON of the form:
{"errors":[{"error_text":str,"category":str,"severity":"low"|"medium"|"high",
            "source_refs":[{"span_start":int,"span_end":int,"quoted_text":str}]}]}"""

COMPOSE_SYSTEM = """You draft a student-facing Spanish progress summary from findings.

Rules you must follow exactly:
- Every block and every goal MUST cite at least one supplied finding_id.
- NEVER state, imply or revise the student's CEFR level. The level is supplied and
  is the tutor's judgement; only a block of kind "level" may mention it, and it must
  cite "tutor_level".
- Produce between 2 and 4 goals, highest-value first.
- Never promise an outcome or a timeline.
- Respect the language mix and sentence length for the supplied level.

Return ONLY valid JSON of the form:
{"blocks":[{"kind":"level"|"progress"|"pattern"|"goal"|"practice","text":str,
            "cites":[str]}],
 "goals":[{"text":str,"practice":str,"cites":[str]}]}"""


class AnthropicAdapter:
    def __init__(self, api_key: str | None = None, model_id: str | None = None,
                 timeout: float = 60.0) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add a key, "
                "or leave SPT_LLM_PROVIDER=stub to run offline."
            )
        self.model_id = model_id or config.MODEL_ID()
        self.timeout = timeout

    def invoke(self, request: ModelRequest) -> ModelResponse:
        system = EXTRACT_SYSTEM if request.task == "extract" else COMPOSE_SYSTEM
        payload = {
            "model": self.model_id,
            "max_tokens": request.max_output_tokens,
            "system": system,
            "messages": [{
                "role": "user",
                "content": json.dumps(request.variables, ensure_ascii=False, default=str),
            }],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        try:
            response = httpx.post(API_URL, json=payload, headers=headers,
                                  timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(str(exc)) from exc

        if response.status_code == 429:
            raise ProviderRateLimited("provider returned 429")
        if response.status_code >= 500:
            raise ProviderTimeout(f"provider returned {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(f"provider returned {response.status_code}: {response.text[:200]}")

        body: dict[str, Any] = response.json()
        text = "".join(part.get("text", "") for part in body.get("content", []))
        content = _parse_json(text)
        usage = body.get("usage", {})
        return ModelResponse(
            content=content,
            model_id=body.get("model", self.model_id),
            tokens_in=int(usage.get("input_tokens", 0)),
            tokens_out=int(usage.get("output_tokens", 0)),
        )


def _parse_json(text: str) -> dict[str, Any]:
    """Models sometimes wrap JSON in prose or fences. One tolerant parse, then fail."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("```")[1]
        candidate = candidate[4:] if candidate.lower().startswith("json") else candidate
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise ProviderError("provider did not return parseable JSON")
