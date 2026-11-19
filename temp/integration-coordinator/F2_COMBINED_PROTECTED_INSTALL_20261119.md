# F2 combined retry-safety protected-install evidence

Date: 2026-11-19

## Scope

The installed delta closes two source-level gaps: a retry admitted under one
release must revalidate that exact `COMPLETE` release before every resume or
reconstruction; and retry outcomes/receipts must carry a canonical digest of
the complete source/dependency/config release binding. This is not a scraper
run, queue release, Google action, job-data change, or automatic rollback.

## Sealed source and independent QA

- Package: `/tmp/jsh-f2-combined-source-package.tar.gz`
- Package SHA-256:
  `ea2b2afc858e2422de10bd144495ff8a4f90ee9123c9f2901a492bee84235f7d`
- Scope: six source files and five tests, verified against the package
  manifest before test execution.
- Two independent disposable overlays proved imports resolved from the overlay,
  not the protected checkout. The exact combined suite passed 120 checks in
  each verification. The second review split those checks only for executor
  timing, preserving the same 120-test scope.
- Review verified that the resume guard fires before a fetch, write, local
  cycle rebuild, inbox acknowledgement, or cursor movement. Missing,
  mismatched, nonterminal, or rolled-back releases fail closed. The fixture
  changes seed the release journal now required by the guard; they do not
  relax behavior.

## Guarded installation and protected verification

- Installer: `/tmp/install_f2_combined_safety.py`
- Installer SHA-256:
  `191994f46981e72aba6bff00832e780579c26828559fa474e3ad20cbe10ec4a3`
- Existing `.integration-install.lock` was acquired and retained.
- The installer verified the package and all current protected preimages,
  saved each prior file, atomically copied each new file, and hash-verified the
  installed result.
- Rollback receipt:
  `/tmp/jsh-f2-combined-20261119T201236Z-n261z6ji/manifest.json`
- Receipt status: `INSTALLED_HASH_VERIFIED` for eleven files.

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests \
  .venv/bin/python -m pytest -q \
  tests/test_repair_retry.py tests/test_integration_release.py \
  tests/test_fresh_scan_request.py tests/test_local_pipeline.py \
  tests/test_durable_inbox.py tests/test_outcomes.py \
  tests/test_publication_receipts.py tests/test_scrape_outcome_producer.py
120 passed in 21.46s
```

## What remains open

This does not provide the coordinator-owned lifecycle ledger or an operator
visible rollback-required fact, nor does it prove stale-event reconciliation,
the full retry lifecycle, release/start/rollback races in production, or a
guarded real-company acceptance sequence. Those are still required before
automatic release or broad backlog processing.
