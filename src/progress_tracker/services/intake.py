"""Component A — Intake & Registration API.

Registers a lesson note as an immutable source record and starts a run.
Performs no interpretation whatsoever.
"""

from __future__ import annotations

from ..context import AppContext
from ..models import AuditEvent, LessonRecord, NoteSubmission, sha256
from ..states import RecordStatus


class DuplicateLesson(Exception):
    """Same student, same date, same note text — idempotency guard.

    Without this, resubmitting a lesson would double-count every error in it and
    corrupt the recurrence window (PR-1).
    """

    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        super().__init__(f"this lesson is already recorded as {record_id}")


def register(ctx: AppContext, submission: NoteSubmission) -> LessonRecord:
    note_hash = sha256(submission.note_text)
    existing = ctx.stores.lessons.find_duplicate(
        submission.student_ref, submission.lesson_date, note_hash
    )
    if existing:
        ctx.stores.audit.append(AuditEvent(
            record_id=existing, actor="A:intake", action="lesson.duplicate_rejected",
            outcome="blocked", reason="same student, date and note hash",
        ))
        raise DuplicateLesson(existing)

    record = LessonRecord(
        student_ref=submission.student_ref,
        lesson_date=submission.lesson_date,
        note_text=submission.note_text,
        note_hash=note_hash,
        topics=submission.topics,
        homework=submission.homework,
        tutor_level=submission.tutor_level,
        is_minor=submission.is_minor,
        status=RecordStatus.REGISTERED,
    )
    ctx.stores.lessons.add(record)
    ctx.stores.audit.append(AuditEvent(
        record_id=record.record_id, actor="A:intake", action="lesson.registered",
        after={"note_hash": record.note_hash, "student_ref": record.student_ref,
               "lesson_date": record.lesson_date.isoformat()},
    ))
    return record
