---
name: Control gap
about: A control is specified but not enforceable, or enforceable but not reachable
title: ''
labels: control
assignees: ''
---

This template exists because the most serious defect found during implementation was of exactly
this shape: a control held in every service-layer test while the only screen that exercises tutor
authority could not satisfy it (§14 of the Solution Design Report).

**Which control**
<!-- C-nn, FR-nn, or invariant I-n. -->

**Where the gap is**
- [ ] Specified but nothing enforces it
- [ ] Enforced in a service but unreachable from the interface
- [ ] Enforced but no test would fail if it broke
- [ ] Enforced in a way that breaks another control

**What a test proving it would assert**
