# Protected MuleLab source installation — 2026-11-19

## Result

Installed the exact accepted source/test delta from sanitized checkpoint
`e4e19eff67bac54bd36638c665db6e57e61692db` into
`/home/chris/job-search-helper_old`.

The five modified target files matched baseline `c19c08b` byte-for-byte before
installation, and the five added files were absent. `git apply --check` passed
before the narrow ten-file patch was applied. After installation, every target
Git blob identity matched the accepted checkpoint exactly.

Rollback copies and the absent-file list are stored at:

`/tmp/job-search-helper-protected-backup-20261119-e4e19ef`

## Installed paths

- `src/job_search_helper/company_intake_dispatcher.py`
- `src/job_search_helper/retained_company_event.py`
- `src/job_search_helper/runner.py`
- `src/job_search_helper/scrape_first_pass.py`
- `src/job_search_helper/sync_cli.py`
- `tests/test_company_intake_dispatcher.py`
- `tests/test_company_intake_handoff.py`
- `tests/test_retained_company_event.py`
- `tests/test_retained_work_runner.py`
- `tests/test_sync_cli_lifecycle.py`

## Verification

The protected production-wrapper environment passed 160 strict adjacent tests
with warnings treated as errors and the optional pytest cache disabled.

Both normal and retained intake controls remain disabled by default. No service
was started or restarted; no Google, lock, live-state, credential, raw-job, or
Jetson file was changed.
