# Independent migration review — final source re-review

2026-11-19. **Recommendation: REJECT for SOURCE INSTALLATION ONLY.**

The latest candidate closes the remote guard, projection-order recovery, receipt-version, historical v1 acknowledgement, premature-cleanup, and final-snapshot findings reproduced during this review. One behavioral defect remains: the new public adoption command cannot recover an unchanged retry after the successor has already been committed. The installation package also needs a current, complete checksum manifest.

This supersedes the preceding review. It is a source-installation recommendation, not permission to migrate live records or publish to Google. The reviewer changed only disposable review files and this report/evidence. No protected source, production database, Google data, service, queue, lock, or Jetson state was changed. Nothing was installed.

## Reviewed revision

Candidate: `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/protected-exact-candidate-20261119/`

Tested copy: `/home/chris/Documents/Codex/2026-11-19/job-search-migration-review/work/final-source-review/`

The final tested snapshot contains **30 Python files**, captured at **2026-11-19 20:12:22.867921 UTC**. A fresh comparison at **20:13:31 UTC** found no changed or additional candidate Python files. The complete hashes are in `source-manifest.json`; the end-of-review comparison and package manifest findings are in `candidate-recheck.json`.

| File | SHA-256 |
| --- | --- |
| `inbox.py` | `795ed4c1a63e82c1cb8680221d441963ab57c6efad18705663fb026e5252239a` |
| `exact_legacy_migration_runner.py` | `4ae4f06268ccf13e89f5986a0bc0fb1d2a8dcd5c7ca37261641e7ae7b48b61d8` |
| `exact_cycle_receipt.py` | `e27d9d55619a36bb611fa4586be45d0b57c5cc037c9e8023c651acb7c95f5d40` |
| `exact_cycle_sync.py` | `2fd752d42adbb2be879ca1572228ccda28dd52cc2ff261ca727fd9fc0c70af1a` |
| `sheets_sync.py` | `07b5a998794d40c9cf8e9ba99d255f44012829a9914dc83a82aacc979da30c74` |

**The latest freeze snapshot patch is present and tested.** Findings from earlier snapshots below are explicitly marked closed; they are not residual findings against this revision.

## Remaining findings

### 1. P2 — public adoption retry fails after successor commit

Location: `exact_legacy_migration_runner.py:138-145`, calling `InventoryInbox.begin_exact_legacy_migration`; `inbox.py:405-430` performs legacy-plan checks before recognizing an existing completed migration.

Independent reproduction, `runner_probes.RunnerChecks.test_remaining_gap_wrapper_cannot_retry_after_successor_freeze`:

1. Save a synthetic three-operation legacy plan with completed local cursor `3`, then obtain approval pins through `preview_retained_legacy_migration`.
2. Call `adopt_retained_legacy_migration` with those pins. It returns `successor_state: REMOTE_PLAN_FROZEN`. The successor, verified local marker, and immutable predecessor journal are durable.
3. Call the same public function again with the same database paths, cycle, Company, and identical approval pins. No local values, inventory, or approval data change.
4. The second call raises **`ValueError: Exact legacy retained evidence changed before migration.`** The diagnostic asserts this exact exception.

The retry reads the predecessor from the migration journal, but `begin_exact_legacy_migration` reads the successor from `sync_plans` and compares it to the predecessor digest before reaching its retry handling. The existing exact-local marker would also conflict with the first-adoption checks.

This is the same recovery boundary as a crash after the atomic successor commit but before the command returns its result. Calling the lower-level freeze method again succeeds; retrying the exposed adoption command does not. The tested failure preserves `REMOTE_PLAN_FROZEN` and creates zero receipts. It is a safe refusal, not demonstrated data loss or duplicate execution, but leaves the requested public idempotent recovery incomplete.

**Required fix:** recognize an existing migration before first-adoption-only checks. For the completed state, compare the exact immutable approval, predecessor, successor, cursor, local application and inbox mirror, then return a verified recovered result without replay, resealing, a new receipt, or another successor. Altered retries must still refuse. Add public-command tests for interruption after successor commit, ordinary unchanged retry, and changed binding/plan/mirror/local evidence.

### 2. Installation packaging gate — checksum manifest is stale and incomplete

At the final comparison, `SHA256SUMS` lists 27 files; ten listed hashes do not match the candidate. Three Python files are absent from the manifest:

- `src/job_search_helper/exact_legacy_migration.py`
- `src/job_search_helper/exact_legacy_migration_runner.py`
- `tests/test_exact_legacy_migration.py`

The package README says installation copies only listed files. Its current manifest would either stop a hash-enforcing install or omit the migration modules. This is a packaging defect, independent of the runtime test results. Regenerate the complete manifest only after freezing the repaired revision, update its installation inventory, and verify a disposable reconstruction from that manifest before source installation.

## Requested full-row reproduction and latest fix

The earlier failing probe changed **`Job History` → `Review Notes`** on synthetic identity **`Job Key: job-1`** to **`changed after local adoption`**. The sequence was:

