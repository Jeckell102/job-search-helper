# F3 deployment preflight checkpoint

Status: source accepted. Production installation and operational QA pending.

## Material and provenance

- Accepted source candidate: `/tmp/jsh-f3-resume.ErTFRd`.
- Source-only rollback copy: `/tmp/jsh-f3-production-source-rollback.O6bjzo`.
  It holds the three launch files and the ten production Python modules that
  differ from the candidate. Its scoped manifest digest is
  `8a3c42b90063bf780733166cb8817c60e550c9da6b35c6475449b6fadc33862e`.
- Scope list: root `job-search-helper`, `job-search-scraper`, and
  `release_admission_bootstrap.py`, plus `cli.py`, `engine.py`,
  `exact_cycle_recovery.py`, `inbox.py`, `integration_release.py`,
  `launcher.py`, `local_pipeline.py`, `runner.py`, `scrape_first_pass.py`, and
  `sync_cli.py` under `src/job_search_helper/`. Tests and reports are backed up
  separately from this rollback copy.
- The other task's installed temporary-retry changes matched `37512dd` before
  taking the rollback copy. Verify the same equality for all eight files just
  before installation, and preserve the combined `engine.py` changes.

## Verified live service inventory

At the read-only preflight, `job-search-sync.service` was inactive and disabled.
`wrapper-development-host.service` and `jetson-assistant-bridge.service` were
active and both use the production virtual environment. The wrapper development
host imports production `job_search_helper.cli`. Include it in the maintenance
dependency assessment and ensure it cannot load mixed modules. The assistant
bridge is separate and read-only by design. Verify its dependency set before
deciding whether it needs a hold. No service was stopped or changed.

## Checks before a guarded installation

1. Reconfirm the exact candidate and production base digests, backup bytes and
   mode, active processes and file locks, state database path, backend, and
   queue controls. Verify that no other development task owns these files and
   preserve any concurrent edits that appeared after the base snapshot.
2. Reconfirm normal and retained intake, temporary retry, and unqualified
   release controls are held. Preserve the one Samtec request and the historical
   Saronic cycle. Use no real scraper start as a smoke test.
3. Establish a supervised maintenance hold with fail-closed restart behavior
   across the entire exact multi-file installation and rollback. The candidate's
   source release primitive deliberately excludes the root bootstrap and shell
   launchers. A maintenance operation must account for those files and prevent
   the old launcher from creating a mixed startup during or after an interrupted
   installation. Scraper quiescence and a successful per-file copy alone do not
   establish that boundary.
4. Prove interrupted installation and recovery of that exact maintenance
   operation on a disposable version-matched copy before using it on production.
   Adopt the accepted source narrowly. Verify source, entrypoint mode, and
   expected lock behavior before lifting the maintenance hold.
5. Run read-only deployed verification and independent QA of the installed
   version. Keep existing policy holds until the relevant roadmap pilots and
   operational acceptance gates pass.

Restore only the exact prior source files from the rollback copy if a guarded
installation fails. Preserve existing user changes and mutable state. Retain
the maintenance hold until hashes and expected launcher behavior are verified.

## Disposable bootstrap hold test

`/tmp/test_jsh_f3_foundation_handoff.py` uses both saved bootstrap versions with a
synthetic worker and a synthetic nonterminal maintenance journal. It acquired
the scraper lock, durably wrote the journal, changed part of the fixture, and
killed the maintenance process. Each bootstrap rejected startup after the
lock was released by process death. After completing the fixture and clearing
the hold, the candidate bootstrap loaded the new worker. The test passed under
the production virtual environment's Python 3.11.18. System Python 3.10.12
cannot run the candidate launcher and is outside the project's documented
Python requirement. Installer and rollback replay, supervisor coverage, and
production route closure still require proof.

## Independent route inventory

The existing nonterminal release journal guards the normal public bootstrap,
normal runner startup, guarded retained fetch and named recovery, dispatcher
child admission, and release-bound retry delivery. The reviewer identified
separate routes to include in the durable maintenance hold: legacy applied
commands, direct sync publisher/import/control commands, direct legacy
pipeline entry, and review writeback. Quiesce existing processes that already
loaded affected modules, including the wrapper development host, and preserve
the disabled sync service. Depend on the bootstrap journal for documented
covered paths and use persistent maintenance controls for the remaining paths.
Prove this coverage with the exact 13-file installer and an external recovery
path in a fixture before production installation.
