# AI Assistance Record

Required by the Final Project brief: *"Record material AI assistance, validation work,
rejected or revised outputs, and known limitations."*

GenAI (Claude) was used throughout implementation. I remain responsible for the code,
the design decisions, the validation and the submitted work. The boundaries below are
the ones set in §9 of the Solution Design Report, applied in practice — a system that
claims candidate-and-review discipline should be built with it.

## Where AI was used, and what I did with it

| Area | AI's role | What I did |
|---|---|---|
| Scaffolding, repository stubs, docstrings, fixtures | **Generated** | Read and accepted or rewrote. Failures here surface immediately and the suite catches them. |
| Pydantic models and the store layer | **Generated, then revised** | I moved `SourceRef` from optional to required so an ungrounded candidate cannot be *constructed*, not merely rejected. That is control C-08 and it belongs in the schema. |
| Prompt templates for extraction and composition | **Proposed** | Rewritten by hand and versioned into D5. Both carry explicit prohibitions — never infer an error from the absence of a mention, never state or revise the CEFR level. |
| The recurrence and trend rule (PR-1) | **Proposed candidates only** | Decided by me against real teaching experience and hand-computed on the five-lesson fixture before implementation. Counting lessons rather than mentions is a teaching judgement, not a coding one. |
| Gate logic, state transitions, consent evaluation | **Critique only** | Written by hand. I asked AI to find a bypass or an unhandled state; every finding was verified by a test before I acted on it. A plausible-looking gate that is subtly wrong is the worst failure available here. |
| P1 test assertions | **Not generated** | Written by hand. A test written by the same tool that wrote the code under test is not independent evidence, and P1 is where independence matters most. |
| Anything touching real learner data | **Never** | No real note, name, message or review was pasted into any tool at any point. |

## Candidates I rejected

| Proposed | Why I rejected it | What I did instead |
|---|---|---|
| Embedding similarity to detect recurring errors | A similarity threshold is neither explainable to a tutor nor reproducible in a test, and the corpus is ~30 records | Exact categorical matching on a canonical `pattern_key` |
| Let the model infer the CEFR level, tutor confirms | "Confirm" is where authority quietly transfers — an anchored suggestion is not an independent judgement | The level block may cite `tutor_level` and nothing else; an attempt hard-fails visibly |
| A "send to student" button gated on approval | A gated channel is still a channel, and it is the one that erodes first under convenience pressure | No channel at all; a CI rule fails the build if a transmission library appears |
| `httpx` imported directly in the composition service "for simplicity" | It would have dissolved the single-egress control on the first commit | The architecture test that forbids it was written *before* the adapter |
| Retry generation until the readability band passes | Unbounded retries hide a quality problem and burn the token budget | One regeneration, then flag to the tutor |
| Storing candidates and validated items in one table with a status column | A status column is a convention; two tables are a structure. The whole FR-12 guarantee rests on this | Separate tables, separate repositories, one writer |

## Where AI assistance actually mattered

Two defects I would likely have shipped:

1. **The redaction/identifier collision.** I asked for an adversarial read of the gateway
   against the grounding gate. The suggestion that a blanket scrub could rewrite
   identifiers led me to the UUID bug — a privacy control silently breaking a
   traceability control. See `docs/architecture.md` §1.
2. **Consent could be withdrawn between draft and approval** with nothing re-checking it.
   Surfaced by a prompted failure-path walkthrough, verified by reasoning through the
   state model, and fixed by evaluating consent at the point of consequence (PR-6).

Both now have regression tests.

## Known limitations

- **Extraction quality is unmeasured.** No labelled corpus of Spanish-learner errors
  exists for this workflow; extraction is validated against hand-built fixtures.
- **The stub cannot do negation scope.** It skips sentences containing a negation cue,
  so "he could not get X right" is a false negative.
- **The language-ratio measurement is a heuristic**, not a language identifier.
- **The readability thresholds are my professional judgement**, not a validated
  instrument. They are numeric so they can be argued with and tuned.
- **Careless approval remains possible.** The design makes review easy and skipping it
  hard, and records what happened, but it cannot make a tutor read.
- **Provider retention is outside the boundary**, governed by contract rather than by
  this architecture.
- **Single-user assumptions are pervasive.** Several controls rely on physical isolation.
