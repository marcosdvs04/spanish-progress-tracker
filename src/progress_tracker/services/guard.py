"""Component B — Consent & Access Guard (Gate 1).

Fails closed. For a student flagged as a minor, a run is blocked *before the
first model call* unless an active guardian consent exists, and consent is
re-evaluated at approval because a withdrawal between the two must stop the
summary (FR-14 / PR-6 / C-04).
"""

from __future__ import annotations

from ..context import AppContext
from ..models import AuditEvent, GateDecision
from ..states import RecordStatus


def evaluate(ctx: AppContext, record_id: str, operation: str = "generate") -> GateDecision:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        return GateDecision(permit=False, reason="unknown record")

    if not record.is_minor:
        decision = GateDecision(permit=True)
    else:
        consent = ctx.stores.consents.current(record.student_ref)
        if consent is None:
            decision = GateDecision(
                permit=False, reason="no guardian consent on file",
                blocked_status=RecordStatus.BLOCKED_CONSENT)
        elif not consent.covers(operation):
            decision = GateDecision(
                permit=False,
                reason=f"guardian consent is {consent.state.value} or does not cover {operation}",
                blocked_status=RecordStatus.BLOCKED_CONSENT)
        else:
            decision = GateDecision(permit=True)

    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="B:guard", action=f"gate1.{operation}",
        outcome="ok" if decision.permit else "blocked", reason=decision.reason,
    ))
    if not decision.permit and decision.blocked_status is not None:
        ctx.stores.lessons.set_status(record_id, decision.blocked_status)
    return decision


class ConsentRequired(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def require(ctx: AppContext, record_id: str, operation: str = "generate") -> None:
    decision = evaluate(ctx, record_id, operation)
    if not decision.permit:
        raise ConsentRequired(decision.reason or "blocked at Gate 1")
