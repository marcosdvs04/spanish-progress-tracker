"""Component C — Extraction Service (GenAI).

Turns note text into categorized candidate errors, each carrying a source span
that resolves into the immutable note. Proposes nothing else.

Two rules are enforced here rather than trusted to the model (PR-4):

* a category outside the active taxonomy is rejected, not stored;
* a candidate whose quoted text does not match the note at its offset is
  discarded before storage, because an unresolvable span is an ungrounded claim.
"""

from __future__ import annotations

from typing import Any

from ..context import AppContext
from ..gateway import ModelRequest
from ..models import AuditEvent, CandidateError, SourceRef
from ..states import RecordStatus, require

TEMPLATE_ID = "extract.errors"
TEMPLATE_VERSION = "v1"

ACCEPTS = {RecordStatus.REGISTERED, RecordStatus.BLOCKED_SERVICE}


def run(ctx: AppContext, record_id: str) -> list[CandidateError]:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    require(record.status, ACCEPTS, "extraction")

    taxonomy = ctx.stores.settings.get("taxonomy") or {}
    response = ctx.gateway.invoke(
        ModelRequest(
            task="extract",
            template_id=TEMPLATE_ID,
            version=TEMPLATE_VERSION,
            variables={"note_text": record.note_text, "taxonomy": taxonomy},
        ),
        record_id=record_id,
        aliases=ctx.aliases,
    )

    accepted: list[CandidateError] = []
    rejected: list[dict[str, Any]] = []

    for raw in response.content.get("errors", []):
        category = raw.get("category")
        if category not in taxonomy:
            rejected.append({"category": category, "why": "category not in active taxonomy"})
            continue

        refs: list[SourceRef] = []
        for ref in raw.get("source_refs", []):
            try:
                candidate_ref = SourceRef(
                    record_id=record_id,
                    lesson_date=record.lesson_date,
                    span_start=int(ref["span_start"]),
                    span_end=int(ref["span_end"]),
                    quoted_text=ref["quoted_text"],
                )
            except Exception as exc:  # malformed reference from the model
                rejected.append({"category": category, "why": f"malformed span: {exc}"})
                continue
            if not candidate_ref.resolves_in(record.note_text):
                rejected.append({"category": category, "why": "span does not resolve in the note"})
                continue
            refs.append(candidate_ref)

        if not refs:
            rejected.append({"category": category, "why": "no resolvable source reference"})
            continue

        accepted.append(CandidateError(
            record_id=record_id,
            error_text=raw.get("error_text") or taxonomy[category],
            category=category,
            severity=raw.get("severity", "medium"),
            source_ref=refs[0],
        ))

    ctx.stores.candidates.put_many(record_id, "error", accepted)
    ctx.stores.lessons.set_status(record_id, RecordStatus.EXTRACTED)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="C:extraction", action="errors.extracted",
        after={"accepted": len(accepted), "rejected": rejected},
        model_id=response.model_id, prompt_version=TEMPLATE_VERSION,
        tokens_in=response.tokens_in, tokens_out=response.tokens_out,
    ))
    return accepted
