# Generic legacy-v2 recovery candidate QA acceptance — 2026-11-19

Scope: repaired isolated candidate `/tmp/jsh-selected-legacy-recovery-j291Qp`
only. No protected source, job data, queue, lock, Google, scraper, service, or
Git state was changed.

## Verdict: accepted for its local-only primitive scope

- Candidate suite passed 7/7; legacy migration baseline passed 14/14.
- Foreign full-source-hash Job History suffix is rejected as
  `selected_legacy_job_ownership_mismatch`.
- Foreign Job Evidence prefix is rejected as
  `selected_legacy_evidence_ownership_mismatch`.
- Suffix legacy `Decision=Old` / `Review Status=Pending` are converted to exact
  current-value guards; the final manual state remains `Keep` / `Human
  Reviewed`.
- Restart evidence shows first prefix adoption is new, second is recovered, and
  only suffix chunks `[job-67 ×100, job-167 ×41]` execute: no prefix replay.
- Static review found no HTTP, Google, inbox, queue, lock, or publish calls;
  all tests used temporary SQLite fixtures.

## Still open

The accepted primitive intentionally lacks signer-bound authorization and exact
receipt/remote-intent/readback integration. It must not be installed or used
for real adoption/publishing until those separately reviewed gates are added.
