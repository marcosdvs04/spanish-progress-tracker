"""Command line entry point.

``spt demo`` runs the whole bounded capability end to end against synthetic data
and prints every state transition, so the demonstration is reproducible and does
not depend on clicking through the UI.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from . import config, demo_data
from .context import AppContext
from .models import Disposition, NoteSubmission
from .services import export as export_svc
from .services import guard, intake, review, run_pipeline
from .states import RecordStatus

LINE = "-" * 72


def _p(text: str = "") -> None:
    print(text, flush=True)


def _dispose_all(ctx: AppContext, record_id: str, action: str = "validate") -> list[str]:
    open_items = review._open_items(ctx, record_id)  # noqa: SLF001 - demo introspection
    dispositions = [
        Disposition(record_id=record_id, target=item, action=action)  # type: ignore[arg-type]
        for item in open_items
    ]
    return review.apply_dispositions(ctx, record_id, dispositions)


def _usable(path: Path) -> Path:
    """Return a path SQLite can actually write to.

    Synced folders, network mounts and sandboxes can accept an ordinary file
    write yet refuse the locking SQLite needs, which surfaces as a bare "disk
    I/O error" halfway through a demonstration. Probe once, and fall back to a
    temporary directory with a clear message rather than failing in front of an
    audience.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".spt-probe.db"
        conn = sqlite3.connect(probe)
        conn.execute("create table t (x int)")
        conn.commit()
        conn.close()
        probe.unlink(missing_ok=True)
        return path
    except Exception:
        fallback = Path(tempfile.mkdtemp(prefix="spt-demo-")) / path.name
        _p(f"note: {path.parent} is not writable by SQLite here; using {fallback.parent}")
        return fallback


def _fresh(path: Path) -> Path:
    """Start the demonstration from a clean slate.

    Some environments (sandboxes, synced folders, read-only mounts) refuse the
    delete. Rather than abort a demonstration over housekeeping, fall back to a
    uniquely named sibling so the run still starts empty.
    """
    try:
        if path.exists():
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        return path
    except OSError:
        return path.with_name(f"{path.stem}-{int(time.time())}{path.suffix}")


def _seed_lesson(ctx: AppContext, note: NoteSubmission, quiet: bool = True) -> Optional[str]:
    record = intake.register(ctx, note)
    result = run_pipeline(ctx, record.record_id)
    if not result.ok:
        if not quiet:
            _p(f"  blocked: {result.status.value} ({result.blocked_reason})")
        return None
    review.open_review(ctx, record.record_id)
    _dispose_all(ctx, record.record_id)
    review.approve(ctx, record.record_id)
    export_svc.export(ctx, record.record_id, "txt")
    return record.record_id


