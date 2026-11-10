"""Run orchestration: Gate 1 -> C -> D -> E -> Gate 2.

Each stage commits its own state, which is what makes a failed run resumable
rather than lost (C-14), and what would let the GenAI stages move behind a job
queue at scale without redrawing the architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..context import AppContext
from ..gateway import ProviderError
from ..models import AuditEvent, SummaryDraft, ValidationReport
from ..states import RecordStatus
from . import composition, extraction, guard, patterns, validator


@dataclass
class PipelineResult:
    record_id: str
    status: RecordStatus
    draft: Optional[SummaryDraft] = None
    report: Optional[ValidationReport] = None
    blocked_reason: Optional[str] = None
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is RecordStatus.DRAFT_READY


def run_pipeline(ctx: AppContext, record_id: str) -> PipelineResult:
    try:
        guard.require(ctx, record_id, "generate")
    except guard.ConsentRequired as exc:
        return PipelineResult(record_id, RecordStatus.BLOCKED_CONSENT,
                              blocked_reason=str(exc))

    try:
        extraction.run(ctx, record_id)
        patterns.run(ctx, record_id)
        draft = composition.run(ctx, record_id)
    except ProviderError as exc:
        ctx.stores.lessons.set_status(record_id, RecordStatus.BLOCKED_SERVICE)
        ctx.stores.audit.append(AuditEvent(
            record_id=record_id, actor="orchestrator", action="run.blocked",
            outcome="error", reason=f"{type(exc).__name__}: {exc}"))
        return PipelineResult(record_id, RecordStatus.BLOCKED_SERVICE,
                              blocked_reason=str(exc))

    try:
        report = validator.check(ctx, record_id, draft)
    except validator.InsufficientEvidence as exc:
        return PipelineResult(record_id, RecordStatus.BLOCKED_INSUFFICIENT,
                              blocked_reason="insufficient evidence", missing=exc.missing)
    except validator.AuthorityViolation as exc:
        ctx.stores.lessons.set_status(record_id, RecordStatus.BLOCKED_INSUFFICIENT)
        return PipelineResult(record_id, RecordStatus.BLOCKED_INSUFFICIENT,
                              blocked_reason=f"authority violation: {exc}")

    draft = ctx.stores.candidates.draft(record_id) or draft
    return PipelineResult(record_id, RecordStatus.DRAFT_READY, draft=draft, report=report)
