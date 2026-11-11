"""P1 — the review screen is the only surface on which tutor authority is exercised.

If an open candidate has no control on that screen, the tutor cannot decide it, and
C-19 ("approval is refused while candidates remain open") turns from a safeguard into
a deadlock: approval becomes unreachable for every record. That is an authority
failure, not a cosmetic one, so it is validated at P1.

This was a real defect. Recurrence findings were rendered inside the error card as
read-only text, with disposition buttons only on the error itself. Three errors were
decidable; the three findings derived from them were not, and "Approve and export"
could never succeed from the browser. The CLI was unaffected because it dispositions
the open-item list directly, which is exactly why the gap survived the demo path.
"""

from __future__ import annotations

import re

import pytest
from conftest import note
from fastapi.testclient import TestClient

from progress_tracker import api
from progress_tracker.services import intake, review, run_pipeline

NOTE = ("He confused ser and estar again when describing how he felt. "
        "Gender agreement slipped twice: 'la problema' and 'el persona'. "
        "Prepositions after verbs were hard: 'pienso de' instead of 'pienso en'.")

ITEM_ID = re.compile(r'name="item_id"\s+value="([^"]+)"')


def candidate_controls(html: str) -> set[str]:
    """The item_ids the Candidates section of the screen offers a decision for.

    Scoped deliberately: the draft and goal sections carry "correct" forms, which are
    edits rather than dispositions and do not close an open candidate.
    """
    section = html.split("<h2>Candidates", 1)[1].split("<h2>Draft the student", 1)[0]
    return set(ITEM_ID.findall(section))


@pytest.fixture()
def client(ctx, monkeypatch) -> TestClient:
    monkeypatch.setattr(api, "ctx", ctx)
    return TestClient(api.app)


def _record_under_review(ctx) -> str:
    record = intake.register(ctx, note(NOTE))
    result = run_pipeline(ctx, record.record_id)
    assert result.ok, f"pipeline blocked: {result.status} {result.missing}"
    review.open_review(ctx, record.record_id)
    return record.record_id


def test_every_open_candidate_has_a_control_on_the_review_screen(ctx, client):
    """C-19: the set of open items must be a subset of what the screen can decide."""
    record_id = _record_under_review(ctx)
    page = client.get(f"/ui/review/{record_id}")
    assert page.status_code == 200

    offered = candidate_controls(page.text)
    open_items = set(review._open_items(ctx, record_id))  # noqa: SLF001

    assert open_items, "fixture produced no candidates; the test would pass vacuously"
    unreachable = open_items - offered
    assert not unreachable, (
        f"{len(unreachable)} open candidate(s) have no control on the review screen "
        f"and can never be dispositioned: {sorted(unreachable)}"
    )


def test_findings_are_decided_separately_from_the_errors_they_derive_from(ctx, client):
    """A recurrence claim is its own assertion: the tutor may accept the error and
    reject the pattern. Bundling both into one click would record a decision the
    tutor never made."""
    record_id = _record_under_review(ctx)
    errors = ctx.stores.candidates.errors(record_id)
    findings = ctx.stores.candidates.findings(record_id)
    assert errors and findings

    offered = candidate_controls(client.get(f"/ui/review/{record_id}").text)
    assert {e.item_id for e in errors} <= offered
    assert {f.finding_id for f in findings} <= offered

    # Deciding every error leaves the findings open, by design.
    for e in errors:
        client.post(f"/ui/review/{record_id}/disposition",
                    data={"item_id": e.item_id, "action": "validate"},
                    follow_redirects=False)
    still_open = set(review._open_items(ctx, record_id))  # noqa: SLF001
    assert still_open == {f.finding_id for f in findings}


def test_the_browser_flow_can_reach_approval(ctx, client):
    """End to end through HTTP only: refused first, then granted once every control
    the screen offers has been used. This is the path demonstrated to stakeholders."""
    record_id = _record_under_review(ctx)

    refused = client.post(f"/ui/review/{record_id}/approve", follow_redirects=False)
    assert refused.status_code == 303
    assert "open_items" in refused.headers["location"]

    for item_id in candidate_controls(client.get(f"/ui/review/{record_id}").text):
        client.post(f"/ui/review/{record_id}/disposition",
                    data={"item_id": item_id, "action": "validate"},
                    follow_redirects=False)

    assert not review._open_items(ctx, record_id)  # noqa: SLF001
    granted = client.post(f"/ui/review/{record_id}/approve", follow_redirects=False)
    assert granted.status_code == 303
    assert "open_items" not in granted.headers["location"]
