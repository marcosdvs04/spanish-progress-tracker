"""Component E — Composition Service (GenAI).

Drafts the level-adapted student-facing summary and 2-4 goals, each citing the
finding it rests on. The CEFR level is supplied, never inferred: the only block
permitted to mention it cites ``tutor_level`` and nothing else (FR-04).
"""

from __future__ import annotations

from typing import Optional

from ..context import AppContext
from ..gateway import ModelRequest
from ..models import AuditEvent, Goal, SummaryBlock, SummaryDraft
from ..states import RecordStatus, require

TEMPLATE_ID = "compose.summary"
TEMPLATE_VERSION = "v1"

ACCEPTS = {RecordStatus.PATTERNS_LINKED, RecordStatus.UNDER_REVIEW,
           RecordStatus.CORRECTED, RecordStatus.BLOCKED_SERVICE}


def run(ctx: AppContext, record_id: str, scope: Optional[str] = None,
        instructions: Optional[str] = None) -> SummaryDraft:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    require(record.status, ACCEPTS, "composition")

    findings = ctx.stores.candidates.findings(record_id)
    previous = ctx.stores.candidates.draft(record_id)

    payload = [{
        "finding_id": f.finding_id, "category": f.category, "pattern_key": f.pattern_key,
        "is_recurring": f.is_recurring, "occurrence_count": f.occurrence_count,
        "window_size": f.window_size, "trend": f.trend,
    } for f in findings]

    variables = {
        "level": record.tutor_level,
        "topics": record.topics,
        "homework": record.homework,
        "findings": payload,
    }
    if scope:
        variables["scope"] = scope
        variables["instructions"] = instructions or ""
        # Corrections the tutor already made are re-injected verbatim and are
        # re-checked byte-for-byte by the caller (PR-7 / FR-16).
        if previous is not None:
            keep = "goals" if scope == "summary" else "blocks"
            variables["preserve"] = previous.model_dump(mode="json")[keep]

    response = ctx.gateway.invoke(
        ModelRequest(task="compose", template_id=TEMPLATE_ID, version=TEMPLATE_VERSION,
                     variables=variables),
        record_id=record_id, aliases=ctx.aliases,
    )

    blocks = [SummaryBlock(**b) for b in response.content.get("blocks", [])]
    goals = [Goal(**g) for g in response.content.get("goals", [])]

    # A scoped revision replaces only the requested part (PR-7).
    if scope and previous is not None:
        if scope == "summary":
            goals = previous.goals
        else:
            blocks = previous.body_blocks

    draft = SummaryDraft(
        record_id=record_id,
        revision_no=record.revision_no,
        level_used=record.tutor_level,
        body_blocks=blocks,
        goals=goals,
        model_id=response.model_id,
        prompt_version=TEMPLATE_VERSION,
        review_status="draft",
    )
    ctx.stores.candidates.put(record_id, "draft", draft, draft.draft_id)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="E:composition", action="draft.composed",
        after={"blocks": len(blocks), "goals": len(goals), "scope": scope,
               "revision_no": draft.revision_no},
        model_id=response.model_id, prompt_version=TEMPLATE_VERSION,
        tokens_in=response.tokens_in, tokens_out=response.tokens_out,
    ))
    return draft