`begin → local adoption → mark LOCAL_COMPLETE → edit Review Notes → freeze successor`.

Before the latest patch, `freeze_exact_legacy_successor` returned `REMOTE_PLAN_FROZEN` with no exception. Its application lookup revalidated selected identities/guards, but did not recheck the approved complete row snapshot. This did not demonstrate an overwrite of Review Notes; it demonstrated promotion after the approved full-row evidence had changed.

**Closed in the final tested snapshot:** `inbox.py:544-548` now compares the complete current snapshot with the approved digest, and lines 575-578 check it again before promotion. The same edit now raises **`ValueError: Exact legacy successor snapshot changed before freeze.`** The test asserts that the original legacy plan/cursor remain and the migration remains `LOCAL_COMPLETE`.

## Other findings now closed

| Boundary | Independent final result |
| --- | --- |
| Remote guards, blank/nonblank mismatch | Refused before chunk advancement, including after reopening both databases. Receipt remains pending, remote cursor remains zero, and no write succeeds. |
| Matching blank/nonblank guards | Genuine synthetic remote reads confirm and acknowledge successfully. Guard-only Review Status stays dirty; selected Last Checked clears; local Decision stays unchanged. |
| Normal v2 receipt derivation | Shared derivation retains fingerprint version 2. Its records equal the sealed remote records; normal receipt confirmation succeeds. |
| Historical v1 confirmed receipt | The actual previous reader produces the old acknowledgement from genuine synthetic remote rows. After restart, the candidate finishes acknowledgement with the **identical acknowledgement ID**. Guard checks remain active. |
| Fresh/default v1 evidence | Historical record fingerprints and saved-plan validation remain compatible; pending receipt restart completes confirmation and acknowledgement. |
| Projection ordering | Company-first legacy order reaches exact Sheets planning and public existing-plan recovery without changing local operation order. |
| Complete snapshot and protected fields | Prior-binding Review Notes drift, expected-only Source Hash drift, between-read Decision changes, inactive Company, foreign ownership, and changed local guard on restart all refuse. |
| Premature cleanup/discard/block | Cleanup refuses at `FROZEN` and `LOCAL_COMPLETE`; no archive is created. Discard and inventory block refuse while the migration owns the work. |
| Terminal archive | After valid publication, durable confirmation, local acknowledgement and the inbox acknowledgement marker, terminal cleanup preserves the migration archive. This test uses the normal corrected receipt derivation. |

The Davidson-shaped projection remains **19 local operations / 10 remote operations / 9 local-only evidence operations**, with exactly two protected conflicts and unchanged planning inputs. This is synthetic verification, not a fresh production assessment.

## Adoption interruption and no-replay evidence

The independent checks reopen the durable stores after journal creation, local application, local-complete marking, and successor freeze. Lower-level unchanged retries preserve one predecessor/successor pair, one local application chunk, unchanged records and dirty fields, and zero publication receipts, remote plans, or remote chunks during adoption. Local operation execution is patched to raise if replay is attempted.

Injected SQLite failures before the local chunk insert and before the inbox local-marker insert roll back the corresponding transactions. Reopening and retrying succeeds without a partial local parent or a replaced predecessor left behind. The new public wrapper also recovers an interruption after local application and before inbox completion without replay. Its final post-successor retry is the remaining finding above.

## Validation and reproducible evidence

**243 supplied/focused/adjacent tests passed**, warnings treated as errors, in 36.116 seconds. **29 independent checks passed**, warnings treated as errors, in 7.319 seconds. Of the 29, one deliberately asserts the remaining public-wrapper failure; its passing diagnostic is not acceptance of that behavior.

The initial expanded run in a new review directory lacked two title-list fixture files. Those review-harness omissions were restored from the prior sanitized copy before the final successful run. They are not reported as candidate defects.

Evidence beside the requested report: `HIGH_MODEL_MIGRATION_REVIEW_EVIDENCE/final-source-review/`. It contains the four independent probe files, final logs, complete source manifest, candidate/package recheck, the prior report, and preserved earlier diagnostics. The complete runnable source/test copy is the tested-copy path above. Tests use disposable SQLite files and memory repositories; no real Google client performs network requests.

Run from the tested copy:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -v reviewer_probes adoption_probes.AdoptionChecks compatibility_probes.CompatibilityChecks runner_probes
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -q test_exact_legacy_migration test_exact_local_plan test_exact_cycle_planner test_sheets_sync_exact_scope test_exact_cycle_sync test_exact_cycle_recovery test_exact_recovery_terminal test_publication_receipts test_durable_inbox test_exact_recovery_pause test_exact_recovery_pause_apply test_exact_recovery_pause_executor test_runner_cycles test_run_scoped_sync
```

Repair the public post-successor retry, freeze and reseal the complete package, and rerun that regression plus the existing protections before requesting source-installation acceptance. Live migration and Google publication remain separate gates.
