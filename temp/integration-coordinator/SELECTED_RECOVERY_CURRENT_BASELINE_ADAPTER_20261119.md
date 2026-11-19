# Current-baseline selected recovery adapter checkpoint — 2026-11-19

## Scope

This checkpoint is an isolated, source-only reconciliation candidate.  It does
not modify the protected checkout, SQLite data, Google Sheets, scraper,
controller, queue, locks, services, or Jetson.

## Compatibility decision

The earlier selected-recovery candidate cannot be copied over the protected
source tree.  Its historical versions of the coordinator, inbox, Sheets, and
exact-cycle modules would remove current delivery-evidence and observation
safeguards.  The reviewed package map is
`/tmp/jsh-selected-recovery-protected-package-plan-20261119.md` (SHA-256
`9e8fc9a6fc2a38a9465c7e2dc7f4ba4eae7b4c0412450ba9f5df6a63c8f80acb`).

## Implemented isolated merge

Working copy: `/tmp/jsh-selected-recovery-current-adapter`.

- Preserved the current protected `exact_local_plan.py` and added only a
  selected-recovery prefix adopter.
- Added the narrow recovered-chunk rule needed for a verified prefix shorter
  than the normal 100-operation chunk.  The rule is restricted to cursor zero
  of a plan carrying the exact selected-recovery version, cycle, Company,
  prefix cursor, and prefix digest.  Ordinary plans and later chunks still use
  the existing fixed bounded behavior.
- Reused the isolated selected-plan builder and external-authorization
  verifier as source material only.  The test verifier is explicitly hidden
  from test discovery and remains forbidden unless a caller explicitly permits
  it in a test.
- The old fake remote receipt remains test-only.  No Google/Sheets client or
  remote writer is included in this checkpoint.

## Verification

Command run against the isolated current-baseline source:

```text
PYTHONPATH=/tmp/jsh-selected-recovery-current-adapter/src \
  /home/chris/job-search-helper_old/.venv/bin/pytest -q \
  tests/test_selected_legacy_recovery.py \
  tests/test_selected_recovery_integration.py \
  tests/test_exact_local_plan.py
```

Result: **28 passed** in 4.16 seconds, with no warnings.

This covers Shield-style 1/1 and Saronic-style 67/208 prefix/suffix behavior,
foreign ownership, protected manual fields, signed authorization rejection,
crash/restart, and fake-remote receipt state behavior.  It does **not** prove
current inbox/receipt/Sheets integration, installation safety, real signer
availability, or live publication.

An initial broader run failed before assertions because the isolated source
copy omitted the repository's required `title-blacklist.txt` policy file.
After restoring that unchanged reference file to the isolated test copy, the
current receipt and durable-inbox regression set passed:

```text
74 passed in 7.37 seconds
```

Combined isolated evidence: **102 passing tests**.  This is still staged
source evidence only, not installation or live-publish acceptance.

## Additive current-inbox boundary

The isolated candidate now creates the dedicated
`exact_selected_legacy_recoveries` table from the current `InventoryInbox`
schema and adds a narrow `begin_selected_legacy_recovery` method.  Before it
can freeze a row, the method rechecks the unblocked retained inventory, exact
legacy source plan and cursor, workbook identity, sealed successor, verified
authorization pins, and absence of competing exact local, remote, chunk,
receipt, or all-complete migration ownership.  It creates no receipt, remote
intent, Google client, or remote write.

The existing fake-remote test fixture was also advanced to the new monotonic
selected-recovery state names so that it cannot normalize an obsolete
`LOCAL_COMPLETE` state.  A direct inbox test proves a valid signed candidate
creates only the `FROZEN` selected-recovery row and no exact local or remote
state.

Current combined staged command result: **103 passed in 11.39 seconds** across
selected recovery, local-plan, exact-cycle-sync, durable-inbox, and publication
receipt coverage.  Promotion into the ordinary v2 local state and the existing
real receipt/readback path remain unimplemented and must receive independent
QA before any protected installation.

## Next gate

Port the selected-recovery journal and successor-promotion adapter into a
fresh current-baseline candidate.  It must bind immutable authorization digest
to the existing exact receipt/intent flow, remain unreachable from normal
scrape/sync/retry paths, and receive independent staged QA before any protected
installation.
