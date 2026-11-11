"""Persistence layer: stores D1-D6 and their repositories.

The candidate/validated split is physical, not a convention: ``candidates`` and
``validated`` are separate tables behind separate repositories, and only the
export service writes to ``validated`` (FR-12 / C-19).

``audit`` is append-only. The repository exposes no update or delete method and
SQLite triggers reject both, so the accountability record cannot be rewritten
even from a direct SQL console (C-09).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Date,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine

from . import config
from .models import (
    AuditEvent,
    CandidateError,
    ConsentRecord,
    LessonRecord,
    PatternFinding,
    SummaryDraft,
)
from .states import RecordStatus

metadata = MetaData()

# D1 — source notes, immutable after registration
lessons = Table(
    "lessons", metadata,
    Column("record_id", String, primary_key=True),
    Column("student_ref", String, nullable=False, index=True),
    Column("lesson_date", Date, nullable=False),
    Column("submitted_at", DateTime, nullable=False),
    Column("note_text", Text, nullable=False),
    Column("note_hash", String, nullable=False),
    Column("topics", Text, nullable=False, default="[]"),
    Column("homework", Text),
    Column("tutor_level", String, nullable=False),
    Column("is_minor", Boolean, nullable=False, default=False),
    Column("status", String, nullable=False),
    Column("revision_no", Integer, nullable=False, default=0),
)

# D3 — candidate information. Never read by the export path.
candidates = Table(
    "candidates", metadata,
    Column("id", String, primary_key=True),
    Column("record_id", String, nullable=False, index=True),
    Column("kind", String, nullable=False),          # error | finding | draft
    Column("status", String, nullable=False, default="candidate"),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

# D2 — validated knowledge. Written only by the export service, only on approval.
validated = Table(
    "validated", metadata,
    Column("id", String, primary_key=True),
    Column("record_id", String, nullable=False, index=True),
    Column("student_ref", String, nullable=False, index=True),
    Column("lesson_date", Date, nullable=False),
    Column("kind", String, nullable=False),          # error | draft
    Column("payload", Text, nullable=False),
    Column("approved_at", DateTime, nullable=False),
)

# D4 — audit, approval and consent register (append-only)
audit = Table(
    "audit", metadata,
    Column("event_id", String, primary_key=True),
    Column("record_id", String, index=True),
    Column("at", DateTime, nullable=False),
    Column("actor", String, nullable=False),
    Column("action", String, nullable=False),
    Column("target", String),
    Column("before", Text),
    Column("after", Text),
    Column("model_id", String),
    Column("prompt_version", String),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("latency_ms", Integer),
    Column("outcome", String, nullable=False, default="ok"),
    Column("reason", Text),
)

consents = Table(
    "consents", metadata,
    Column("consent_id", String, primary_key=True),
    Column("student_ref", String, nullable=False, index=True),
    Column("guardian_label", String, nullable=False),
    Column("granted_at", DateTime, nullable=False),
    Column("expires_at", DateTime),
    Column("withdrawn_at", DateTime),
    Column("scope", String, nullable=False, default="generate"),
)

# D5 — versioned prompt templates, so a run can be reconstructed exactly
prompts = Table(
    "prompts", metadata,
    Column("template_id", String, primary_key=True),
    Column("version", String, primary_key=True),
    Column("body", Text, nullable=False),
)

# D6 — tutor-editable configuration (NFR-12 / C-17)
settings = Table(
    "settings", metadata,
    Column("key", String, primary_key=True),
    Column("value", Text, nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("updated_at", DateTime, nullable=False),
)

_APPEND_ONLY_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS audit_no_update
       BEFORE UPDATE ON audit
       BEGIN SELECT RAISE(ABORT, 'audit is append-only (C-09)'); END;""",
    """CREATE TRIGGER IF NOT EXISTS audit_no_delete
       BEFORE DELETE ON audit
       BEGIN SELECT RAISE(ABORT, 'audit is append-only (C-09)'); END;""",
    """CREATE TRIGGER IF NOT EXISTS lessons_immutable_note
       BEFORE UPDATE OF note_text, note_hash, lesson_date, student_ref ON lessons
       BEGIN SELECT RAISE(ABORT, 'lesson notes are immutable once registered'); END;""",
)


