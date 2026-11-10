"""Shared fixtures. Every test runs offline against the deterministic stub."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from progress_tracker.context import AppContext            # noqa: E402
from progress_tracker.gateway import LLMGateway, StubAdapter  # noqa: E402
from progress_tracker.models import Disposition, NoteSubmission  # noqa: E402
from progress_tracker.services import export as export_svc  # noqa: E402
from progress_tracker.services import intake, review, run_pipeline  # noqa: E402
from progress_tracker.store import open_stores             # noqa: E402


@pytest.fixture()
def ctx(tmp_path: Path) -> AppContext:
    stores = open_stores(str(tmp_path / "test.db"))
    gateway = LLMGateway(adapter=StubAdapter(), audit=stores.audit, backoff_base=0.0)
    context = AppContext(stores=stores, gateway=gateway)
    context.export_dir = str(tmp_path / "exports")  # type: ignore[attr-defined]
    return context


@pytest.fixture()
def out_dir(tmp_path: Path) -> str:
    d = tmp_path / "exports"
    d.mkdir(exist_ok=True)
    return str(d)


def note(text: str, *, student: str = "syn-t-01", day: int = 1, level: str = "B1",
         topics: list[str] | None = None, homework: str | None = "Practice",
         minor: bool = False) -> NoteSubmission:
    return NoteSubmission(
        student_ref=student, lesson_date=date(2026, 9, day), tutor_level=level,  # type: ignore[arg-type]
        note_text=text, topics=topics or ["Topic"], homework=homework, is_minor=minor,
    )


def dispose_all(ctx: AppContext, record_id: str, action: str = "validate") -> list[str]:
    open_items = review._open_items(ctx, record_id)   # noqa: SLF001
    return review.apply_dispositions(ctx, record_id, [
        Disposition(record_id=record_id, target=i, action=action)  # type: ignore[arg-type]
        for i in open_items
    ])


def approve_and_export(ctx: AppContext, record_id: str, out: str) -> None:
    review.open_review(ctx, record_id)
    dispose_all(ctx, record_id)
    review.approve(ctx, record_id)
    export_svc.export(ctx, record_id, "txt", out_dir=out)


def seed_lesson(ctx: AppContext, submission: NoteSubmission, out: str) -> str:
    record = intake.register(ctx, submission)
    result = run_pipeline(ctx, record.record_id)
    assert result.ok, f"pipeline blocked: {result.status} {result.missing}"
    approve_and_export(ctx, record.record_id, out)
    return record.record_id
