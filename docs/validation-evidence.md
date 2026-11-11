# Validation Evidence

Generated 2026-11-11 from a clean checkout, offline, against the deterministic stub adapter — no API key and no network. Reproduce with `pytest -v` and `python -m progress_tracker.cli demo`.

**69 tests, all passing.** Organized by the validation priorities in §9 of the Solution Design Report.

## P1 — Authority  <sub>(7 tests)</sub>

These must never fail. One occurrence invalidates the solution however well everything else works.

- [x] export before approval is refused
- [x] approval refused while any item is open
- [x] a raised question still blocks approval
- [x] model asserted cefr level hard fails
- [x] tutor correction survives into the export
- [x] artifact carries status stamp and source appendix
- [x] draft is stamped as unreviewed before approval

## P1 — Review surface  <sub>(3 tests)</sub>

Tutor authority is exercised on exactly one screen. A candidate with no control on it
cannot be decided, which turns C-19 from a safeguard into a deadlock. Driven over HTTP.

- [x] every open candidate has a control on the review screen
- [x] findings are decided separately from the errors they derive from
- [x] the browser flow can reach approval

## P1 — Privacy  <sub>(10 tests)</sub>

Consent, minimization, isolation and the synthetic-data guarantee.

- [x] minor without consent produces zero outbound calls
- [x] consent granted then run proceeds
- [x] consent withdrawn between draft and approval blocks approval
- [x] expired consent does not count as consent
- [x] withdrawal never deletes the consent trail
- [x] contact details never leave the trust boundary
- [x] identifiers are not mangled by redaction
- [x] one students data never appears in anothers request
- [x] no fixture contains anything resembling real learner data
- [x] the denylist check actually catches a violation

## P2 — Grounding and traceability  <sub>(11 tests)</sub>

The difference between an assistant and a plausible-sounding liability.

- [x] five described errors are extracted with resolving spans
- [x] no error is invented that is not in the notes
- [x] an absence of an error is not an error
- [x] a candidate cannot be built without a source reference
- [x] a span that does not resolve is discarded before storage
- [x] an ungrounded statement is removed and logged
- [x] a sparse note halts instead of producing content
- [x] audit is append only and replays a whole run
- [x] the lesson note is immutable after registration
- [x] every exported statement resolves to a quote
- [x] a duplicate submission is refused

## P3 — Domain logic  <sub>(9 tests)</sub>

Recurrence, trend, and the candidate/validated boundary.

- [x] recurring error is reported as four of the last five
- [x] a one off in the same set is not flagged as recurring
- [x] an unvalidated candidate never affects a later count
- [x] unvalidated candidates are absent from history and exports
- [x] changing the window at runtime changes the result
- [x] trend needs enough history before it claims a direction
- [x] a correction survives a revision verbatim
- [x] only one revision is permitted
- [x] history endpoint returns validated material only

## P4 — Quality attributes  <sub>(13 tests)</sub>

Readability bands, latency, token budget, provider resilience.

- [x] every level band is met by the draft it produces[A1]
- [x] every level band is met by the draft it produces[A2]
- [x] every level band is met by the draft it produces[B1]
- [x] every level band is met by the draft it produces[B2]
- [x] every level band is met by the draft it produces[C1]
- [x] a1 and b2 drafts differ measurably
- [x] an over complex draft is caught
- [x] language detector behaves on clear cases
- [x] a run completes well inside the latency budget
- [x] token budget is enforced before anything is sent
- [x] rate limits retry then fail cleanly without losing data
- [x] a blocked service run is resumable
- [x] the whole suite runs against the stub with no network

## Architecture controls  <sub>(16 tests)</sub>

Lint rules that run on every commit, so the allowed-interaction matrix stays true of the code.

- [x] only the gateway may import an http client
- [x] no component can transmit anything to anyone
- [x] the lint rule catches a seeded violation
- [x] only the export service writes to the validated store
- [x] the audit repository exposes no way to rewrite history
- [x] every state has a defined set of transitions
- [x] exported is terminal and only approved can reach it
- [x] every component in the report exists as a module[intake]
- [x] every component in the report exists as a module[guard]
- [x] every component in the report exists as a module[extraction]
- [x] every component in the report exists as a module[patterns]
- [x] every component in the report exists as a module[composition]
- [x] every component in the report exists as a module[validator]
- [x] every component in the report exists as a module[review]
- [x] every component in the report exists as a module[export]
- [x] every component in the report exists as a module[orchestrator]

## End-to-end demonstration transcript

`python -m progress_tracker.cli demo` runs the whole bounded capability against synthetic data and prints every state transition. Verbatim output:

