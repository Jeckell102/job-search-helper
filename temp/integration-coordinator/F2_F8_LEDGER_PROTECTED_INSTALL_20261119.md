# F2/F8 coordinator lifecycle-ledger installation

Date: 2026-11-19

## Installed scope

The coordinator now durably records retry lifecycle facts using full release
binding provenance. It retains conflicting same-attempt facts for
reconciliation, surfaces `ROLLBACK_REQUIRED` without calling rollback, and
includes both new append-only tables in F8 retention counts. It does not
dispatch work, start workers, release code, access Google, or delete data.

## Independent evidence

- Source package:
  `/tmp/jsh-f2-f8-rebased-source-package.tar.gz`
- Package SHA-256:
  `eeeaecbda1202bb34491ced3dea7c5464795c2ec7fa63a872b31944a8334bd11`
- Independent target-overlay QA: 98 checks passed. It verified duplicate
  original repair-key retention, retained changed-pin conflicts as
  `RECONCILIATION_REQUIRED`, held-only `ROLLBACK_REQUIRED`, malformed-binding
  refusal before persistence, late-original safety, and F8 table accounting
  with `automatic_cleanup: false`.

## Guarded installation

- Actual target: `/home/chris/job-search-helper_old/dev/wrapper-coder/tools`
- Installer: `/tmp/install_f2_f8_coordinator_ledger.py`
- Installer SHA-256:
  `21cbc9c214fec81d18b54568ede3203e8d61a391bc7123d38e2146256064f2c4`
- Existing `repairs/deployment.lock` was acquired and retained. No active
  coordinator process was present at preflight.
- Rollback receipt:
  `/tmp/jsh-f2f8-ledger-20261119T204312Z-q38be4pi/manifest.json`
- Receipt result: `INSTALLED_HASH_VERIFIED` for five files.

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:/home/chris/job-search-helper_old/src \
  python3 -m unittest -v test_outcome_intake test_retry_lifecycle_ledger \
  test_coordinator_supervision test_host_supervision \
  test_coordinator_outcome_delivery test_retry_command_refresh \
  test_retry_investigation_refresh
Ran 98 tests in 12.540s
OK
```

## Remaining gate

The ledger is an observation and retention component. It does not close the
full retry lifecycle/live release gate, authorize automatic rollback or broad
processing, or replace guarded real-company acceptance.
