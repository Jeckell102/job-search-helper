# Generic legacy-v2 recovery candidate QA hold — 2026-11-19

Scope: isolated candidate `/tmp/jsh-selected-legacy-recovery-j291Qp` only.
No protected source, local data, queue, lock, Google, scraper, service, or Git
state changed.

## Verdict: reject; do not install

The candidate's four new tests and 14 legacy regression tests passed, but
independent adversarial fixtures reproduced two release-blocking defects.

1. **Cross-company isolation:** the builder checks only prefix Job History
   ownership, allowing a foreign-company Job History suffix and a foreign Job
   Evidence prefix. A later commit could mutate or publish another company's
   records.
2. **Manual-field preservation:** suffix values were sealed without applying
   the existing Decision/Review Status reconciliation. In the isolated fixture,
   current `Keep` / `Human Reviewed` became legacy `Old` / `Pending`.

The journal/happy-path tests are not sufficient. Repair must enforce ownership
for every prefix and suffix operation (including evidence identity) and guard
manual fields across the entire converted plan. Add adversarial regression
tests before rerunning independent QA.
