# F2/F3 release-admission protected-install evidence

Date: 2026-11-19

## Scope

This record covers only the five-file, sealed F2/F3 release-admission delta.
It does not authorize or record a scraper run, queue release, Google access,
job-data mutation, broad backlog processing, or automatic release.

## Source and independent reconstitution

- Package: `/tmp/jsh-f2f3-release-admission-source-package.tar.gz`
- Package SHA-256:
  `0f3f8c33c560fa1ef1f8b344d00ca04df6ff10d01a7555b2425a8c84d32d2864`
- Payload: exactly `integration_release.py`, `repair_retry.py`,
  `scan_request.py`, `test_integration_release.py`, and
  `test_repair_retry.py`, plus the package manifest.
- Independent QA overlaid the verified delta onto a disposable copy of the
  current protected source. All five manifest entries matched before and
  after the test run; imports resolved from the disposable copy.
- Independent test result:

  ```text
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests \
    /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q \
    tests/test_repair_retry.py tests/test_integration_release.py \
    tests/test_fresh_scan_request.py tests/test_scrape_outcome_producer.py \
    tests/test_local_pipeline.py
  65 passed in 24.05s
  ```

## Guarded installation

- Installer: `/tmp/install_f2_f3_release_admission.py`
- Installer SHA-256:
  `469a02db5c88fc826329ae34f3debb93f08dd1fe972b9f224b30144c40feaae1`
- Existing `.integration-install.lock` was acquired, never removed.
- The installer verified current protected hashes, made a per-file rollback
  copy, atomically replaced each file, and verified installed hashes.
- Receipt:
  `/tmp/jsh-f2-f3-release-20261119T194453Z-d03rx1s1/manifest.json`
- Receipt status: `INSTALLED_HASH_VERIFIED` for five files.

## Protected verification

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests \
  .venv/bin/python -m pytest -q \
  tests/test_repair_retry.py tests/test_integration_release.py \
  tests/test_fresh_scan_request.py tests/test_scrape_outcome_producer.py \
  tests/test_local_pipeline.py
65 passed in 14.37s
```

## Remaining acceptance work

The source proof confirms the intended admission behavior: only a matching
`COMPLETE` immutable release binding may create the bounded retry; missing,
mismatched, nonterminal, or rolled-back bindings retain the request before a
new cycle is created or a cursor is consumed. It does not prove the complete
retry lifecycle, stale-result precedence, real release/start/rollback races,
or the final guarded company-only live acceptance sequence. Those gates stay
open.
