"""Adapter contract. Substituting a provider changes one class here (NFR-17)."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class ModelRequest(BaseModel):
    task: str                      # "extract" | "compose"
    template_id: str
    version: str
    variables: dict[str, Any] = Field(default_factory=dict)
    max_output_tokens: int = 3000


class ModelResponse(BaseModel):
    content: dict[str, Any]
    model_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class ProviderError(RuntimeError):
    """Base class for every provider failure. Never leaks past the gateway."""


class ProviderTimeout(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class BudgetExceeded(ProviderError):
    """Raised before anything is sent, when a request exceeds the token budget."""


class LLMAdapter(Protocol):
    """The entire provider surface. Implement this to add a provider."""

    model_id: str

    def invoke(self, request: ModelRequest) -> ModelResponse:  # pragma: no cover
        ...


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~4 characters per token)."""
    return max(1, len(text) // 4)
