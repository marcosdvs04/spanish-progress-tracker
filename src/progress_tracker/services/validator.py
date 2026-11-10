"""Component F — Grounding & Readability Validator (Gate 2).

Deterministic. A model must not grade its own output, so this is a separate
component with no model access at all.

* **Grounding (PR-3 / C-11).** Every block and goal must cite an item whose
  source reference resolves in the immutable note. An uncited or unresolvable
  statement is REMOVED and the removal is logged with the text that was removed.
* **Level assertion (FR-04).** A block of kind ``level`` may cite ``tutor_level``
  and nothing else. Citing anything else is a HARD FAILURE, not a silent removal,
  because it means the model attempted to assess the student.
* **Floor (FR-11).** Above 40% of blocks removed, or fewer than two grounded
  errors surviving, the run halts in Blocked-InsufficientEvidence with a list of
  what the notes would need to contain. It never fabricates to fill the gap.
* **Readability (PR-2 / C-12).** Mean sentence length and Spanish-token ratio
  are measured against the band for the tutor-set level.
"""

from __future__ import annotations

from .. import config
from ..context import AppContext
from ..language import mean_sentence_length, spanish_ratio
from ..models import AuditEvent, Readability, SummaryDraft, ValidationReport
from ..states import RecordStatus

LEVEL_CITE = "tutor_level"
#: Citations that point at the tutor's own submitted fields rather than at an
#: extracted item. A block that only restates what the tutor typed (the topics
#: list, the homework) is grounded in the submission itself.
TUTOR_CITES = {"tutor_level", "tutor_topics", "tutor_homework"}


class InsufficientEvidence(Exception):
    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("; ".join(missing))


class AuthorityViolation(Exception):
    """The model attempted to assess the CEFR level. Must be visible, never silent."""


def student_facing_text(draft: SummaryDraft) -> str:
    parts = [b.text for b in draft.body_blocks]
    parts += [f"{g.text} {g.practice}" for g in draft.goals]
    return " ".join(parts)


def check(ctx: AppContext, record_id: str, draft: SummaryDraft) -> ValidationReport:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)

    findings = {f.finding_id: f for f in ctx.stores.candidates.findings(record_id)}
    errors = {e.item_id: e for e in ctx.stores.candidates.errors(record_id)}
    note = record.note_text

    def citation_resolves(cite: str) -> bool:
        if cite in TUTOR_CITES:
            return True
        finding = findings.get(cite)
        if finding is not None:
            return any(r.resolves_in(note) for r in finding.supporting_refs)
        error = errors.get(cite)
        if error is not None:
            return error.source_ref.resolves_in(note)
        return False

    removed: list[dict] = []
    hard_failures: list[str] = []

    kept_blocks = []
    for block in draft.body_blocks:
        if block.kind == "level":
            if set(block.cites) - {LEVEL_CITE} or not block.cites:
                hard_failures.append(
                    f"level statement cites {block.cites!r}; only {LEVEL_CITE!r} is permitted"
                )
            kept_blocks.append(block)
            continue
        if not block.cites or not any(citation_resolves(c) for c in block.cites):
            removed.append({"kind": "block", "id": block.block_id, "text": block.text,
                            "why": "no citation resolves into the lesson note"})
            continue
        kept_blocks.append(block)

    kept_goals = []
    for goal in draft.goals:
        if not goal.cites or not any(citation_resolves(c) for c in goal.cites):
            removed.append({"kind": "goal", "id": goal.goal_id, "text": goal.text,
                            "why": "no citation resolves into the lesson note"})
            continue
        kept_goals.append(goal)

    if hard_failures:
        ctx.stores.audit.append(AuditEvent(
            record_id=record_id, actor="F:validator", action="gate2.authority_violation",
            outcome="error", reason="; ".join(hard_failures),
        ))
        raise AuthorityViolation("; ".join(hard_failures))

    draft.body_blocks = kept_blocks
    draft.goals = kept_goals

    text = student_facing_text(draft)
    band = (ctx.stores.settings.get("level_bands") or config.LEVEL_BANDS)[draft.level_used]
    readability = Readability(
        mean_sentence_len=round(mean_sentence_length(text), 2),
        target_lang_ratio=round(spanish_ratio(text), 3),
        passed=(mean_sentence_length(text) <= band["max_sentence"]
                and spanish_ratio(text) >= band["min_es_ratio"]),
    )
    draft.readability = readability

    total_blocks = len(draft.body_blocks) + len(removed)
    removed_fraction = (len(removed) / total_blocks) if total_blocks else 0.0
    grounded_errors = sum(1 for e in errors.values() if e.source_ref.resolves_in(note))

    missing: list[str] = []
    if removed_fraction > config.MAX_REMOVED_FRACTION:
        missing.append(
            f"{int(removed_fraction * 100)}% of the draft was not supported by the notes"
        )
    if grounded_errors < config.MIN_GROUNDED_ERRORS:
        missing.append(
            "the note needs at least two specific errors: what the student said or wrote, "
            "and what was wrong with it"
        )

    report = ValidationReport(
        passed=not missing, removed=removed, readability=readability,
        missing=missing, hard_failures=[],
    )

    ctx.stores.candidates.put(record_id, "draft", draft, draft.draft_id)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="F:validator", action="gate2.checked",
        after={"removed": len(removed), "readability": readability.model_dump(),
               "grounded_errors": grounded_errors},
        outcome="ok" if report.passed else "blocked",
        reason="; ".join(missing) or None,
    ))

    if not report.passed:
        ctx.stores.lessons.set_status(record_id, RecordStatus.BLOCKED_INSUFFICIENT)
        raise InsufficientEvidence(missing)

    ctx.stores.lessons.set_status(record_id, RecordStatus.DRAFT_READY)
    return report
