"""P1 — authority violations.

These are the failures that invalidate the solution however well everything else
works, so they are validated before any stakeholder demonstration (§9.2).
"""

from __future__ import annotations

import pytest
from conftest import dispose_all, note

from progress_tracker.models import Disposition, SummaryBlock
from progress_tracker.services import export as export_svc
from progress_tracker.services import intake, review, run_pipeline
from progress_tracker.services import validator as validator_svc
from progress_tracker.states import RecordStatus

NOTE = ("He confused ser and estar again when describing feelings. "
        "Gender agreement slipped on two adjectives. "
        "Prepositions after verbs were hard: 'pienso de' instead of 'pienso en'.")


def test_export_before_approval_is_refused(ctx, out_dir):
    """FR-07 / C-13: a record that has not passed Gate 3 has no export path."""
    record = intake.register(ctx, note(NOTE))
    result = run_pipeline(ctx, record.record_id)
    assert result.status is RecordStatus.DRAFT_READY

    with pytest.raises(export_svc.NotApproved):
        export_svc.export(ctx, record.record_id, "txt", out_dir=out_dir)

    # ...and still refused once the review is open but not approved.
    review.open_review(ctx, record.record_id)
    with pytest.raises(export_svc.NotApproved):
        export_svc.export(ctx, record.record_id, "txt", out_dir=out_dir)


def test_approval_refused_while_any_item_is_open(ctx):
    """FR-13 / invariant I-3: approval must mean review, not clicking past."""
    record = intake.register(ctx, note(NOTE))
    run_pipeline(ctx, record.record_id)
    review.open_review(ctx, record.record_id)

    with pytest.raises(review.UndispositionedItems) as excinfo:
        review.approve(ctx, record.record_id)
    assert excinfo.value.item_ids, "the refusal must name the items still open"


def test_a_raised_question_still_blocks_approval(ctx):
    """An open question is not a decision."""
    record = intake.register(ctx, note(NOTE))
    run_pipeline(ctx, record.record_id)
    review.open_review(ctx, record.record_id)
    dispose_all(ctx, record.record_id, action="question")

    with pytest.raises(review.UndispositionedItems):
        review.approve(ctx, record.record_id)


def test_model_asserted_cefr_level_hard_fails(ctx):
    """FR-04: an attempted assessment must be VISIBLE, never silently stripped."""
    record = intake.register(ctx, note(NOTE))
    run_pipeline(ctx, record.record_id)
    draft = ctx.stores.candidates.draft(record.record_id)
    assert draft is not None

    # Simulate a model that decided the student's level for itself.
    draft.body_blocks = [
        SummaryBlock(kind="level", text="You have now reached B2.", cites=["some_finding"])
    ] + [b for b in draft.body_blocks if b.kind != "level"]

    with pytest.raises(validator_svc.AuthorityViolation):
        validator_svc.check(ctx, record.record_id, draft)

    events = [e for e in ctx.stores.audit.for_record(record.record_id)
              if e["action"] == "gate2.authority_violation"]
    assert events, "the violation must be recorded, not just raised"


def test_tutor_correction_survives_into_the_export(ctx, out_dir):
    """FR-09: the tutor's wording is what the student receives."""
    record = intake.register(ctx, note(NOTE))
    result = run_pipeline(ctx, record.record_id)
    draft = result.draft
    assert draft is not None and draft.goals

    review.open_review(ctx, record.record_id)
    corrected = "Objetivo escrito por el tutor, no por la maquina."
    review.apply_dispositions(ctx, record.record_id, [Disposition(
        record_id=record.record_id, target=draft.goals[0].goal_id,
        action="correct", after=corrected)])
    dispose_all(ctx, record.record_id)
    review.approve(ctx, record.record_id)

    artifact = export_svc.export(ctx, record.record_id, "txt", out_dir=out_dir)
    body = open(artifact.path, encoding="utf-8").read()
    assert corrected in body

    before_after = [e for e in ctx.stores.audit.for_record(record.record_id)
                    if e["action"] == "review.correct"]
    assert before_after, "the correction must be recorded with its before/after"


def test_artifact_carries_status_stamp_and_source_appendix(ctx, out_dir):
    """FR-15 / C-10."""
    record = intake.register(ctx, note(NOTE))
    run_pipeline(ctx, record.record_id)
    review.open_review(ctx, record.record_id)
    dispose_all(ctx, record.record_id)
    review.approve(ctx, record.record_id)

    for fmt in ("txt", "pdf"):
        artifact = export_svc.export(ctx, record.record_id, fmt, out_dir=out_dir)
        assert artifact.status_stamp == "Tutor-approved"
        assert artifact.source_appendix, "every export carries its sources"
        assert artifact.content_hash

    body = open(artifact.path.replace(".pdf", ".txt"), encoding="utf-8").read()
    assert "Tutor-approved" in body and "SOURCES" in body


def test_draft_is_stamped_as_unreviewed_before_approval(ctx):
    record = intake.register(ctx, note(NOTE))
    result = run_pipeline(ctx, record.record_id)
    assert result.draft is not None
    assert result.draft.review_status == "draft"
