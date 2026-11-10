"""LLMGateway — component I.

The single egress point. It is the only place in the system that may talk to a
network, and it carries four controls:

* **C-02** minimization and aliasing: names, emails, phone numbers and URLs are
  stripped or substituted before anything leaves the trust boundary.
* **NFR-16** token budget: a request above the configured budget is refused
  *before* it is sent, and provider failures retry with bounded backoff.
* **NFR-15** observability: every call is written to the append-only audit store
  with model id, prompt version, token counts, latency and outcome.
* **NFR-17 / C-18** provider abstraction: callers never see a provider type.
"""

from __future__ import annotations

import random
import re
import time
from typing import Any, Optional

from .. import config
from ..models import AuditEvent
from .base import (
    BudgetExceeded,
    LLMAdapter,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    estimate_tokens,
)
from .stub import StubAdapter

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?<![\w])(?:\+\d[\d\s().-]{6,}\d|\d{3}[\s().-]+\d{3}[\s().-]+\d{4})(?![\w])")
_URL = re.compile(r"https?://\S+")


def build_adapter(provider: Optional[str] = None) -> LLMAdapter:
    """Resolve the configured provider. Adding one means adding a branch here."""
    name = (provider or config.LLM_PROVIDER()).lower()
    if name == "stub":
        return StubAdapter()
    if name == "anthropic":
        from .anthropic_adapter import AnthropicAdapter  # imported lazily on purpose

        return AnthropicAdapter()
    raise ValueError(f"unknown provider {name!r}; expected 'stub' or 'anthropic'")


class LLMGateway:
    def __init__(self, adapter: Optional[LLMAdapter] = None, audit: Any = None,
                 max_input_tokens: Optional[int] = None,
                 max_output_tokens: Optional[int] = None,
                 retries: int = 3, backoff_base: float = 0.25) -> None:
        self.adapter = adapter or build_adapter()
        self.audit = audit
        self.max_input_tokens = max_input_tokens or config.MAX_INPUT_TOKENS()
        self.max_output_tokens = max_output_tokens or config.MAX_OUTPUT_TOKENS()
        self.retries = retries
        self.backoff_base = backoff_base
        #: Every outbound payload this gateway has sent, for test inspection.
        self.sent_payloads: list[dict[str, Any]] = []

    # ------------------------------------------------------------ minimization

    @staticmethod
    def redact(text: str, aliases: Optional[dict[str, str]] = None) -> str:
        """Substitute aliases, then strip contact details (C-02)."""
        out = text
        for real, alias in (aliases or {}).items():
            if real:
                out = re.sub(rf"\b{re.escape(real)}\b", alias, out, flags=re.IGNORECASE)
        out = _EMAIL.sub("[redacted-email]", out)
        out = _URL.sub("[redacted-url]", out)
        out = _PHONE.sub("[redacted-phone]", out)
        return out

    #: Only free-text values are rewritten. Identifiers, category keys and
    #: citation lists are left alone: an early version redacted everything, and
    #: the phone-number pattern silently rewrote UUIDs that contained a long run
    #: of digits, which broke the citations that depend on them. Scrubbing is a
    #: text operation, so it is applied only to text fields.
    TEXT_FIELDS = frozenset({
        "note_text", "instructions", "error_text", "quoted_text",
        "text", "practice", "homework", "topics", "label",
    })

    def _minimize(self, variables: dict[str, Any],
                  aliases: Optional[dict[str, str]]) -> dict[str, Any]:
        def walk(value: Any, key: Optional[str]) -> Any:
            if isinstance(value, str):
                return self.redact(value, aliases) if key in self.TEXT_FIELDS else value
            if isinstance(value, list):
                return [walk(v, key) for v in value]
            if isinstance(value, dict):
                return {k: walk(v, k) for k, v in value.items()}
            return value

        return {k: walk(v, k) for k, v in variables.items()}

    # --------------------------------------------------------------- invocation

    def invoke(self, request: ModelRequest, *, record_id: Optional[str] = None,
               aliases: Optional[dict[str, str]] = None) -> ModelResponse:
        safe_vars = self._minimize(request.variables, aliases)
        safe = request.model_copy(update={
            "variables": safe_vars,
            "max_output_tokens": min(request.max_output_tokens, self.max_output_tokens),
        })

        estimated = estimate_tokens(str(safe_vars))
        if estimated > self.max_input_tokens:
            self._log(record_id, safe, None, "error",
                      f"token budget exceeded: {estimated} > {self.max_input_tokens}")
            raise BudgetExceeded(
                f"request needs ~{estimated} input tokens, budget is {self.max_input_tokens}"
            )

        self.sent_payloads.append({"task": safe.task, "variables": safe_vars})

        last: Optional[ProviderError] = None
        for attempt in range(1, self.retries + 1):
            started = time.perf_counter()
            try:
                response = self.adapter.invoke(safe)
            except (ProviderTimeout, ProviderRateLimited) as exc:
                last = exc
                self._log(record_id, safe, None, "error",
                          f"{type(exc).__name__} on attempt {attempt}/{self.retries}")
                if attempt < self.retries:
                    time.sleep(self.backoff_base * (2 ** (attempt - 1))
                               * (1 + random.random() * 0.1))
                continue
            except ProviderError as exc:
                self._log(record_id, safe, None, "error", str(exc))
                raise
            response.latency_ms = response.latency_ms or int(
                (time.perf_counter() - started) * 1000)
            self._log(record_id, safe, response, "ok", None)
            return response

        assert last is not None
        raise last

    # ---------------------------------------------------------------- audit

    def _log(self, record_id: Optional[str], request: ModelRequest,
             response: Optional[ModelResponse], outcome: str, reason: Optional[str]) -> None:
        if self.audit is None:
            return
        self.audit.append(AuditEvent(
            record_id=record_id,
            actor="I:gateway",
            action=f"model.{request.task}",
            target=request.template_id,
            model_id=getattr(self.adapter, "model_id", None),
            prompt_version=request.version,
            tokens_in=response.tokens_in if response else None,
            tokens_out=response.tokens_out if response else None,
            latency_ms=response.latency_ms if response else None,
            outcome=outcome,  # type: ignore[arg-type]
            reason=reason,
        ))
