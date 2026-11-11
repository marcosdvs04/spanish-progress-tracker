# Security and Privacy

This prototype handles notes a tutor writes about a student, so the security posture is part of
the architecture rather than an afterthought. What follows is what the code actually does, not an
aspiration.

## Reporting a vulnerability

Open a GitHub issue describing the problem and how to reproduce it. If the issue would expose
data by being public, say so in a one-line issue and the discussion can move elsewhere.

This is a course prototype with one maintainer; there is no SLA.

## What the prototype does

- **No real learner data is in this repository.** Every fixture and demonstration note is
  invented. A test (`test_no_fixture_contains_anything_resembling_real_learner_data`) fails the
  build if anything resembling a real email address, phone number or personal name appears in the
  fixtures.
- **Nothing is transmitted anywhere except to the model provider.** A dependency test
  (`test_no_component_can_transmit_anything_to_anyone`) fails if any module imports a mail,
  webhook or messaging client. There is no send button because there is no send capability.
- **Only the gateway may reach the network.** A lint rule fails the build if any module other
  than `gateway/anthropic_adapter.py` imports an HTTP client.
- **Outbound payloads are minimized.** Names, email addresses and phone numbers are replaced with
  an opaque student alias before anything leaves the trust boundary, and a test asserts the
  contact details are absent from the payload while the alias is present.
- **A minor's note never reaches a provider without recorded, unexpired guardian consent.** This
  is enforced as a precondition on the first model call, and the test asserts *zero* outbound
  calls rather than a redacted one.
- **The audit log is append-only.** SQLite triggers reject `UPDATE` and `DELETE`, and the audit
  repository exposes no method that could rewrite history.

## What it does not do

- **Encryption at rest is full-disk**, the documented fallback, not database-level encryption.
- **Provider-side retention is outside the boundary.** It is governed by the provider contract,
  not by this architecture.
- **Single-user assumptions are pervasive.** Several controls rely on the fact that one process
  serves one tutor. They would need re-implementing at a tenancy layer before any multi-tutor
  deployment, and that is not a configuration change.

## Secrets

No key is required to run or test anything in this repository; the default provider is a
deterministic local stub. If you supply an Anthropic key for the live adapter, put it in a local
`.env` (see `.env.example`). `.env` is gitignored. No key, token or credential is committed here.
