"""Component G — Review Workbench.

The only component that accepts human authority. Exactly four reviewer actions
exist (FR-13), and approval is refused while any candidate is still open, so
"approved" always means the tutor saw every candidate rather than clicked past
them (invariant I-3).

A ``question`` disposition deliberately still blocks approval: an open question
is not a decision.
"""

from __future__ import annotations

from typing import Iterable, Optional

from ..context import AppContext
from ..models import AuditEvent, Disposition, RevisionRequest, SummaryDraft, utcnow
from ..states import RecordStatus, require
from . import guard

OPEN_STATUSES = {"candidate", "questioned"}
MAX_REVISIONS = 1


class UndispositionedItems(Exception):
    def __init__(self, item_ids: list[str]) -> None:
        self.item_ids = item_ids
        super().__init__(f"{len(item_ids)} item(s) still need a decision")


class RevisionLimitReached(Exception):
    pass


def open_review(ctx: AppContext, record_id: str) -> SummaryDraft:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    require(record.status,
            {RecordStatus.DRAFT_READY, RecordStatus.UNDER_REVIEW, RecordStatus.CORRECTED},
            "review")
    draft = ctx.stores.candidates.draft(record_id)
    if draft is None:
        raise LookupError("no draft for this record")
    if record.status is RecordStatus.DRAFT_READY:
        ctx.stores.lessons.set_status(record_id, RecordStatus.UNDER_REVIEW)
        ctx.stores.audit.append(AuditEvent(
            record_id=record_id, actor="tutor", action="review.opened"))
    return draft


def _open_items(ctx: AppContext, record_id: str) -> list[str]:
    open_ids = set(ctx.stores.candidates.undispositioned(record_id))
    for item in ctx.stores.candidates.errors(record_id):
        if item.status in OPEN_STATUSES:
            open_ids.add(item.item_id)
    return sorted(open_ids)


def apply_dispositions(ctx: AppContext, record_id: str,
                       dispositions: Iterable[Disposition]) -> list[str]:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    require(record.status, {RecordStatus.UNDER_REVIEW, RecordStatus.CORRECTED},
            "disposition")

    draft = ctx.stores.candidates.draft(record_id)
    status_for = {"validate": "validated", "correct": "corrected",
                  "reject": "rejected", "question": "questioned"}

    for d in dispositions:
        ctx.stores.candidates.set_item_status(d.target, status_for[d.action])

        # A correction to the student-facing text is applied to the draft itself,
        # and the tutor's wording is what the export will carry (FR-09).
        if draft is not None and d.action == "correct" and d.after:
            for block in draft.body_blocks:
                if block.block_id == d.target:
                    d.before = d.before or block.text
                    block.text = d.after
            for goal in draft.goals:
                if goal.goal_id == d.target:
                    d.before = d.before or goal.text
                    goal.text = d.after

        ctx.stores.audit.append(AuditEvent(
            record_id=record_id, actor=d.reviewer, action=f"review.{d.action}",
            target=d.target,
            before={"text": d.before} if d.before else None,
            after={"text": d.after} if d.after else None,
            reason=d.note,
        ))

    if draft is not None:
        ctx.stores.candidates.put(record_id, "draft", draft, draft.draft_id)

    still_open = _open_items(ctx, record_id)
    if not still_open:
        ctx.stores.lessons.set_status(record_id, RecordStatus.CORRECTED)
    return still_open


def revise(ctx: AppContext, record_id: str, request: RevisionRequest) -> SummaryDraft:
    """One bounded revision cycle (PR-7 / FR-16).

    The cap exists so that "just regenerate it again" cannot quietly replace
    tutor judgement with model iteration.
    """
    from . import composition  # local import keeps the component graph acyclic

    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    require(record.status, {RecordStatus.UNDER_REVIEW, RecordStatus.CORRECTED}, "revision")
    if record.revision_no >= MAX_REVISIONS:
        raise RevisionLimitReached(
            f"one revision per record; this record is already at revision {record.revision_no}"
        )

    ctx.stores.lessons.bump_revision(record_id)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="tutor", action="review.revision_requested",
        after={"scope": request.scope, "instructions": request.instructions},
    ))
    return composition.run(ctx, record_id, scope=request.scope,
                           instructions=request.instructions)


def approve(ctx: AppContext, record_id: str, reviewer: str = "tutor") -> SummaryDraft:
    """Gate 3. The only transition that creates authority."""
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    # UnderReview is accepted here so that an early approval attempt fails with
    # the real reason - open items - rather than a state technicality. It can
    # never succeed from UnderReview, because that state means at least one
    # candidate is still open (invariant I-3).
    require(record.status, {RecordStatus.CORRECTED, RecordStatus.UNDER_REVIEW}, "approval")

    still_open = _open_items(ctx, record_id)
    if still_open:
        ctx.stores.audit.append(AuditEvent(
            record_id=record_id, actor=reviewer, action="gate3.refused",
            outcome="blocked", reason=f"{len(still_open)} undispositioned item(s)"))
        raise UndispositionedItems(still_open)

    # Consent is re-checked here, not only at the start: a withdrawal between the
    # draft and the approval must stop the summary (PR-6).
    guard.require(ctx, record_id, "generate")

    draft = ctx.stores.candidates.draft(record_id)
    if draft is None:
        raise LookupError("no draft for this record")
    draft.review_status = "tutor_approved"
    ctx.stores.candidates.put(record_id, "draft", draft, draft.draft_id)
    ctx.stores.lessons.set_status(record_id, RecordStatus.APPROVED)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor=reviewer, action="gate3.approved",
        after={"approved_at": utcnow().isoformat(), "draft_id": draft.draft_id},
    ))
    return draft


def abandon(ctx: AppContext, record_id: str, reason: Optional[str] = None) -> None:
    """Candidates are retained in D3 and marked, never promoted to D2."""
    ctx.stores.lessons.set_status(record_id, RecordStatus.ABANDONED)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="tutor", action="review.abandoned", reason=reason))
