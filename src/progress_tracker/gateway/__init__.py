"""Model gateway (component I) — the system's only egress point.

No other module may import an HTTP client or a provider SDK. The architecture
test in ``tests/test_architecture.py`` enforces this continuously (C-06).
"""

from __future__ import annotations

from .base import (
    BudgetExceeded,
    LLMAdapter,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
)
from .gateway import LLMGateway, build_adapter
from .stub import StubAdapter

__all__ = [
    "BudgetExceeded",
    "LLMAdapter",
    "LLMGateway",
    "ModelRequest",
    "ModelResponse",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderTimeout",
    "StubAdapter",
    "build_adapter",
]
