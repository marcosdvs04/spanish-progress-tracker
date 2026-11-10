"""Information structures (Solution Design Report §7.5).

Three fields carry the architecture's guarantees and appear on nearly everything:
``record_id`` (which run), ``source_ref`` (what evidence supports this), and
``status`` (how far it has been reviewed).

``SourceRef`` is a REQUIRED field on every candidate item. That single schema
decision is control C-08: an ungrounded candidate cannot be constructed, let
alone stored.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .states import RecordStatus

CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1"]


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat a naive value as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------- D1: source


class NoteSubmission(Base):
    """Input to component A. The tutor's own words, unmodified."""

    student_ref: str = Field(min_length=1, max_length=64)
    lesson_date: date
    note_text: str = Field(min_length=1)
    tutor_level: CEFRLevel
    topics: list[str] = Field(default_factory=list)
    homework: Optional[str] = None
    is_minor: bool = False


class LessonRecord(Base):
    """Immutable after registration. The anchor for every source reference."""

    record_id: str = Field(default_factory=new_id)
    student_ref: str
    lesson_date: date
    submitted_at: datetime = Field(default_factory=utcnow)
    note_text: str
    note_hash: str = ""
    topics: list[str] = Field(default_factory=list)
    homework: Optional[str] = None
    tutor_level: CEFRLevel
    is_minor: bool = False
    status: RecordStatus = RecordStatus.REGISTERED
    revision_no: int = 0

    @field_validator("note_hash", mode="before")
    @classmethod
    def _default_hash(cls, v: Any, info: Any) -> Any:
        if v:
            return v
        data = info.data if hasattr(info, "data") else {}
        return sha256(data.get("note_text", ""))


# ------------------------------------------------------ traceability primitive


class SourceRef(Base):
    """Character span into an immutable ``LessonRecord.note_text``."""

    record_id: str
    lesson_date: date
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    quoted_text: str = Field(min_length=1)

    @field_validator("span_end")
    @classmethod
    def _end_after_start(cls, v: int, info: Any) -> int:
        start = (info.data or {}).get("span_start", 0)
        if v <= start:
            raise ValueError("span_end must be greater than span_start")
        return v

    def resolves_in(self, note_text: str) -> bool:
        """True when the span still points at the text it claims to quote."""
        if self.span_end > len(note_text):
            return False
        return note_text[self.span_start : self.span_end] == self.quoted_text


# ---------------------------------------------------- D3: candidate information

ItemStatus = Literal["candidate", "validated", "corrected", "rejected", "questioned"]
Severity = Literal["low", "medium", "high"]


class CandidateError(Base):
    """Produced by component C. Stored in D3 and never in D2 (FR-12 / C-19)."""

    item_id: str = Field(default_factory=new_id)
    record_id: str
    error_text: str = Field(min_length=1)
    category: str = Field(min_length=1)
    severity: Severity = "medium"
    source_ref: SourceRef  # required — control C-08
    origin: Literal["ai_extraction", "tutor"] = "ai_extraction"
    status: ItemStatus = "candidate"


Trend = Literal["improving", "persistent", "worsening", "insufficient_history"]


class PatternFinding(Base):
    """Produced by component D. Deterministic: no model call (PR-1)."""

    finding_id: str = Field(default_factory=new_id)
    record_id: str
    student_ref: str
    category: str
    pattern_key: str
    is_recurring: bool
    occurrence_count: int = Field(ge=0)
    window_size: int = Field(ge=1)
    threshold: int = Field(ge=1)
    first_seen: Optional[date] = None
    last_seen: Optional[date] = None
    trend: Trend = "insufficient_history"
    supporting_refs: list[SourceRef] = Field(default_factory=list)
    rule_version: str = "PR-1/v1"


BlockKind = Literal["progress", "pattern", "goal", "practice", "level"]


class SummaryBlock(Base):
    block_id: str = Field(default_factory=new_id)
    kind: BlockKind
    text: str = Field(min_length=1)
    cites: list[str] = Field(default_factory=list)  # finding_id / item_id / "tutor_level"


