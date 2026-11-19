# M2 terminal-safe Company event bridge installation

Date: 2026-11-19

## Purpose and boundary

During a running scrape, periodic intake now persists an external Company
change in the durable outbox. The terminal-safe bridge closes the intake while
the normal outer scraper lock is still held, performs the final Company-control
pull, and lets the existing bridge write a next-run request and receipt. It
does not select a new cycle, start a second scrape, overwrite a competing
request, access Google during installation, or enable broad processing.

## Source QA

- Patch: `/tmp/m2-midrun-event-repair.patch`
- Patch SHA-256:
  `10912e087098749a5282366c4bac6d94551a79a99052bdc46e70d4a41926b21a`
- Independent QA applied the patch to a disposable current-source copy. It
  changed exactly five files: `run_sync.py`, `runner.py`, and three focused
  test files.
- The expanded suite passed 73 checks. It covers the final pull, one current
  fetch/cycle, one durable next-run request and receipt, idempotent replay,
  and preservation of a competing request. The intentional terminal
  reconciliation raised one stale-sheet test's expected pulls from two to
  three; the test now documents startup, conflict replan, and terminal pull.

## Guarded protected installation

- Installer: `/tmp/install_m2_terminal_event_bridge.py`
- Installer SHA-256:
  `b735859f7bbe502b3f8b3850e68933932fb04b791344306b0a46d3652202e3fe`
- Existing `.integration-install.lock` was acquired and retained.
- Receipt:
  `/tmp/jsh-m2-terminal-bridge-20261119T203206Z-2qy6x41s/manifest.json`
- Result: `INSTALLED_HASH_VERIFIED` for five files.

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests \
  .venv/bin/python -m pytest -q \
  tests/test_run_scoped_sync.py tests/test_company_event_bridge.py \
  tests/test_company_event_outbox.py tests/test_stale_sheet_choices.py
73 passed in 6.59s
```

## Remaining M2 evidence

This source activation does not close Milestone 2. The project still requires
guarded live proof of idle and busy Company change intake, restart/duplicate
recovery, the normal company-only storage path, and final independent
end-to-end acceptance. Broad backlog processing and unqualified automatic
release remain disabled.
