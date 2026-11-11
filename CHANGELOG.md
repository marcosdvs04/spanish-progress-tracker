# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] — 2026-11-11

### Fixed
- **The review screen could not reach approval.** A recurrence finding is a candidate and
  counts toward C-19, but the workbench rendered findings as read-only text inside the error
  card and placed disposition controls only on the error. Three errors were decidable; the
  three findings derived from them were not, so approval was refused permanently and the
  browser path could never reach `Approved` for any record. The CLI was unaffected because it
  dispositions the open-item list directly — which is why the gap survived the demonstration
  path. Each finding now carries its own controls, and a finding whose category produced no
  error gets a card of its own. Deliberately not bundled into the error's decision: a tutor may
  accept that the error occurred and reject the claim that it recurs.
  Regression tests: `test_every_open_candidate_has_a_control_on_the_review_screen`,
  `test_findings_are_decided_separately_from_the_errors_they_derive_from`,
  `test_the_browser_flow_can_reach_approval`.

### Added
- `spt prepare`: seeds the workbench database and stops at the review step, so the browser
  demonstration starts at the decision rather than at an empty database or an approved record.
- `PatternFinding.status`, read from the candidate row, so a finding's disposition state is
  visible on the review screen.
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, pull-request and issue templates, `.editorconfig`.

### Changed
- 69 tests (was 66). Collected counts: P1 20, P2 11, P3 9, P4 13, architecture 16.
- README screenshot regenerated against the corrected review screen.

## [1.0.0] — 2026-11-10

First complete prototype: the bounded end-to-end capability from the Solution Design Report.

### Added
- Components A–I and stores D1–D6, one module per component.
- Nine-state record model with three hard gates and four exception states.
- Deterministic recurrence and trend (PR-1) over approved history only.
- Grounding and readability gate with per-CEFR-level bands (PR-2, PR-3).
- Review workbench with four reviewer actions and one bounded revision cycle.
- Plain-text and PDF export, status-stamped, with a source appendix.
- LLM gateway with alias substitution, token budget, bounded retry and call logging;
  deterministic stub adapter and live Anthropic adapter behind one interface.
- 66 tests organized by validation priority, plus continuous architecture lint rules.
- `spt demo`: scripted end-to-end demonstration including both refusal paths.

### Fixed during implementation
- **Privacy redaction was corrupting identifiers.** The phone-number pattern matched
  UUIDs containing long digit runs, so citations were silently rewritten and the
  statements that depended on them were dropped by the grounding gate. Redaction is
  now applied only to text fields, and the pattern requires a separator or a `+`.
  Regression test: `test_identifiers_are_not_mangled_by_redaction`.
- **An absence of an error was being extracted as an error.** "No ser and estar errors
  today" produced a ser/estar candidate and inflated the recurrence count — the exact
  distortion PR-1 exists to avoid. Sentences carrying a negation cue are now skipped.
  Regression test: `test_an_absence_of_an_error_is_not_an_error`.
- **Non-recurring findings were described as patterns.** A finding below the threshold
  is now reported as something that came up, never as something that repeats.
- **Approval from `UnderReview` failed with a state error** rather than the real reason.
  It now reports the open items.
