# Sprint 4 staged manual Company recovery

November 21, 2026. Root owns the staged manual Start route. This follow-up
exercises the existing ordinary Company publisher through the staged
bootstrap and runner with local SQLite and fixture provider and workbook
adapters. Production has not been updated for this change.

- A genuine Company 2 event waits behind an unfinished Company 1 cycle.
  It creates no second cycle and starts no broad scrape. After the first
  cycle closes, the next bare Start fetches only Company 2 once and records
  the verified-zero result without a workbook write.
- An interruption after inventory freeze leaves the exact Company cycle
  recoverable. Bare Start holds. The existing exact `publish` command can
  be repeated from the saved scope. The provider is fetched once and the
  one terminal outcome is preserved.
- A fixture workbook commits one job and loses the response. The initial
  bare Start prints `PUBLICATION_HELD`, the request digest and the cycle
  ID. The exact existing `publish` command confirms the first write from
  readback, without resending a write or refetching the provider. The local
  jobs and evidence tables contain one record each.

The first lost-response run failed because the old source did not emit
the request digest. The only correction adds the already frozen scope to
the result of the same exact publish call. The admission, publication
confirmation and recovery criteria are unchanged.
[Preserved failure](S4_NEXT_MANUAL_START_RECOVERY_FAILURE_20261121.md).

| Artifact | SHA-256 |
| --- | --- |
| `release_admission_bootstrap.py` | `9cafc1f6b283d77e769640134756df7e67d81702789ada5e5b2381f427cef152` |
| `src/job_search_helper/runner.py` | `4abc4fd6d7713294e0029fb770c3a5ffd57968569386ffaffd44f468cfcf2dd0` |
| `src/job_search_helper/manual_company_start.py` | `bb1e010e6e14d0e7fe1df1bc91d5f633d37ed726fcc2ce2ee074f2252f0f6c5e` |
| `test_manual_company_start.py` | `99f09ee5dc0f85b25f4fb21f2aafae30f5ccbcce4dee4643b0337bf101c52958` |
| `test_manual_busy_boundary.py` | `503e6d34bb1200383fc57dbb4ce6b1d50b04e405a671fbafabc70a5b80853448` |

Root ran ten focused cases, including the unchanged installed-source
routing reproducer. Independent QA reran the original failure and passed
nine corrected fixture cases. These are source-level regression results.
The live next-manual-run and deployed QA gates remain open. The native
two-tool builder update must keep its original exact predecessor files.
[Independent QA](S4_NEXT_MANUAL_START_RECOVERY_INDEPENDENT_20261121.md).
