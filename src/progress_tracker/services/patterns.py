"""Component D — Pattern & History Service.

Deterministic: no model call. Recurrence is an exact categorical count over the
student's APPROVED history, which is what makes a recurrence claim reproducible,
countable and arguable — and therefore trustworthy enough to change a lesson plan.

PR-1, restated:

    is_recurring     = occurrence_count >= threshold                 (default 3)
    occurrence_count = distinct APPROVED lessons in the window containing
                       this pattern_key, + 1 if the current candidate set has it
    trend            = occurrence rate, older vs recent half, outside a +/-0.2 band

Lessons are counted, not mentions. Only approved lessons enter the window, so an
unvalidated candidate can never influence a later recurrence claim (FR-12).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .. import config
from ..context import AppContext
from ..models import AuditEvent, PatternFinding
from ..states import RecordStatus, require

RULE_VERSION = "PR-1/v1"
ACCEPTS = {RecordStatus.EXTRACTED, RecordStatus.BLOCKED_SERVICE}


def _trend(dates_in_window: list[date], hit_dates: set[date], band: float) -> str:
    """Compare the occurrence rate in the older and recent halves of the window."""
    if len(dates_in_window) < 2:
        return "insufficient_history"
    ordered = sorted(dates_in_window)
    split = len(ordered) // 2
    older, recent = ordered[:split], ordered[split:]
    if not older or not recent:
        return "insufficient_history"
    r_old = sum(1 for d in older if d in hit_dates) / len(older)
    r_recent = sum(1 for d in recent if d in hit_dates) / len(recent)
    if r_recent < r_old - band:
        return "improving"
    if r_recent > r_old + band:
        return "worsening"
    return "persistent"


def run(ctx: AppContext, record_id: str) -> list[PatternFinding]:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    require(record.status, ACCEPTS, "pattern detection")

    window_n = int(ctx.stores.settings.get("window_n") or config.DEFAULT_WINDOW_N)
    threshold = int(ctx.stores.settings.get("threshold") or config.DEFAULT_THRESHOLD)
    band = float(ctx.stores.settings.get("trend_band") or config.DEFAULT_TREND_BAND)

    # Approved history only (FR-12 / C-19), excluding the lesson under review.
    history = ctx.stores.validated.approved_errors(
        record.student_ref, before=record.lesson_date, limit_lessons=window_n
    )
    window_dates = sorted({d for d, _ in history})

    by_key: dict[str, set[date]] = {}
    refs_by_key: dict[str, list[dict]] = {}
    for lesson_date, payload in history:
        key = payload.get("category", "")
        by_key.setdefault(key, set()).add(lesson_date)
        refs_by_key.setdefault(key, []).append(payload.get("source_ref", {}))

    findings: list[PatternFinding] = []
    for candidate in ctx.stores.candidates.errors(record_id):
        key = candidate.category
        hit_dates = by_key.get(key, set())
        occurrence_count = len(hit_dates) + 1  # + the lesson under review
        first_seen: Optional[date] = min(hit_dates) if hit_dates else record.lesson_date
        supporting = [candidate.source_ref]

        findings.append(PatternFinding(
            record_id=record_id,
            student_ref=record.student_ref,
            category=key,
            pattern_key=key,
            is_recurring=occurrence_count >= threshold,
            occurrence_count=occurrence_count,
            window_size=max(len(window_dates) + 1, 1),
            threshold=threshold,
            first_seen=first_seen,
            last_seen=record.lesson_date,
            trend=(_trend(window_dates + [record.lesson_date],
                          hit_dates | {record.lesson_date}, band)
                   if len(window_dates) + 1 >= threshold else "insufficient_history"),
            supporting_refs=supporting,
            rule_version=RULE_VERSION,
        ))

    findings.sort(key=lambda f: (not f.is_recurring, -f.occurrence_count, f.category))
    ctx.stores.candidates.put_many(record_id, "finding", findings)
    ctx.stores.lessons.set_status(record_id, RecordStatus.PATTERNS_LINKED)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="D:patterns", action="patterns.computed",
        after={"window_n": window_n, "threshold": threshold,
               "window_lessons": len(window_dates),
               "recurring": sum(1 for f in findings if f.is_recurring)},
        prompt_version=RULE_VERSION,
    ))
    return findings