class Goal(Base):
    goal_id: str = Field(default_factory=new_id)
    text: str = Field(min_length=1)
    practice: str = Field(min_length=1)
    cites: list[str] = Field(default_factory=list)


class Readability(Base):
    mean_sentence_len: float = 0.0
    target_lang_ratio: float = 0.0
    passed: bool = False


class SummaryDraft(Base):
    """Produced by component E, revised through component G."""

    draft_id: str = Field(default_factory=new_id)
    record_id: str
    revision_no: int = 0
    level_used: CEFRLevel
    body_blocks: list[SummaryBlock] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    readability: Readability = Field(default_factory=Readability)
    model_id: str = ""
    prompt_version: str = ""
    #: Rendered on screen and stamped into every artifact (NFR-06 / C-10).
    review_status: Literal["draft", "tutor_approved"] = "draft"


# ------------------------------------------------------------- review actions

DispositionAction = Literal["validate", "correct", "reject", "question"]


class Disposition(Base):
    """Exactly four reviewer actions exist (FR-13)."""

    disposition_id: str = Field(default_factory=new_id)
    record_id: str
    target: str  # item_id | finding_id | block_id | goal_id
    action: DispositionAction
    before: Optional[str] = None
    after: Optional[str] = None
    note: Optional[str] = None
    reviewer: str = "tutor"
    decided_at: datetime = Field(default_factory=utcnow)


class RevisionRequest(Base):
    record_id: str
    scope: Literal["summary", "goals"]
    instructions: str = Field(min_length=1)


# -------------------------------------------------------------------- consent


class ConsentState(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ConsentRecord(Base):
    """Read at Gate 1. ``state`` is derived, never hand-set (PR-6)."""

    consent_id: str = Field(default_factory=new_id)
    student_ref: str
    guardian_label: str
    granted_at: datetime = Field(default_factory=utcnow)
    expires_at: Optional[datetime] = None
    withdrawn_at: Optional[datetime] = None
    scope: Literal["generate", "generate_and_share"] = "generate"

    @property
    def state(self) -> ConsentState:
        if self.withdrawn_at is not None:
            return ConsentState.WITHDRAWN
        if self.expires_at is not None and as_utc(self.expires_at) <= utcnow():
            return ConsentState.EXPIRED
        return ConsentState.ACTIVE

    def covers(self, operation: str) -> bool:
        if self.state is not ConsentState.ACTIVE:
            return False
        return operation == "generate" or self.scope == "generate_and_share"


# ---------------------------------------------------------------- D4: audit


class AuditEvent(Base):
    """Append-only. No update or delete path exists anywhere (C-09)."""

    event_id: str = Field(default_factory=new_id)
    record_id: Optional[str] = None
    at: datetime = Field(default_factory=utcnow)
    actor: str
    action: str
    target: Optional[str] = None
    before: Optional[dict] = None
    after: Optional[dict] = None
    model_id: Optional[str] = None
    prompt_version: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    latency_ms: Optional[int] = None
    outcome: Literal["ok", "blocked", "error"] = "ok"
    reason: Optional[str] = None


# -------------------------------------------------------------------- output


class SourceAppendixEntry(Base):
    statement_id: str
    lesson_date: date
    quoted_text: str


class ExportArtifact(Base):
    """Produced by component H only, and only from state Approved (FR-15)."""

    artifact_id: str = Field(default_factory=new_id)
    record_id: str
    fmt: Literal["txt", "pdf"]
    path: str
    approved_at: datetime
    approved_by: str
    status_stamp: str = "Tutor-approved"
    source_appendix: list[SourceAppendixEntry] = Field(default_factory=list)
    content_hash: str = ""


# -------------------------------------------------------------- gate decision


class GateDecision(Base):
    permit: bool
    reason: Optional[str] = None
    blocked_status: Optional[RecordStatus] = None


class ValidationReport(Base):
    """Output of Gate 2 (component F)."""

    passed: bool
    removed: list[dict] = Field(default_factory=list)
    readability: Readability = Field(default_factory=Readability)
    missing: list[str] = Field(default_factory=list)
    hard_failures: list[str] = Field(default_factory=list)
