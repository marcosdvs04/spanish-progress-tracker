"""Record state model (Solution Design Report §7.8, Figure 4).

One record, one state, at all times. A component declares the states it accepts
and the single state it produces; an out-of-state call is refused. The three
gates are the only transitions that change what the system may do next.
"""

from __future__ import annotations

from enum import Enum


class RecordStatus(str, Enum):
    REGISTERED = "Registered"
    EXTRACTED = "Extracted"
    PATTERNS_LINKED = "PatternsLinked"
    DRAFT_READY = "DraftReady"
    UNDER_REVIEW = "UnderReview"
    CORRECTED = "Corrected"
    APPROVED = "Approved"
    EXPORTED = "Exported"
    # Exception states
    BLOCKED_CONSENT = "Blocked-ConsentRequired"
    BLOCKED_INSUFFICIENT = "Blocked-InsufficientEvidence"
    BLOCKED_SERVICE = "Blocked-ServiceUnavailable"
    ABANDONED = "Abandoned"


#: Allowed transitions. Anything absent here is impossible by construction.
TRANSITIONS: dict[RecordStatus, set[RecordStatus]] = {
    RecordStatus.REGISTERED: {
        RecordStatus.EXTRACTED,
        RecordStatus.BLOCKED_CONSENT,
        RecordStatus.BLOCKED_SERVICE,
        RecordStatus.ABANDONED,
    },
    RecordStatus.EXTRACTED: {
        RecordStatus.PATTERNS_LINKED,
        RecordStatus.BLOCKED_SERVICE,
        RecordStatus.ABANDONED,
    },
    RecordStatus.PATTERNS_LINKED: {
        RecordStatus.DRAFT_READY,
        RecordStatus.BLOCKED_INSUFFICIENT,
        RecordStatus.BLOCKED_SERVICE,
        RecordStatus.ABANDONED,
    },
    RecordStatus.DRAFT_READY: {
        RecordStatus.UNDER_REVIEW,
        RecordStatus.ABANDONED,
    },
    RecordStatus.UNDER_REVIEW: {
        RecordStatus.CORRECTED,
        RecordStatus.DRAFT_READY,  # one bounded revision (PR-7)
        RecordStatus.ABANDONED,
    },
    RecordStatus.CORRECTED: {
        RecordStatus.APPROVED,
        RecordStatus.DRAFT_READY,  # one bounded revision (PR-7)
        RecordStatus.UNDER_REVIEW,
        RecordStatus.ABANDONED,
    },
    RecordStatus.APPROVED: {RecordStatus.EXPORTED},
    RecordStatus.EXPORTED: set(),
    # Blocked states return to the step that produced them, once the cause is cleared.
    RecordStatus.BLOCKED_CONSENT: {RecordStatus.REGISTERED, RecordStatus.ABANDONED},
    RecordStatus.BLOCKED_INSUFFICIENT: {RecordStatus.ABANDONED},
    RecordStatus.BLOCKED_SERVICE: {
        RecordStatus.REGISTERED,
        RecordStatus.EXTRACTED,
        RecordStatus.PATTERNS_LINKED,
        RecordStatus.ABANDONED,
    },
    RecordStatus.ABANDONED: set(),
}

#: Only these states may be exported. This single line is the whole of FR-07
#: expressed as a precondition (invariant I-1).
EXPORTABLE = {RecordStatus.APPROVED, RecordStatus.EXPORTED}


class StateError(RuntimeError):
    """Raised when a component is called with a record in a state it does not accept."""

    def __init__(self, current: RecordStatus, expected: object, action: str = "") -> None:
        self.current = current
        self.expected = expected
        super().__init__(
            f"record is {current.value}; {action or 'this action'} requires {expected}"
        )


def can_transition(src: RecordStatus, dst: RecordStatus) -> bool:
    return dst in TRANSITIONS.get(src, set())


def require(current: RecordStatus, allowed: set[RecordStatus], action: str) -> None:
    """Guard a component entry point. Raises StateError if the record is not ready."""
    if current not in allowed:
        raise StateError(current, sorted(s.value for s in allowed), action)


def assert_transition(src: RecordStatus, dst: RecordStatus) -> None:
    if not can_transition(src, dst):
        raise StateError(src, dst.value, "transition")
