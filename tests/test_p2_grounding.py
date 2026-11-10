"""P2 — grounding and traceability: the difference between an assistant and a
plausible-sounding liability."""

from __future__ import annotations

import pytest
from conftest import dispose_all, note

from progress_tracker.models import CandidateError, SourceRef, SummaryBlock
from progress_tracker.services import export as export_svc
from progress_tracker.services import extraction, intake, review, run_pipeline
from progress_tracker.services import validator as validator_svc
from progress_tracker.states import RecordStatus

FIVE_ERRORS = (
    "He confused ser and estar when describing how he felt. "
    "Gender agreement slipped twice on adjectives after the noun. "
    "Preterite vs imperfect is still unclear in narration. "
    "Prepositions after verbs: he said 'pienso de' instead of 'pienso en'. "
    "Object pronouns CD and CI were mixed up throughout."
)


def test_five_described_errors_are_extracted_with_resolving_spans(ctx):
    """FR-02 / FR-08."""
    record = intake.register(ctx, note(FIVE_ERRORS))
    errors = extraction.run(ctx, record.record_id)

    categories = {e.category for e in errors}
    assert categories == {
        "grammar/ser-estar", "grammar/gender-agreement",
        "grammar/preterite-imperfect", "grammar/prepositions",
        "grammar/object-pronouns",
    }
    for error in errors:
        assert error.source_ref.resolves_in(record.note_text)
        assert error.source_ref.quoted_text in record.note_text


def test_no_error_is_invented_that_is_not_in_the_notes(ctx):
    """The fabrication test: a note about one thing yields only that thing."""
    text = ("Spoke about his weekend for ten minutes. "
            "Gender agreement errors on the adjectives, twice. "
            "Otherwise fluent and confident today.")
    record = intake.register(ctx, note(text))
    errors = extraction.run(ctx, record.record_id)
    assert {e.category for e in errors} == {"grammar/gender-agreement"}


def test_an_absence_of_an_error_is_not_an_error(ctx):
    """'No ser and estar errors today' must not become a ser/estar error.

    Without this the recurrence count is inflated by the tutor saying something
    went WELL - the exact distortion PR-1 exists to avoid.
    """
    text = ("Past tenses introduced, preterite vs imperfect is confusing for him. "
            "A false friend came up with 'realizar'. "
            "No ser and estar errors today, which is progress.")
    record = intake.register(ctx, note(text))
    categories = {e.category for e in extraction.run(ctx, record.record_id)}
    assert "grammar/ser-estar" not in categories
    assert "grammar/preterite-imperfect" in categories


def test_a_candidate_cannot_be_built_without_a_source_reference(ctx):
    """C-08 is a schema decision, not a runtime check."""
    with pytest.raises(Exception):
        CandidateError(record_id="r", error_text="x", category="grammar/ser-estar")  # type: ignore[call-arg]


def test_a_span_that_does_not_resolve_is_discarded_before_storage(ctx):
    record = intake.register(ctx, note(FIVE_ERRORS))
    ref = SourceRef(record_id=record.record_id, lesson_date=record.lesson_date,
                    span_start=0, span_end=10, quoted_text="NOT IN THE NOTE")
    assert not ref.resolves_in(record.note_text)


def test_an_ungrounded_statement_is_removed_and_logged(ctx):
    """PR-3: removal, with the removed text recorded."""
    record = intake.register(ctx, note(FIVE_ERRORS))
    result = run_pipeline(ctx, record.record_id)
    draft = result.draft
    assert draft is not None

    draft.body_blocks.append(SummaryBlock(
        kind="pattern", text="Your accent has become almost native.", cites=[]))
    report = validator_svc.check(ctx, record.record_id, draft)

    removed_texts = [r["text"] for r in report.removed]
    assert "Your accent has become almost native." in removed_texts
    assert all("native" not in b.text for b in draft.body_blocks)


def test_a_sparse_note_halts_instead_of_producing_content(ctx):
    """FR-11 / C-11: refuse rather than fabricate."""
    record = intake.register(ctx, note("Good lesson.", topics=[], homework=None))
    result = run_pipeline(ctx, record.record_id)

    assert result.status is RecordStatus.BLOCKED_INSUFFICIENT
    assert result.missing, "the refusal must say what the note would need"
    assert "two specific errors" in " ".join(result.missing)


def test_audit_is_append_only_and_replays_a_whole_run(ctx, out_dir):
    """C-09 / NFR-15."""
    from sqlalchemy import delete, update

    from progress_tracker.store import audit as audit_table

    record = intake.register(ctx, note(FIVE_ERRORS))
    run_pipeline(ctx, record.record_id)
    review.open_review(ctx, record.record_id)
    dispose_all(ctx, record.record_id)
    review.approve(ctx, record.record_id)
    export_svc.export(ctx, record.record_id, "txt", out_dir=out_dir)

    assert not hasattr(ctx.stores.audit, "update")
    assert not hasattr(ctx.stores.audit, "delete")

    with pytest.raises(Exception):
        with ctx.stores.engine.begin() as conn:
            conn.execute(update(audit_table).values(outcome="ok"))
    with pytest.raises(Exception):
        with ctx.stores.engine.begin() as conn:
            conn.execute(delete(audit_table))

    actions = [e["action"] for e in ctx.stores.audit.for_record(record.record_id)]
    for expected in ("lesson.registered", "gate1.generate", "model.extract",
                     "errors.extracted", "patterns.computed", "model.compose",
                     "draft.composed", "gate2.checked", "gate3.approved",
                     "export.written"):
        assert expected in actions, f"{expected} missing from the audit replay"


def test_the_lesson_note_is_immutable_after_registration(ctx):
    from sqlalchemy import update

    from progress_tracker.store import lessons as lessons_table

    record = intake.register(ctx, note(FIVE_ERRORS))
    with pytest.raises(Exception):
        with ctx.stores.engine.begin() as conn:
            conn.execute(update(lessons_table)
                         .where(lessons_table.c.record_id == record.record_id)
                         .values(note_text="rewritten"))


def test_every_exported_statement_resolves_to_a_quote(ctx, out_dir):
    record = intake.register(ctx, note(FIVE_ERRORS))
    run_pipeline(ctx, record.record_id)
    review.open_review(ctx, record.record_id)
    dispose_all(ctx, record.record_id)
    review.approve(ctx, record.record_id)
    artifact = export_svc.export(ctx, record.record_id, "txt", out_dir=out_dir)

    for entry in artifact.source_appendix:
        assert entry.quoted_text in record.note_text


def test_a_duplicate_submission_is_refused(ctx):
    """Idempotency protects the recurrence count from double counting."""
    submission = note(FIVE_ERRORS)
    intake.register(ctx, submission)
    with pytest.raises(intake.DuplicateLesson):
        intake.register(ctx, submission)
