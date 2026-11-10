"""Component H — Export Service (Gate 3 enforcement + the only output producer).

Two properties make this the last line of the authority guarantee:

* a record not in ``Approved``/``Exported`` has no export path at all — this is
  the whole of FR-07 expressed as a precondition (invariant I-1);
* the output is a FILE. There is no email client, messaging client, webhook or
  third-party POST anywhere in this project, so the system cannot transmit
  anything to a student even if someone wanted it to (C-16).

Promotion to the validated store happens here and only here, which is why an
unapproved item can never enter a later recurrence count (C-19).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from .. import config
from ..context import AppContext
from ..models import (
    AuditEvent,
    ExportArtifact,
    SourceAppendixEntry,
    SummaryDraft,
    utcnow,
)
from ..states import EXPORTABLE, RecordStatus


class NotApproved(Exception):
    """Raised for any record that has not passed Gate 3."""


def _appendix(ctx: AppContext, record_id: str, draft: SummaryDraft) -> list[SourceAppendixEntry]:
    findings = {f.finding_id: f for f in ctx.stores.candidates.findings(record_id)}
    errors = {e.item_id: e for e in ctx.stores.candidates.errors(record_id)}
    entries: list[SourceAppendixEntry] = []
    seen: set[tuple[str, str]] = set()

    def add(statement_id: str, cites: list[str]) -> None:
        for cite in cites:
            refs = []
            if cite in findings:
                refs = findings[cite].supporting_refs
            elif cite in errors:
                refs = [errors[cite].source_ref]
            for ref in refs:
                key = (ref.lesson_date.isoformat(), ref.quoted_text)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(SourceAppendixEntry(
                    statement_id=statement_id, lesson_date=ref.lesson_date,
                    quoted_text=ref.quoted_text))

    for block in draft.body_blocks:
        add(block.block_id, block.cites)
    for goal in draft.goals:
        add(goal.goal_id, goal.cites)
    return entries


def render_text(ctx: AppContext, record_id: str, draft: SummaryDraft,
                appendix: list[SourceAppendixEntry]) -> str:
    record = ctx.stores.lessons.get(record_id)
    assert record is not None
    stamp = ("Tutor-approved" if draft.review_status == "tutor_approved"
             else "Draft - not reviewed")
    lines = [
        "SPANISH PROGRESS SUMMARY",
        f"Student: {record.student_ref}    Lesson: {record.lesson_date.isoformat()}",
        f"Level (set by your tutor): {draft.level_used}",
        f"Status: {stamp}",
        "=" * 64,
        "",
    ]
    for block in draft.body_blocks:
        lines.append(block.text)
        lines.append("")
    if draft.goals:
        lines.append("NEXT FOCUS")
        lines.append("-" * 64)
        for i, goal in enumerate(draft.goals, 1):
            lines.append(f"{i}. {goal.text}")
            lines.append(f"   {goal.practice}")
        lines.append("")
    lines.append("SOURCES")
    lines.append("-" * 64)
    if appendix:
        for entry in appendix:
            lines.append(f"[{entry.lesson_date.isoformat()}] \"{entry.quoted_text}\"")
    else:
        lines.append("(no source statements)")
    lines.append("")
    lines.append(f"Every statement above comes from your tutor's lesson notes. Status: {stamp}.")
    return "\n".join(lines)


def _render_pdf(path: Path, text: str) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    x, y = 20 * mm, height - 20 * mm
    for raw in text.split("\n"):
        line = raw
        while True:
            chunk, line = line[:95], line[95:]
            c.setFont("Helvetica-Bold" if chunk.isupper() and chunk.strip() else "Helvetica", 9)
            c.drawString(x, y, chunk)
            y -= 12
            if y < 20 * mm:
                c.showPage()
                y = height - 20 * mm
            if not line:
                break
    c.save()


def export(ctx: AppContext, record_id: str, fmt: str = "txt",
           out_dir: Optional[str] = None) -> ExportArtifact:
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise LookupError(record_id)
    if record.status not in EXPORTABLE:
        ctx.stores.audit.append(AuditEvent(
            record_id=record_id, actor="H:export", action="export.refused",
            outcome="blocked", reason=f"record is {record.status.value}, not Approved"))
        raise NotApproved(
            f"record is {record.status.value}; export requires an approved record (FR-07)"
        )

    draft = ctx.stores.candidates.draft(record_id)
    if draft is None:
        raise LookupError("no draft for this record")

    approved_at = utcnow()
    appendix = _appendix(ctx, record_id, draft)

    # Promote approved material into the validated store. This is the ONLY write
    # to D2 in the whole system (C-19).
    if record.status is RecordStatus.APPROVED:
        for item in ctx.stores.candidates.errors(record_id):
            if item.status in ("validated", "corrected"):
                ctx.stores.validated.promote(record, "error", item, item.item_id, approved_at)
        ctx.stores.validated.promote(record, "draft", draft, draft.draft_id, approved_at)

    text = render_text(ctx, record_id, draft, appendix)
    directory = Path(out_dir or config.EXPORT_DIR())
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{record.student_ref}_{record.lesson_date.isoformat()}_{record_id[:8]}"
    path = directory / f"{stem}.{fmt}"

    if fmt == "txt":
        path.write_text(text, encoding="utf-8")
    elif fmt == "pdf":
        _render_pdf(path, text)
    else:
        raise ValueError(f"unsupported format {fmt!r}")

    artifact = ExportArtifact(
        record_id=record_id, fmt=fmt, path=str(path), approved_at=approved_at,
        approved_by="tutor",
        status_stamp="Tutor-approved",
        source_appendix=appendix,
        content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    ctx.stores.lessons.set_status(record_id, RecordStatus.EXPORTED)
    ctx.stores.audit.append(AuditEvent(
        record_id=record_id, actor="H:export", action="export.written",
        after={"format": fmt, "path": str(path), "content_hash": artifact.content_hash,
               "appendix_entries": len(appendix)},
    ))
    return artifact
