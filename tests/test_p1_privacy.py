"""P1 — privacy violations: consent, minimization, isolation, synthetic data."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import dispose_all, note

from progress_tracker.models import ConsentRecord
from progress_tracker.services import guard, intake, review, run_pipeline
from progress_tracker.states import RecordStatus

NOTE = ("He confused ser and estar when describing the weather. "
        "Gender agreement errors on three adjectives. "
        "Preterite vs imperfect was hard in the story.")


def test_minor_without_consent_produces_zero_outbound_calls(ctx):
    """FR-14 / C-04: the gate fails closed, BEFORE the first model call."""
    record = intake.register(ctx, note(NOTE, student="syn-minor-01", minor=True))
    before = len(ctx.gateway.sent_payloads)

    result = run_pipeline(ctx, record.record_id)

    assert result.status is RecordStatus.BLOCKED_CONSENT
    assert len(ctx.gateway.sent_payloads) == before, \
        "a consent-blocked record must not reach the gateway at all"


def test_consent_granted_then_run_proceeds(ctx):
    ctx.stores.consents.grant(ConsentRecord(
        student_ref="syn-minor-02", guardian_label="guardian-A"))
    record = intake.register(ctx, note(NOTE, student="syn-minor-02", minor=True))
    assert run_pipeline(ctx, record.record_id).ok


def test_consent_withdrawn_between_draft_and_approval_blocks_approval(ctx):
    """PR-6: consent is evaluated at the point of consequence, not only at the start."""
    ctx.stores.consents.grant(ConsentRecord(
        student_ref="syn-minor-03", guardian_label="guardian-B"))
    record = intake.register(ctx, note(NOTE, student="syn-minor-03", minor=True))
    assert run_pipeline(ctx, record.record_id).ok

    review.open_review(ctx, record.record_id)
    dispose_all(ctx, record.record_id)
    ctx.stores.consents.withdraw("syn-minor-03")

    with pytest.raises(guard.ConsentRequired):
        review.approve(ctx, record.record_id)


def test_expired_consent_does_not_count_as_consent(ctx):
    ctx.stores.consents.grant(ConsentRecord(
        student_ref="syn-minor-04", guardian_label="guardian-C",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    record = intake.register(ctx, note(NOTE, student="syn-minor-04", minor=True))
    assert run_pipeline(ctx, record.record_id).status is RecordStatus.BLOCKED_CONSENT


def test_withdrawal_never_deletes_the_consent_trail(ctx):
    ctx.stores.consents.grant(ConsentRecord(
        student_ref="syn-minor-05", guardian_label="guardian-D"))
    ctx.stores.consents.withdraw("syn-minor-05")
    current = ctx.stores.consents.current("syn-minor-05")
    assert current is not None and current.withdrawn_at is not None
    assert current.granted_at is not None, "who consented and when must survive"


def test_contact_details_never_leave_the_trust_boundary(ctx):
    """C-02: the golden test. A note with a name, an email and a phone number."""
    text = ("Student Jordan Fake emailed jordan.fake@example-mail.com about homework. "
            "ser and estar confusion throughout the message. "
            "Gender agreement errors on two adjectives. "
            "Call 555 010 9988 to reschedule.")
    ctx.aliases = {"Jordan Fake": "student-7"}
    record = intake.register(ctx, note(text, student="syn-contact-01"))
    run_pipeline(ctx, record.record_id)

    payload = str(ctx.gateway.sent_payloads)
    assert "jordan.fake@example-mail.com" not in payload
    assert "555 010 9988" not in payload
    assert "Jordan Fake" not in payload
    assert "student-7" in payload, "the alias is substituted, not just deleted"


def test_identifiers_are_not_mangled_by_redaction(ctx):
    """Regression: the phone pattern once rewrote UUIDs containing digit runs,
    which silently broke the citations that depend on them."""
    record = intake.register(ctx, note(NOTE))
    assert run_pipeline(ctx, record.record_id).ok
    findings = ctx.stores.candidates.findings(record.record_id)
    draft = ctx.stores.candidates.draft(record.record_id)
    known = {f.finding_id for f in findings} | {"tutor_level", "tutor_topics",
                                                "tutor_homework"}
    cited = {c for b in draft.body_blocks for c in b.cites}
    assert cited <= known, f"citation(s) corrupted in transit: {cited - known}"


def test_one_students_data_never_appears_in_anothers_request(ctx):
    """C-07: the context builder takes exactly one student reference."""
    first = intake.register(ctx, note("He confused ser and estar. "
                                      "Gender agreement errors on adjectives. "
                                      "PINEAPPLE_MARKER_A was discussed.",
                                      student="syn-iso-A", day=1))
    run_pipeline(ctx, first.record_id)
    boundary = len(ctx.gateway.sent_payloads)

    second = intake.register(ctx, note("Preterite vs imperfect confusion. "
                                       "Subjunctive avoided completely.",
                                       student="syn-iso-B", day=2))
    run_pipeline(ctx, second.record_id)

    later = str(ctx.gateway.sent_payloads[boundary:])
    assert "PINEAPPLE_MARKER_A" not in later
    assert "syn-iso-A" not in later


# ---------------------------------------------------------------- C-05 denylist

REAL_DATA_PATTERNS = {
    "consumer email domain": re.compile(
        r"@(gmail|yahoo|hotmail|outlook|icloud|proton)\.", re.I),
    "institutional email": re.compile(r"@[\w-]+\.(edu|org|gov)\b", re.I),
    "marketplace url": re.compile(r"(preply|italki|verbling)\.com", re.I),
}

#: Any phone-shaped string that does not use the reserved 555 exchange.
PHONE = re.compile(r"\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b")

SCANNED = [
    Path(__file__).resolve().parents[1] / "src" / "progress_tracker" / "demo_data.py",
    Path(__file__).resolve().parent,
]


def _scan(text: str) -> list[str]:
    hits = [name for name, pattern in REAL_DATA_PATTERNS.items() if pattern.search(text)]
    if any("555" not in m for m in PHONE.findall(text)):
        hits.append("non-reserved phone")
    return hits


def test_no_fixture_contains_anything_resembling_real_learner_data(ctx):
    """NFR-14 / C-05. Fixtures are invented; this check keeps them that way."""
    offenders: list[str] = []
    for target in SCANNED:
        files = [target] if target.is_file() else sorted(target.glob("*.py"))
        for path in files:
            # This file is excluded from its own scan: it deliberately contains
            # the violating strings used to prove the check can fail.
            if path.resolve() == Path(__file__).resolve():
                continue
            hits = _scan(path.read_text(encoding="utf-8"))
            offenders += [f"{path.name}: {hit}" for hit in hits]
    assert not offenders, f"possible real data in fixtures: {offenders}"


def test_the_denylist_check_actually_catches_a_violation():
    """A control that cannot fail is not a control."""
    assert _scan("contact me at someone@gmail.com") == ["consumer email domain"]
    assert _scan("book at https://preply.com/en/tutor/123") == ["marketplace url"]
    assert _scan("call 212 555 0199") == []          # reserved range is allowed
    assert _scan("call 212 884 0199") == ["non-reserved phone"]
