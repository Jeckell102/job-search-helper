# Independent QA — Sprint 4 owner-external native dependency repair

Date: 2026-11-20

## Pins and S4-only verification

- Source `owner_external_company_intake.py`: `c053591c38e27e36b564a953da4835cefd1d5bd0aff4a23b0db12caff4d8607e` — verified.
- Test `test_owner_external_company_intake.py`: `6aa4f6c2a5bcd8681e77a36f3cc79efd213d6b98bd5ce23931ccf2dd25ea6cc5` — verified.

The test was run against an isolated S4-only repository source tree explicitly lacking `job_search_helper.runtime_mapping_facts`:

```text
env PYTHONPATH=/tmp/jsh-s4-owner-external-native-deps.BPS2oLQK:/tmp/jsh-s4-manual-intake-v2.8WVknvUm:/tmp/job-search-helper-m3-baseline-a5aa02e/src:/tmp/job-search-helper-current-overlay/tests python3 -m pytest -q test_owner_external_company_intake.py
# 24 passed in 2.12s
```

## Findings

- The failed Sprint 5-only `runtime_mapping_facts` import is gone. Dependencies are the existing S4 repository/sheet-profile/SQLite APIs and the preserved v2 read-only scope helpers; no unstaged Sprint 5 module is imported.
- `open_jobs_for_external_intake` now captures the canonical named Jobs file device/inode before opening SQLite, identifies the descriptor newly held for that exact physical file, and binds the managed connection, descriptor, `PRAGMA database_list`, `/proc/self/fd` target, and current path identity.
- The replacement test renames the named Jobs file and creates a replacement after open. Even when the caller supplies the replacement device/inode in scope, preparation holds before any Sheets read because the still-open SQLite descriptor cannot be relabeled.
- Static inspection finds no Google mutation route: no `batchUpdate`, developer metadata, append, remote commit, or remote `_execute` call. The only write in the helper is the local, private, fsynced absence proof; local SQLite import remains required and transactional after read-only remote verification.
- Existing exact scope, owner/preproof/postproof, native table/header, literal unique row, source drift, local collision, rollback, and replay tests remain green.

## Verdict

**ACCEPT for the prior narrow, genuine owner-created, read-only external-row import.** The native dependency repair resolves the prior pre-operation import blocker and adds the required descriptor-replacement hold. It does not authorize a Sheets append, automation, scheduling, or broader intake activation.

No production, credentials, live Sheets service, or network access was used.
