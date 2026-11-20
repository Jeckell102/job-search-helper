# F1 external reconciliation protected install — 2026-11-20

## Result

The independently accepted four-file F1 external-Company reconciliation patch
from sanitized commit `720c84e` was installed narrowly into
`/home/chris/job-search-helper_old`.

Before installation, every protected target byte matched parent checkpoint
`a940524`. Rollback copies are at
`/tmp/job-search-helper-protected-backup-f1-720c84e` and their hashes match the
parent checkpoint. After installation, every protected target hash matches
commit `720c84e`:

| File | Installed SHA-256 |
| --- | --- |
| `src/job_search_helper/sheets_sync.py` | `c25217362098132957d8fffc37a33e15b4e2a989b46db7a1d197abe2460f5bae` |
| `src/job_search_helper/sqlite_repository.py` | `db6d14838fb691733824a8c607acbf21a9069c8ebf19076d09ec5049244f8cee` |
| `tests/test_company_event_outbox.py` | `a124881e2beccede76c195e03d68e59d548af3c943516254a6fd29c698845995` |
| `tests/test_company_publication_controls.py` | `9b93b432cfffb03d10aa375584ad4b898386989da84e8338f453ea62be1f0a1d` |

Protected-runtime validation used the project virtual environment, disabled
external pytest plugins and bytecode/cache writes, and passed **140 tests**.

No service was installed, enabled, reloaded, or started. Both durable intake
gates remain off. No Google row, local database, request, cycle, receipt,
credential, lock, Jetson state, or raw job record was changed by this install.

## Remaining gate

F1 is not closed. It still requires a controlled live Google Sheets proof of
the installed version across both idle and busy runtime paths. The retained
Samtec route also remains gated by the user's exact historical-cycle
blast-radius confirmation.