def cmd_demo(args: argparse.Namespace) -> int:
    db = _usable(_fresh(Path(args.db or "data/demo.db")))
    out = str(_fresh(Path(args.out or "exports/demo")))
    try:
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / ".probe").write_text("x")
        (Path(out) / ".probe").unlink()
    except Exception:
        out = tempfile.mkdtemp(prefix="spt-exports-")
        _p(f"note: export directory not writable here; using {out}")
    ctx = AppContext(db_path=str(db))

    _p(LINE)
    _p("SPANISH PROGRESS TRACKER — end-to-end demonstration (synthetic data only)")
    _p(f"model provider : {ctx.gateway.adapter.model_id}")
    _p(LINE)

    _p("\n[1] Seeding four approved lessons as the student's history")
    for note in demo_data.HISTORY:
        rid = _seed_lesson(ctx, note)
        _p(f"    {note.lesson_date}  approved+exported  record {rid[:8] if rid else 'n/a'}")

    _p("\n[2] New lesson arrives — the one under review")
    record = intake.register(ctx, demo_data.CURRENT)
    _p(f"    registered {record.record_id[:8]}  status={record.status.value}")
    result = run_pipeline(ctx, record.record_id)
    _p(f"    pipeline finished  status={result.status.value}")

    _p("\n[3] Recurrence findings (deterministic, no model involved)")
    for f in ctx.stores.candidates.findings(record.record_id):
        flag = "RECURRING" if f.is_recurring else "one-off  "
        _p(f"    {flag}  {f.category:<28} {f.occurrence_count} of last {f.window_size}"
           f"  trend={f.trend}")

    draft = result.draft
    assert draft is not None
    _p(f"\n[4] Draft readability  mean sentence={draft.readability.mean_sentence_len} words"
       f"  spanish ratio={draft.readability.target_lang_ratio}"
       f"  passed={draft.readability.passed}")
    _p(f"    review status stamped on the draft: {draft.review_status}")

    _p("\n[5] Export before approval must be refused")
    try:
        export_svc.export(ctx, record.record_id, "txt", out_dir=out)
        _p("    !! EXPORTED WITHOUT APPROVAL — control C-13 FAILED")
        return 1
    except export_svc.NotApproved as exc:
        _p(f"    refused: {exc}")

    _p("\n[6] Tutor opens the review and corrects one goal")
    review.open_review(ctx, record.record_id)
    if draft.goals:
        goal = draft.goals[0]
        corrected = "Objetivo: usar 'estar' para estados temporales."
        review.apply_dispositions(ctx, record.record_id, [Disposition(
            record_id=record.record_id, target=goal.goal_id, action="correct",
            after=corrected)])
        _p(f"    corrected goal -> {corrected}")

    _p("\n[7] Approval with items still open must be refused")
    try:
        review.approve(ctx, record.record_id)
        _p("    !! APPROVED WITH OPEN ITEMS — control C-13 FAILED")
        return 1
    except review.UndispositionedItems as exc:
        _p(f"    refused: {exc}")

    _p("\n[8] Tutor dispositions every candidate, then approves")
    remaining = _dispose_all(ctx, record.record_id)
    _p(f"    open items remaining: {len(remaining)}")
    approved = review.approve(ctx, record.record_id)
    _p(f"    approved; draft status is now '{approved.review_status}'")

    _p("\n[9] Export")
    txt = export_svc.export(ctx, record.record_id, "txt", out_dir=out)
    pdf = export_svc.export(ctx, record.record_id, "pdf", out_dir=out)
    _p(f"    {txt.path}  sha256={txt.content_hash[:16]}...")
    _p(f"    {pdf.path}  sha256={pdf.content_hash[:16]}...")
    _p(f"    source appendix entries: {len(txt.source_appendix)}")

    _p("\n[10] Refusal path — a note with nothing specific in it")
    sparse = intake.register(ctx, demo_data.SPARSE)
    sparse_result = run_pipeline(ctx, sparse.record_id)
    _p(f"    status={sparse_result.status.value}")
    for missing in sparse_result.missing:
        _p(f"    needs: {missing}")

    _p("\n[11] Consent path — a minor with no guardian consent on file")
    before = len(ctx.gateway.sent_payloads)
    minor = intake.register(ctx, demo_data.MINOR)
    minor_result = run_pipeline(ctx, minor.record_id)
    after = len(ctx.gateway.sent_payloads)
    _p(f"    status={minor_result.status.value}")
    _p(f"    outbound model calls for this record: {after - before}  (must be 0)")

    _p("\n[12] Minimization — contact details never leave the trust boundary")
    contact = intake.register(ctx, demo_data.WITH_CONTACT)
    run_pipeline(ctx, contact.record_id)
    payload = str(ctx.gateway.sent_payloads[-2:])
    for needle in ("jordan.fake@example-mail.com", "555 010 9988"):
        _p(f"    '{needle}' present in outbound payload: {needle in payload}")

    _p("\n[13] Audit replay — the run reconstructed from the log, no model invoked")
    for event in ctx.stores.audit.for_record(record.record_id):
        _p(f"    {event['at']}  {event['actor']:<14} {event['action']:<26}"
           f" {event['outcome']}")

    _p("\n" + LINE)
    _p(f"Demonstration complete. Artifacts in {out}")
    _p(LINE)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("progress_tracker.api:app", host=args.host, port=args.port,
                reload=args.reload)
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    for target in (args.db or config.DB_PATH(), config.EXPORT_DIR()):
        path = Path(target)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        _p(f"removed {path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    config.load_dotenv()
    parser = argparse.ArgumentParser(prog="spt", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("demo", help="run the scripted end-to-end demonstration")
    d.add_argument("--db", default=None)
    d.add_argument("--out", default=None)
    d.set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="run the review workbench")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(func=cmd_serve)

    r = sub.add_parser("reset", help="delete the local database and exports")
    r.add_argument("--db", default=None)
    r.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