```text
------------------------------------------------------------------------
SPANISH PROGRESS TRACKER — end-to-end demonstration (synthetic data only)
model provider : stub/rule-based-v1
------------------------------------------------------------------------

[1] Seeding four approved lessons as the student's history
    2026-09-01  approved+exported  record de88f301
    2026-09-08  approved+exported  record e33cdbf0
    2026-09-15  approved+exported  record 2bd9cafc
    2026-09-22  approved+exported  record d87edd11

[2] New lesson arrives — the one under review
    registered ef8b3f9f  status=Registered
    pipeline finished  status=DraftReady

[3] Recurrence findings (deterministic, no model involved)
    RECURRING  grammar/ser-estar            4 of last 5  trend=improving
    one-off    grammar/prepositions         2 of last 5  trend=worsening
    one-off    grammar/object-pronouns      1 of last 5  trend=worsening

[4] Draft readability  mean sentence=5.57 words  spanish ratio=1.0  passed=True
    review status stamped on the draft: draft

[5] Export before approval must be refused
    refused: record is DraftReady; export requires an approved record (FR-07)

[6] Tutor opens the review and corrects one goal
    corrected goal -> Objetivo: usar 'estar' para estados temporales.

[7] Approval with items still open must be refused
    refused: 6 item(s) still need a decision

[8] Tutor dispositions every candidate, then approves
    open items remaining: 0
    approved; draft status is now 'tutor_approved'

[9] Export
    exports/demo/syn-b1-01_2026-09-29_ef8b3f9f.txt  sha256=02ef7f54396c1618...
    exports/demo/syn-b1-01_2026-09-29_ef8b3f9f.pdf  sha256=ce386b16634938cc...
    source appendix entries: 3

[10] Refusal path — a note with nothing specific in it
    status=Blocked-InsufficientEvidence
    needs: the note needs at least two specific errors: what the student said or wrote, and what was wrong with it

[11] Consent path — a minor with no guardian consent on file
    status=Blocked-ConsentRequired
    outbound model calls for this record: 0  (must be 0)

[12] Minimization — contact details never leave the trust boundary
    'jordan.fake@example-mail.com' present in outbound payload: False
    '555 010 9988' present in outbound payload: False

[13] Audit replay — the run reconstructed from the log, no model invoked
    2026-11-10 21:59:02.408516  A:intake       lesson.registered          ok
    2026-11-10 21:59:02.410909  B:guard        gate1.generate             ok
    2026-11-10 21:59:02.413413  I:gateway      model.extract              ok
    2026-11-10 21:59:02.423451  C:extraction   errors.extracted           ok
    2026-11-10 21:59:02.434560  D:patterns     patterns.computed          ok
    2026-11-10 21:59:02.437341  I:gateway      model.compose              ok
    2026-11-10 21:59:02.441494  E:composition  draft.composed             ok
    2026-11-10 21:59:02.446897  F:validator    gate2.checked              ok
    2026-11-10 21:59:02.451645  H:export       export.refused             blocked
    2026-11-10 21:59:02.456025  tutor          review.opened              ok
    2026-11-10 21:59:02.458928  tutor          review.correct             ok
    2026-11-10 21:59:02.464346  tutor          gate3.refused              blocked
    2026-11-10 21:59:02.469033  tutor          review.validate            ok
    2026-11-10 21:59:02.473062  tutor          review.validate            ok
    2026-11-10 21:59:02.477046  tutor          review.validate            ok
    2026-11-10 21:59:02.480985  tutor          review.validate            ok
    2026-11-10 21:59:02.484934  tutor          review.validate            ok
    2026-11-10 21:59:02.489140  tutor          review.validate            ok
    2026-11-10 21:59:02.496806  B:guard        gate1.generate             ok
    2026-11-10 21:59:02.503259  tutor          gate3.approved             ok
    2026-11-10 21:59:02.517396  H:export       export.written             ok
    2026-11-10 21:59:02.546477  H:export       export.written             ok

------------------------------------------------------------------------
Demonstration complete. Artifacts in ./exports/demo
------------------------------------------------------------------------
```

## Headline results

| Claim | Evidence |
|---|---|
| A recurring error is reported with its count and window | `ser/estar` — **4 of last 5 lessons**, trend `improving` |
| A one-off in the same set is not flagged | `object-pronouns` — 1 of last 5, `is_recurring=False` |
| An unapproved candidate never enters a later count | lesson analysed but never approved leaves the count at 4 |
| Export before approval is impossible | refused: *record is DraftReady; export requires an approved record* |
| Approval while a candidate is open is impossible | refused: *6 item(s) still need a decision* |
| A minor without consent reaches no model | **0** outbound gateway calls for that record |
| Contact details never leave the boundary | email and phone absent from the outbound payload; alias substituted |
| A sparse note refuses instead of inventing | halts in `Blocked-InsufficientEvidence` naming what is missing |
| A tutor correction reaches the student verbatim | corrected goal present in the exported artifact |
| A run replays from the audit log alone | 16 events, no model re-invoked |

## What this evidence does not show

**Extraction accuracy.** The stub is rule-based, so these results measure the pipeline and its controls, not a language model's judgement. Running the same fixtures against the live provider is the obvious next step and is not claimed here.

**Behaviour on real notes.** Every fixture is invented. The prototype has never been run on a real learner's record, by design.
