"""Components A-I. One module per component, matching the Solution Design Report."""

from __future__ import annotations

from . import composition, export, extraction, guard, intake, patterns, review, validator
from .orchestrator import PipelineResult, run_pipeline

__all__ = [
    "PipelineResult",
    "composition",
    "export",
    "extraction",
    "guard",
    "intake",
    "patterns",
    "review",
    "run_pipeline",
    "validator",
]