def _json(value: Any) -> str:
    def enc(o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        raise TypeError(type(o))

    return json.dumps(value, default=enc)


def make_engine(db_path: Optional[str] = None) -> Engine:
    path = db_path or config.DB_PATH()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    else:
        url = "sqlite://"
    engine = create_engine(url, future=True)
    metadata.create_all(engine)
    with engine.begin() as conn:
        for trg in _APPEND_ONLY_TRIGGERS:
            conn.execute(text(trg))
    return engine


# --------------------------------------------------------------- repositories


class AuditRepo:
    """Append-only. Deliberately exposes no update() or delete()."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, event: AuditEvent) -> None:
        with self._engine.begin() as conn:
            conn.execute(audit.insert().values(
                event_id=event.event_id, record_id=event.record_id, at=event.at,
                actor=event.actor, action=event.action, target=event.target,
                before=_json(event.before) if event.before else None,
                after=_json(event.after) if event.after else None,
                model_id=event.model_id, prompt_version=event.prompt_version,
                tokens_in=event.tokens_in, tokens_out=event.tokens_out,
                latency_ms=event.latency_ms, outcome=event.outcome, reason=event.reason,
            ))

    def for_record(self, record_id: str) -> list[dict]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(audit).where(audit.c.record_id == record_id).order_by(audit.c.at)
            ).mappings().all()
        return [dict(r) for r in rows]

    def all(self) -> list[dict]:
        with self._engine.begin() as conn:
            rows = conn.execute(select(audit).order_by(audit.c.at)).mappings().all()
        return [dict(r) for r in rows]


class LessonRepo:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, record: LessonRecord) -> None:
        with self._engine.begin() as conn:
            conn.execute(lessons.insert().values(
                record_id=record.record_id, student_ref=record.student_ref,
                lesson_date=record.lesson_date, submitted_at=record.submitted_at,
                note_text=record.note_text, note_hash=record.note_hash,
                topics=_json(record.topics), homework=record.homework,
                tutor_level=record.tutor_level, is_minor=record.is_minor,
                status=record.status.value, revision_no=record.revision_no,
            ))

    def get(self, record_id: str) -> Optional[LessonRecord]:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(lessons).where(lessons.c.record_id == record_id)
            ).mappings().first()
        if row is None:
            return None
        data = dict(row)
        data["topics"] = json.loads(data["topics"])
        data["status"] = RecordStatus(data["status"])
        return LessonRecord(**data)

    def find_duplicate(self, student_ref: str, lesson_date: date, note_hash: str) -> Optional[str]:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(lessons.c.record_id).where(
                    lessons.c.student_ref == student_ref,
                    lessons.c.lesson_date == lesson_date,
                    lessons.c.note_hash == note_hash,
                )
            ).first()
        return row[0] if row else None

    def set_status(self, record_id: str, status: RecordStatus) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(lessons).where(lessons.c.record_id == record_id)
                         .values(status=status.value))

    def bump_revision(self, record_id: str) -> int:
        rec = self.get(record_id)
        assert rec is not None
        new_no = rec.revision_no + 1
        with self._engine.begin() as conn:
            conn.execute(update(lessons).where(lessons.c.record_id == record_id)
                         .values(revision_no=new_no))
        return new_no

    def list_for_student(self, student_ref: str) -> list[LessonRecord]:
        with self._engine.begin() as conn:
            ids = conn.execute(
                select(lessons.c.record_id).where(lessons.c.student_ref == student_ref)
                .order_by(lessons.c.lesson_date)
            ).scalars().all()
        return [r for r in (self.get(i) for i in ids) if r is not None]


class CandidateRepo:
    """Store D3. Unvalidated items only; never read by the export path."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def put(self, record_id: str, kind: str, obj: Any, item_id: str, status: str = "candidate") -> None:
        payload = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj
        with self._engine.begin() as conn:
            conn.execute(delete(candidates).where(candidates.c.id == item_id))
            conn.execute(candidates.insert().values(
                id=item_id, record_id=record_id, kind=kind, status=status,
                payload=_json(payload), created_at=datetime.now(timezone.utc),
            ))

    def put_many(self, record_id: str, kind: str, objs: Iterable[Any]) -> None:
        for obj in objs:
            ident = getattr(obj, "item_id", None) or getattr(obj, "finding_id", None) \
                or getattr(obj, "draft_id", None)
            self.put(record_id, kind, obj, ident)

    def _rows(self, record_id: str, kind: str) -> list[dict]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(candidates).where(
                    candidates.c.record_id == record_id, candidates.c.kind == kind
                ).order_by(candidates.c.created_at)
            ).mappings().all()
        return [dict(r) for r in rows]

    def errors(self, record_id: str) -> list[CandidateError]:
        out = []
        for row in self._rows(record_id, "error"):
            data = json.loads(row["payload"])
            data["status"] = row["status"]
            out.append(CandidateError(**data))
        return out

    def findings(self, record_id: str) -> list[PatternFinding]:
        out = []
        for row in self._rows(record_id, "finding"):
            data = json.loads(row["payload"])
            data["status"] = row["status"]
            out.append(PatternFinding(**data))
        return out

    def draft(self, record_id: str) -> Optional[SummaryDraft]:
        rows = self._rows(record_id, "draft")
        return SummaryDraft(**json.loads(rows[-1]["payload"])) if rows else None

    def set_item_status(self, item_id: str, status: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(update(candidates).where(candidates.c.id == item_id)
                         .values(status=status))

    def undispositioned(self, record_id: str) -> list[str]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(candidates.c.id).where(
                    candidates.c.record_id == record_id,
                    candidates.c.kind.in_(("error", "finding")),
                    candidates.c.status == "candidate",
                )
            ).scalars().all()
        return list(rows)


