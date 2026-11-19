# Read-only interrupted-cycle recovery status candidate

Updated: 2026-11-19. This candidate is based on the exact current protected
MuleLab engine and runner. It does not authorize a recovery pause, scrape,
Google write, lock deletion, or cycle replacement.

## Purpose

The existing guarded recovery command validates its cycle only while applying
hundreds of manual holds. This candidate adds a separate read-only status
command that proves the exact local/workbook cycle and scope before an owner
decides whether to apply recovery.

The report exposes the cycle ID, current status, scope count, stage counts,
number of Companies that would be paused, and stable SHA-256 digests of the
complete Company-ID and blocking-cycle sets. It does not print either private
list. It rejects a
missing, completed, ambiguous, status-mismatched, scope-mismatched or
membership-drifted cycle. It also refuses a nonterminal integration-release
journal.

It opens the saved-inventory database in SQLite read-only mode and counts every
inventory, sync plan and partially applied plan owned by any non-superseded
unfinished cycle. The status is eligible only when the named cycle is the sole
blocker and all saved-work counts are zero. Otherwise it requires publication
or explicit evidence reconciliation before any cycle pause.

The apply path calls the same complete assessment again while holding the
existing scraper/writer lock. The command never deletes a lock and never starts
a scrape.

## Production-baseline correction

An earlier isolated patch was mistakenly based on a narrower stale source copy.
It was installed under the integration lock only long enough to run protected
tests. Those tests immediately exposed that the copy lacked the production
runner's automatic FIRST PASS handoff/timing behavior and the production
engine's current screening/cooperative-fetch behavior. No scraper, Google
operation, or workbook change ran.

Both files were restored byte-for-byte from the new pre-install rollback copies:

```text
2b7c39ec0a117e9f1d71ce13858e9bcad0af8c9d61ca54a5604e5f76b5d01f0c  engine.py
178600cf76b5ba223780e563b37d05aa3e902c059890efc43776df99485d74fa  runner.py
```

The restored protected selection then passed 82/82 checks. The current
candidate was rebuilt from those exact restored files rather than from the
stale isolated application tree.

## Candidate evidence

```text
2412949030619a8d4b9c5d8b0bf8ad63f444fc54ea1b7930defd1e90d27f2cfd  candidate engine.py
ebe5d12caba37b56b2585ec268b7c27a8b9a279f909ab52f9c59e82f4074116e  candidate runner.py
664f7923019538dd7f345b528d8b7d019f69c67f482cd9e099e58b073a886839  candidate test_fresh_scan_request.py
f374090b479f3a134e004f6278592405cd2578c9ef348ed05f1fd6f8deb2f7a8  candidate test_runner_cycles.py
```

A disposable overlay of the exact protected source/tests plus only these four
candidate files passed 113/113 focused recovery, runner, release, local-pipeline,
Company-event and retry checks with resource warnings treated as errors. Four
apply-path tests prove the locked command refuses saved inventory, saved plans,
partially applied plans and multiple blockers before calling the mutating engine
operation, with cycle, workbook and inbox snapshots unchanged. A fifth test
makes the startup synchronizer introduce saved work and proves the full gate is
re-evaluated only after that synchronizer has stopped, refusing the pause before
the engine mutation. The pause and its follow-up publication do not overlap any
background synchronization worker.

An earlier raw local-database diagnostic counted 19 unfinished historical cycle
records and their retained work without applying the normal supersession
contract. The installed command is the authoritative contract calculation: it
reduces the current blocker set to the exact newest 800-Company cycle, while
still finding 47 saved inventories, eight saved plans and eight partially
applied plans for that blocker. It reports 767 queued/inventory Companies that
would otherwise be paused and refuses recovery because the saved work must be
published or explicitly reconciled first. No recovery apply is authorized.

## Installation and live read-only proof

Independent review first rejected a post-check synchronization race. The
corrected source stops startup synchronization before the shared full gate,
runs that gate immediately before the engine mutation, and starts a separate
publisher only after a successful pause. Independent re-review accepted the
corrected source.

Only `engine.py` and `runner.py` were installed under the existing
`.integration-install.lock`. Exact pre-install files are retained at
`/tmp/job-search-recovery-status-backup-20261119-OXgRwL`. Installed hashes match
the accepted candidate above, and the protected selection passed 113/113 with
resource warnings treated as errors.

The installed read-only command for `CYC-B639C6D864EC` returned
`changes_applied=false`, `eligible=false`, state
`SAVED_WORK_MUST_BE_PUBLISHED_OR_RECONCILED`, one active blocker, 47 saved
inventories, eight saved plans and eight partially applied plans. It started no
scrape and performed no recovery. Publication/reconciliation of that durable
work remains the next operational gate.
