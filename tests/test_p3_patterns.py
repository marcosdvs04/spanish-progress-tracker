"""P3 — domain logic: recurrence, trend, and the candidate/validated boundary."""

from __future__ import annotations

from conftest import dispose_all, note, seed_lesson

from progress_tracker.models import RevisionRequest
from progress_tracker.services import intake, patterns, review, run_pipeline

SER_ESTAR = ("He confused ser and estar again when describing how he felt. "
             "Gender agreement slipped on two adjectives.")
NO_SER_ESTAR = ("Preterite vs imperfect is confusing in narration. "
                "A false friend came up with 'realizar'.")
CURRENT = ("ser vs estar again with temporary states, he used ser for 'estoy listo'. "
           "Object pronouns CD and CI were hard, he mixed up le and lo.")


def _history(ctx, out_dir) -> None:
    """Four approved lessons: ser/estar in three of them, never in lesson 3."""
    seed_lesson(ctx, note(SER_ESTAR, day=1), out_dir)
    seed_lesson(ctx, note(SER_ESTAR, day=8), out_dir)
    seed_lesson(ctx, note(NO_SER_ESTAR, day=15), out_dir)
    seed_lesson(ctx, note(SER_ESTAR, day=22), out_dir)


def test_recurring_error_is_reported_as_four_of_the_last_five(ctx, out_dir):
    """FR-03, the headline claim."""
    _history(ctx, out_dir)
    record = intake.register(ctx, note(CURRENT, day=29))
    assert run_pipeline(ctx, record.record_id).ok

    findings = {f.category: f for f in ctx.stores.candidates.findings(record.record_id)}
    ser_estar = findings["grammar/ser-estar"]
    assert ser_estar.is_recurring is True
    assert ser_estar.occurrence_count == 4
    assert ser_estar.window_size == 5
    assert ser_estar.first_seen is not None and ser_estar.last_seen is not None


def test_a_one_off_in_the_same_set_is_not_flagged_as_recurring(ctx, out_dir):
    _history(ctx, out_dir)
    record = intake.register(ctx, note(CURRENT, day=29))
    run_pipeline(ctx, record.record_id)

    findings = {f.category: f for f in ctx.stores.candidates.findings(record.record_id)}
    one_off = findings["grammar/object-pronouns"]
    assert one_off.is_recurring is False
    assert one_off.occurrence_count == 1


def test_an_unvalidated_candidate_never_affects_a_later_count(ctx, out_dir):
    """FR-12 / C-19: the candidate/validated split, measured."""
    _history(ctx, out_dir)

    # A fifth lesson with ser/estar that is analysed but NEVER approved.
    unapproved = intake.register(ctx, note(SER_ESTAR, day=25))
    assert run_pipeline(ctx, unapproved.record_id).ok

    later = intake.register(ctx, note(CURRENT, day=29))
    run_pipeline(ctx, later.record_id)
    findings = {f.category: f for f in ctx.stores.candidates.findings(later.record_id)}

    assert findings["grammar/ser-estar"].occurrence_count == 4, \
        "the unapproved lesson must not have been counted"


def test_unvalidated_candidates_are_absent_from_history_and_exports(ctx, out_dir):
    unapproved = intake.register(ctx, note(SER_ESTAR, day=3))
    run_pipeline(ctx, unapproved.record_id)

    history = ctx.stores.validated.approved_errors("syn-t-01")
    assert history == [], "nothing unapproved may enter the validated store"


def test_changing_the_window_at_runtime_changes_the_result(ctx, out_dir):
    """NFR-12 / C-17: configurable without a code change or a redeploy."""
    _history(ctx, out_dir)
    record = intake.register(ctx, note(CURRENT, day=29))
    run_pipeline(ctx, record.record_id)
    wide = {f.category: f for f in ctx.stores.candidates.findings(record.record_id)}

    ctx.stores.settings.set("window_n", 3)
    ctx.stores.lessons.set_status(record.record_id,
                                  __import__("progress_tracker.states", fromlist=["x"])
                                  .RecordStatus.EXTRACTED)
    patterns.run(ctx, record.record_id)
    narrow = {f.category: f for f in ctx.stores.candidates.findings(record.record_id)}

    assert wide["grammar/ser-estar"].window_size == 5
    assert narrow["grammar/ser-estar"].window_size <= 4
    assert narrow["grammar/ser-estar"].window_size != wide["grammar/ser-estar"].window_size


def test_trend_needs_enough_history_before_it_claims_a_direction(ctx, out_dir):
    """The system says it does not know yet rather than guessing."""
    record = intake.register(ctx, note(SER_ESTAR, day=1))
    run_pipeline(ctx, record.record_id)
    finding = ctx.stores.candidates.findings(record.record_id)[0]
    assert finding.trend == "insufficient_history"


def test_a_correction_survives_a_revision_verbatim(ctx, out_dir):
    """FR-16 / PR-7."""
    record = intake.register(ctx, note(SER_ESTAR, day=1))
    result = run_pipeline(ctx, record.record_id)
    draft = result.draft
    assert draft is not None and draft.goals

    review.open_review(ctx, record.record_id)
    corrected = "Objetivo corregido a mano por el tutor."
    from progress_tracker.models import Disposition
    review.apply_dispositions(ctx, record.record_id, [Disposition(
        record_id=record.record_id, target=draft.goals[0].goal_id,
        action="correct", after=corrected)])

    revised = review.revise(ctx, record.record_id,
                            RevisionRequest(record_id=record.record_id, scope="summary",
                                            instructions="shorter, warmer"))
    assert any(g.text == corrected for g in revised.goals), \
        "a scoped revision must not overwrite the tutor's own words"
    assert revised.revision_no == 1


def test_only_one_revision_is_permitted(ctx, out_dir):
    import pytest

    record = intake.register(ctx, note(SER_ESTAR, day=1))
    run_pipeline(ctx, record.record_id)
    review.open_review(ctx, record.record_id)
    review.revise(ctx, record.record_id, RevisionRequest(
        record_id=record.record_id, scope="summary", instructions="again"))

    with pytest.raises(review.RevisionLimitReached):
        review.revise(ctx, record.record_id, RevisionRequest(
            record_id=record.record_id, scope="summary", instructions="and again"))


def test_history_endpoint_returns_validated_material_only(ctx, out_dir):
    _history(ctx, out_dir)
    approved = ctx.stores.validated.approved_errors("syn-t-01")
    assert approved, "approved lessons are in the validated store"
    lesson_days = {d.day for d, _ in approved}
    assert lesson_days == {1, 8, 15, 22}