class ValidatedRepo:
    """Store D2. The only source for history and trend. Written on approval only."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def promote(self, record: LessonRecord, kind: str, obj: Any, ident: str,
                approved_at: datetime) -> None:
        payload = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj
        with self._engine.begin() as conn:
            conn.execute(delete(validated).where(validated.c.id == ident))
            conn.execute(validated.insert().values(
                id=ident, record_id=record.record_id, student_ref=record.student_ref,
                lesson_date=record.lesson_date, kind=kind,
                payload=_json(payload), approved_at=approved_at,
            ))

    def approved_errors(self, student_ref: str, before: Optional[date] = None,
                        limit_lessons: Optional[int] = None) -> list[tuple[date, dict]]:
        """Approved error items, newest lesson first, optionally limited to N lessons."""
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(validated.c.lesson_date, validated.c.payload).where(
                    validated.c.student_ref == student_ref, validated.c.kind == "error"
                ).order_by(validated.c.lesson_date.desc())
            ).all()
        items = [(r[0], json.loads(r[1])) for r in rows]
        if before is not None:
            items = [i for i in items if i[0] < before]
        if limit_lessons is not None:
            keep: list[date] = []
            for d, _ in items:
                if d not in keep:
                    keep.append(d)
                if len(keep) >= limit_lessons:
                    break
            items = [i for i in items if i[0] in keep]
        return items

    def approved_drafts(self, student_ref: str) -> list[dict]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(validated.c.payload).where(
                    validated.c.student_ref == student_ref, validated.c.kind == "draft"
                ).order_by(validated.c.lesson_date)
            ).scalars().all()
        return [json.loads(r) for r in rows]


class ConsentRepo:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def grant(self, record: ConsentRecord) -> None:
        with self._engine.begin() as conn:
            conn.execute(consents.insert().values(
                consent_id=record.consent_id, student_ref=record.student_ref,
                guardian_label=record.guardian_label, granted_at=record.granted_at,
                expires_at=record.expires_at, withdrawn_at=record.withdrawn_at,
                scope=record.scope,
            ))

    def withdraw(self, student_ref: str, when: Optional[datetime] = None) -> None:
        """Sets a timestamp. Never deletes the record — the trail must survive (PR-6)."""
        with self._engine.begin() as conn:
            conn.execute(update(consents).where(
                consents.c.student_ref == student_ref,
                consents.c.withdrawn_at.is_(None),
            ).values(withdrawn_at=when or datetime.now(timezone.utc)))

    def current(self, student_ref: str) -> Optional[ConsentRecord]:
        with self._engine.begin() as conn:
            row = conn.execute(
                select(consents).where(consents.c.student_ref == student_ref)
                .order_by(consents.c.granted_at.desc())
            ).mappings().first()
        return ConsentRecord(**dict(row)) if row else None


class SettingsRepo:
    """Store D6. Tutor-editable behaviour, versioned and audited."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._seed()

    def _seed(self) -> None:
        defaults = {
            "taxonomy": config.DEFAULT_TAXONOMY,
            "window_n": config.DEFAULT_WINDOW_N,
            "threshold": config.DEFAULT_THRESHOLD,
            "trend_band": config.DEFAULT_TREND_BAND,
            "level_bands": config.LEVEL_BANDS,
        }
        with self._engine.begin() as conn:
            existing = set(conn.execute(select(settings.c.key)).scalars().all())
            for key, value in defaults.items():
                if key not in existing:
                    conn.execute(settings.insert().values(
                        key=key, value=_json(value), version=1,
                        updated_at=datetime.now(timezone.utc),
                    ))

    def get(self, key: str) -> Any:
        with self._engine.begin() as conn:
            row = conn.execute(select(settings.c.value).where(settings.c.key == key)).first()
        return json.loads(row[0]) if row else None

    def set(self, key: str, value: Any) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(select(settings.c.version).where(settings.c.key == key)).first()
            version = (row[0] + 1) if row else 1
            if row:
                conn.execute(update(settings).where(settings.c.key == key).values(
                    value=_json(value), version=version, updated_at=datetime.now(timezone.utc)))
            else:
                conn.execute(settings.insert().values(
                    key=key, value=_json(value), version=version,
                    updated_at=datetime.now(timezone.utc)))
        return version


class PromptRepo:
    """Store D5. Versioned templates so a run can be reconstructed exactly."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def put(self, template_id: str, version: str, body: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(delete(prompts).where(
                prompts.c.template_id == template_id, prompts.c.version == version))
            conn.execute(prompts.insert().values(
                template_id=template_id, version=version, body=body))

    def get(self, template_id: str, version: str) -> Optional[str]:
        with self._engine.begin() as conn:
            row = conn.execute(select(prompts.c.body).where(
                prompts.c.template_id == template_id, prompts.c.version == version)).first()
        return row[0] if row else None


class Stores:
    """Convenience bundle passed to the services."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.lessons = LessonRepo(engine)
        self.candidates = CandidateRepo(engine)
        self.validated = ValidatedRepo(engine)
        self.audit = AuditRepo(engine)
        self.consents = ConsentRepo(engine)
        self.settings = SettingsRepo(engine)
        self.prompts = PromptRepo(engine)


def open_stores(db_path: Optional[str] = None) -> Stores:
    return Stores(make_engine(db_path))
