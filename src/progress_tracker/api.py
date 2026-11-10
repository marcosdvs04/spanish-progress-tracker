"""FastAPI application: the JSON contract (§7.6) and the review workbench (G).

The workbench is server-rendered with no client-side state, so an unapproved
draft never exists outside the server's state machine.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config
from .context import AppContext
from .models import Disposition, NoteSubmission, RevisionRequest
from .services import export as export_svc
from .services import guard, intake, review, run_pipeline
from .services import validator as validator_svc
from .states import RecordStatus

config.load_dotenv()

app = FastAPI(
    title="Spanish Progress Tracker",
    version="1.0.0",
    description=(
        "AI-assisted Spanish student progress & error tracker. "
        "A bounded Document Intelligence pipeline with retained human authority."
    ),
)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
ctx = AppContext()


def _record_or_404(record_id: str):
    record = ctx.stores.lessons.get(record_id)
    if record is None:
        raise HTTPException(404, "unknown record")
    return record


# ================================================================ JSON contract


@app.post("/lessons", status_code=201)
def create_lesson(submission: NoteSubmission) -> dict:
    try:
        record = intake.register(ctx, submission)
    except intake.DuplicateLesson as exc:
        raise HTTPException(409, {"error": "DUPLICATE_LESSON", "record_id": exc.record_id})
    return {"record_id": record.record_id, "status": record.status.value}


@app.post("/lessons/{record_id}/run", status_code=202)
def run_lesson(record_id: str) -> dict:
    _record_or_404(record_id)
    result = run_pipeline(ctx, record_id)
    if result.status is RecordStatus.BLOCKED_CONSENT:
        raise HTTPException(403, {"error": "CONSENT_REQUIRED", "reason": result.blocked_reason})
    if result.status is RecordStatus.BLOCKED_INSUFFICIENT:
        raise HTTPException(422, {"error": "INSUFFICIENT_EVIDENCE", "missing": result.missing})
    if result.status is RecordStatus.BLOCKED_SERVICE:
        raise HTTPException(503, {"error": "SERVICE_UNAVAILABLE", "reason": result.blocked_reason})
    return {"record_id": record_id, "status": result.status.value}


@app.get("/review/{record_id}")
def get_review(record_id: str) -> dict:
    record = _record_or_404(record_id)
    draft = ctx.stores.candidates.draft(record_id)
    if draft is None:
        raise HTTPException(409, {"error": "NOT_READY", "status": record.status.value})
    return {
        "status": record.status.value,
        "draft": draft.model_dump(mode="json"),
        "errors": [e.model_dump(mode="json") for e in ctx.stores.candidates.errors(record_id)],
        "findings": [f.model_dump(mode="json")
                     for f in ctx.stores.candidates.findings(record_id)],
        "note_text": record.note_text,
    }


@app.post("/review/{record_id}/disposition")
def post_disposition(record_id: str, dispositions: list[Disposition] = Body(...)) -> dict:
    _record_or_404(record_id)
    try:
        still_open = review.apply_dispositions(ctx, record_id, dispositions)
    except Exception as exc:
        raise HTTPException(409, str(exc))
    return {"undispositioned_count": len(still_open), "undispositioned": still_open}


@app.post("/review/{record_id}/revise")
def post_revise(record_id: str, request: RevisionRequest) -> dict:
    _record_or_404(record_id)
    try:
        draft = review.revise(ctx, record_id, request)
    except review.RevisionLimitReached as exc:
        raise HTTPException(409, {"error": "REVISION_LIMIT_REACHED", "detail": str(exc)})
    return {"draft": draft.model_dump(mode="json")}


@app.post("/review/{record_id}/approve")
def post_approve(record_id: str, reviewer: str = Body("tutor", embed=True)) -> dict:
    _record_or_404(record_id)
    try:
        draft = review.approve(ctx, record_id, reviewer)
    except review.UndispositionedItems as exc:
        raise HTTPException(409, {"error": "UNDISPOSITIONED_ITEMS", "items": exc.item_ids})
    except guard.ConsentRequired as exc:
        raise HTTPException(403, {"error": "CONSENT_REQUIRED", "reason": str(exc)})
    return {"status": "Approved", "draft_id": draft.draft_id,
            "review_status": draft.review_status}


@app.post("/exports/{record_id}")
def post_export(record_id: str, fmt: str = Body("txt", embed=True)) -> dict:
    _record_or_404(record_id)
    try:
        artifact = export_svc.export(ctx, record_id, fmt)
    except export_svc.NotApproved as exc:
        raise HTTPException(409, {"error": "NOT_APPROVED", "detail": str(exc)})
    return artifact.model_dump(mode="json")


@app.get("/students/{student_ref}/history")
def get_history(student_ref: str, window: Optional[int] = None) -> dict:
    """Validated material only. Candidates are never included (FR-12)."""
    errors = ctx.stores.validated.approved_errors(student_ref, limit_lessons=window)
    return {
        "student_ref": student_ref,
        "approved_lessons": sorted({d.isoformat() for d, _ in errors}),
        "approved_errors": [{"lesson_date": d.isoformat(), "category": p.get("category")}
                            for d, p in errors],
        "approved_summaries": len(ctx.stores.validated.approved_drafts(student_ref)),
    }


@app.put("/config")
def put_config(payload: dict = Body(...)) -> dict:
    allowed = {"taxonomy", "window_n", "threshold", "trend_band", "level_bands"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(422, f"unknown setting(s): {sorted(unknown)}")
    if "window_n" in payload:
        n = int(payload["window_n"])
        if not (config.WINDOW_MIN <= n <= config.WINDOW_MAX):
            raise HTTPException(
                422, f"window_n must be between {config.WINDOW_MIN} and {config.WINDOW_MAX}")
    versions = {k: ctx.stores.settings.set(k, v) for k, v in payload.items()}
    return {"updated": versions}


@app.get("/audit/{record_id}")
def get_audit(record_id: str) -> dict:
    _record_or_404(record_id)
    return {"events": [{k: (v.isoformat() if hasattr(v, "isoformat") else v)
                        for k, v in e.items()}
                       for e in ctx.stores.audit.for_record(record_id)]}


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return f"ok provider={ctx.gateway.adapter.model_id}"


# ================================================================== workbench


@app.get("/", response_class=HTMLResponse)
def ui_index(request: Request) -> HTMLResponse:
    records = []
    with ctx.stores.engine.begin() as conn:
        from sqlalchemy import select

        from .store import lessons as t

        rows = conn.execute(select(t).order_by(t.c.submitted_at.desc())).mappings().all()
    for row in rows:
        records.append({"record_id": row["record_id"], "student_ref": row["student_ref"],
                        "lesson_date": row["lesson_date"], "status": row["status"]})
    return TEMPLATES.TemplateResponse(request, "index.html", {
        "records": records,
        "provider": ctx.gateway.adapter.model_id, "today": date.today().isoformat(),
    })


@app.post("/ui/lessons")
def ui_create(
    student_ref: str = Form(...), lesson_date: str = Form(...),
    tutor_level: str = Form(...), note_text: str = Form(...),
    topics: str = Form(""), homework: str = Form(""), is_minor: str = Form(""),
):
    submission = NoteSubmission(
        student_ref=student_ref.strip(), lesson_date=date.fromisoformat(lesson_date),
        tutor_level=tutor_level,  # type: ignore[arg-type]
        note_text=note_text,
        topics=[t.strip() for t in topics.split(",") if t.strip()],
        homework=homework.strip() or None, is_minor=bool(is_minor),
    )
    try:
        record = intake.register(ctx, submission)
    except intake.DuplicateLesson as exc:
        return RedirectResponse(f"/ui/review/{exc.record_id}?msg=duplicate", status_code=303)
    result = run_pipeline(ctx, record.record_id)
    if not result.ok:
        return RedirectResponse(
            f"/ui/blocked/{record.record_id}?reason={result.status.value}", status_code=303)
    return RedirectResponse(f"/ui/review/{record.record_id}", status_code=303)


@app.get("/ui/blocked/{record_id}", response_class=HTMLResponse)
def ui_blocked(request: Request, record_id: str, reason: str = "") -> HTMLResponse:
    record = _record_or_404(record_id)
    events = ctx.stores.audit.for_record(record_id)
    missing = [e["reason"] for e in events if e["outcome"] == "blocked" and e["reason"]]
    return TEMPLATES.TemplateResponse(request, "blocked.html", {
        "record": record, "reason": reason or record.status.value,
        "missing": missing,
    })


@app.get("/ui/review/{record_id}", response_class=HTMLResponse)
def ui_review(request: Request, record_id: str, msg: str = "") -> HTMLResponse:
    record = _record_or_404(record_id)
    try:
        draft = review.open_review(ctx, record_id)
    except Exception:
        return RedirectResponse(f"/ui/blocked/{record_id}?reason={record.status.value}",
                                status_code=303)
    record = _record_or_404(record_id)
    errors = ctx.stores.candidates.errors(record_id)
    findings = {f.category: f for f in ctx.stores.candidates.findings(record_id)}
    text = validator_svc.student_facing_text(draft)
    return TEMPLATES.TemplateResponse(request, "review.html", {
        "record": record, "draft": draft, "errors": errors,
        "findings": findings, "open_items": review._open_items(ctx, record_id),
        "msg": msg, "preview": text,
    })


@app.post("/ui/review/{record_id}/disposition")
def ui_disposition(record_id: str, request: Request, item_id: str = Form(...),
                   action: str = Form(...), after: str = Form("")):
    review.apply_dispositions(ctx, record_id, [Disposition(
        record_id=record_id, target=item_id, action=action,  # type: ignore[arg-type]
        after=after.strip() or None)])
    return RedirectResponse(f"/ui/review/{record_id}", status_code=303)


@app.post("/ui/review/{record_id}/approve")
def ui_approve(record_id: str):
    try:
        review.approve(ctx, record_id)
    except review.UndispositionedItems:
        return RedirectResponse(f"/ui/review/{record_id}?msg=open_items", status_code=303)
    except guard.ConsentRequired:
        return RedirectResponse(f"/ui/blocked/{record_id}?reason=consent", status_code=303)
    export_svc.export(ctx, record_id, "txt")
    export_svc.export(ctx, record_id, "pdf")
    return RedirectResponse(f"/ui/exported/{record_id}", status_code=303)


@app.get("/ui/exported/{record_id}", response_class=HTMLResponse)
def ui_exported(request: Request, record_id: str) -> HTMLResponse:
    record = _record_or_404(record_id)
    draft = ctx.stores.candidates.draft(record_id)
    assert draft is not None
    appendix = export_svc._appendix(ctx, record_id, draft)  # noqa: SLF001
    body = export_svc.render_text(ctx, record_id, draft, appendix)
    return TEMPLATES.TemplateResponse(request, "exported.html", {
        "record": record, "body": body,
        "export_dir": config.EXPORT_DIR(),
    })
