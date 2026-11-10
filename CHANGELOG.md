# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
