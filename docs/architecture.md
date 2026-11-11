# Architecture notes

Companion to the Solution Design Report. This file records what the *code* does and
where the design was changed by implementation evidence. The report holds the full
rationale, the requirements baseline and the traceability matrix.

## Reference architecture

Canonical Architecture **(1) Document Intelligence**, with the governed history store
borrowed from **(2) Knowledge Intelligence** as component `D2`.

| Canonical element | Realized as |
|---|---|
| API ingestion — registers source documents | `services/intake.py` — a lesson note is the source document |
| Document Store | `D1` lessons, immutable after registration (SQLite trigger) |
| GenAI Extraction — source-linked candidates | `services/extraction.py` + `gateway/` |
| Fact Store — candidates kept distinct from validated information | `D3` and `D2`, separate tables, separate repositories |
| Human Review Workbench | `services/review.py` + the server-rendered UI in `api.py` |
| GenAI Report Service | `services/composition.py` (draft) and `services/export.py` (artifact) |
| Authorized Reviewer — authority outside the pipeline | the tutor; enforced by Gate 3 and the absence of any transmission capability |

## Architectural pattern

**Layered**, deployed as a **single-process client–server** application. The pipeline is a
sequenced orchestration inside the application layer, with each stage committing its own
state — which is what makes a failed run resumable rather than lost.

| Layer | Contains |
|---|---|
| Presentation | `api.py` UI routes, `templates/`, the export download |
| Application | `services/` (A–H), `gateway/` (I), `services/orchestrator.py` |
| Information | `store.py` — D1–D6 |

Event-driven was rejected for the prototype: eventual consistency conflicts with the
"one record, one state" invariant that the review step depends on. Every status
transition is already an event in all but name, so the move is available later.

## The three gates

| Gate | Component | Refuses when | Resulting state |
|---|---|---|---|
| **1 — Access & consent** | `services/guard.py` | a minor has no active guardian consent | `Blocked-ConsentRequired` |
| **2 — Grounding & readability** | `services/validator.py` | too little of the draft is supported by the note | `Blocked-InsufficientEvidence` |
| **3 — Tutor approval** | `services/review.py` → `services/export.py` | any candidate is still open | stays `UnderReview` |

Gate 1 runs **before the first model call**, so a consent-blocked record produces zero
outbound requests — measured, not asserted (`test_minor_without_consent_produces_zero_outbound_calls`).

## Invariants the state model enforces

- **I-1** — a record not `Approved`/`Exported` has no export path. This is FR-07 as a
  precondition, in `states.EXPORTABLE`.
- **I-2** — only the `Approved → Exported` transition writes to `D2`, so an unapproved
  item can never enter a later recurrence count.
- **I-3** — `Corrected → Approved` is refused while any candidate is open, so approval
  means the tutor saw every candidate.
- **I-4** — every transition, including every block, writes one audit event, so a run
  replays without re-invoking a model.

## Controls that run on every commit

`tests/test_architecture.py` is the allowed-interaction matrix expressed as code:

- only `gateway/anthropic_adapter.py` may import an HTTP client (**C-06**);
- no module anywhere may import an email, messaging or webhook library (**C-16**);
- only `services/export.py` calls `validated.promote` (**C-19**);
- `AuditRepo` exposes exactly `append`, `for_record`, `all` — no update, no delete (**C-09**);
- every state declares where it can go, including nowhere.

Each of these has a companion test proving the rule can actually fail on a seeded
violation. A control that cannot fail is not a control.

## Changes forced by implementation

Recorded as the Final Project brief requires: what changed, why, and the effect.

### 1. Redaction was corrupting the identifiers the design depends on

**Found by:** `test_identifiers_are_not_mangled_by_redaction`, written after the grounding
gate began dropping statements that should have passed.

The gateway walked every value in the outbound payload and applied the contact-detail
patterns. The phone-number pattern matched UUIDs containing a long run of digits, so a
`finding_id` was silently rewritten to `[redacted-phone]` in transit. The composed blocks
then cited an identifier that no longer resolved, and Gate 2 removed them — a privacy
control quietly breaking a traceability control.

**Effect on the design.** Minimization is now a *text* operation: it applies only to a
declared set of text-bearing fields (`gateway/gateway.py: TEXT_FIELDS`), and the phone
pattern requires a separator or a leading `+`. The report's claim that "the gateway
substitutes aliases and strips contact details" is unchanged; what changed is that it no
longer touches anything that is not prose.

### 2. An absence of an error was being extracted as an error

**Found by:** the recurrence demonstration reporting *5 of last 5* where the fixtures
said four.

A tutor note reading "No ser and estar errors today, which is progress" produced a
`ser/estar` candidate, because the extractor matched the trigger phrase without regard to
negation. That inflates the recurrence count using a sentence in which the tutor said
something went **well** — precisely the distortion PR-1 exists to avoid.

**Effect on the design.** Sentences carrying a negation cue are skipped
(`gateway/stub.py: NEGATION_CUES`). This is a crude substitute for negation scope and is
recorded as a limitation: "he could *not* get X right" is now a false negative. It is one
of the clearest arguments for the live model path.

### 3. Blocks that restate the tutor's own input had nothing to cite

The topics line and the homework line repeat fields the tutor typed, so they had no
extracted item to point at and Gate 2 removed them as ungrounded — which pushed some runs
over the 40% removal floor and halted them.

**Effect on the design.** Three reserved citations exist — `tutor_level`, `tutor_topics`,
`tutor_homework` — meaning "grounded in the submission itself". The level block may cite
`tutor_level` **and nothing else**; citing anything else is still a hard failure, because
that is the model attempting to assess.

### 4. Non-recurring findings were described as patterns

The composer used "this keeps coming back" for every finding. A finding below the
threshold is now reported as something that came up, with its count, never as something
that repeats. Overstating a one-off would distort the signal the project exists to produce.

### 5. Approval from `UnderReview` failed for the wrong reason

An early approval attempt raised a state error rather than naming the open items. `approve`
now accepts `UnderReview` and fails with `UndispositionedItems`, which is the real reason.
It can never *succeed* from that state, because `UnderReview` means at least one candidate
is open — so invariant I-3 is unchanged.

### 6. The review screen could not reach approval

A recurrence finding is a candidate in its own right, so `_open_items` counted it — but the
workbench rendered findings as read-only text inside the error card and put disposition
controls only on the error. Three errors were decidable; the three findings derived from
them were not. C-19 then did exactly what it is supposed to do and refused approval, so
**"Approve and export" could never succeed from the browser at all**. The CLI demo was
unaffected because it dispositions the open-item list directly, which is precisely why the
gap survived every run of the demonstration path.

The fix gives each finding its own controls, and a finding whose category produced no error
gets a card of its own. Bundling it into the error's button was rejected: the tutor may well
accept that the error happened and reject the claim that it recurs, and recording a decision
the tutor did not make is the failure mode this whole design exists to prevent.

The deeper lesson is about where the test boundary sat. Every control was tested through the
service layer, so the invariant held in every test while the only surface that exercises
tutor authority could not satisfy it. Three P1 tests now drive the review screen over HTTP
and assert that the set of open items is a subset of the controls the page renders.

## Deployment

One local process, one encrypted SQLite file, loopback only, one outbound TLS destination
from the gateway. Learner data never leaves the machine except as alias-substituted text
sent to the model provider. `data/` and `exports/` are git-ignored.

The scaling path — tenancy boundary, job queue behind the GenAI stages, shared gateway
with per-tenant budgets — is in §7.11 of the Solution Design Report and is explicitly not
implemented here.
