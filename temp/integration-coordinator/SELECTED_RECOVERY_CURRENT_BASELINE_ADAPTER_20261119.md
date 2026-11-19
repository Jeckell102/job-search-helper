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

## Next gate

Port the selected-recovery journal and successor-promotion adapter into a
fresh current-baseline candidate.  It must bind immutable authorization digest
to the existing exact receipt/intent flow, remain unreachable from normal
scrape/sync/retry paths, and receive independent staged QA before any protected
installation.
