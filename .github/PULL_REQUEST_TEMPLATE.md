## What this changes

<!-- One or two sentences. What is different after this, and why. -->

## Why

<!-- The problem or requirement this serves. Link the FR/NFR/control from the Solution Design
     Report where there is one — e.g. FR-12, C-19, I-3. -->

## Architecture checklist

The interaction matrix (§7.3) and the controls (§8) are enforced by tests, so these should be
answered rather than assumed:

- [ ] No module outside `gateway/` acquired an HTTP client, and no module acquired a mail,
      webhook or messaging client.
- [ ] Nothing outside `services/export.py` writes to the validated store.
- [ ] No new path lets an unapproved record produce an artifact.
- [ ] Candidate and validated information stayed in their separate stores.
- [ ] Any new candidate type is decidable from the review screen.

## Evidence

- [ ] `pytest` passes locally (69 tests, offline, no API key).
- [ ] A test was added that fails without this change.
- [ ] `docs/` updated if behaviour a reader relies on has changed.

## Notes for the reviewer

<!-- Anything you want looked at hardest, and anything you are unsure about. -->
