# Independent senior migration review — second re-review

Date: 2026-11-19. **Recommendation: REJECT the assembled migration for installation or operational use.**

The requested remote guard, complete-snapshot, ownership, and local guard repairs pass the independent checks below. The original false-confirmation finding is closed for the tested revision. A concrete restart compatibility defect remains: the normal existing-plan recovery path rejects a migrated plan with the corrected remote ordering. Complete durable legacy adoption also remains an acceptance gate.

This report supersedes the preceding review. No protected checkout, production database, Google Sheet, service, queue, lock, or Jetson was changed by this reviewer. Tests used synthetic memory repositories and disposable SQLite databases only. Nothing was installed or published.

## Exact review boundary

I reread the coordinator status and captured a coherent source/test snapshot at **2026-11-19 19:51:54 UTC**. All 29 candidate Python files matched the disposable copy.

Candidate: `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/protected-exact-candidate-20261119/`

Tested copy: `/home/chris/Documents/Codex/2026-11-19/job-search-migration-review/work/second-rereview/`

| Tested file | SHA-256 |
| --- | --- |
| `exact_legacy_migration.py` | `7025c993034409d58a3ba777970941039d6e85b9177a58d3baae70b6f57d8379` |
| `exact_local_plan.py` | `e449720770e5c3f8f26e69890776c225235024a0649c86cdbc6bc55c4e75981e` |
| `sheets_sync.py` | `a74d5c350e1fa9b1304bfa9ecf4e8a969af98a44653268d1cd99ceb120fbabd6` |
| `publication_receipts.py` | `a03241a80bae133fc7b528661c97197371e4b3ea14a4e92b295f37a0338a9d8a` |
| `exact_cycle_planner.py` | `2ac33c0e02509eed8ddb9f68cf3953f01b46360918208d5a68ec43e2b18fee21` |
| `test_exact_legacy_migration.py` | `e6b4c1c80f8d07ed15ee91566e796ecac133cae5526cdb96c06ccef303c146a0` |

**Concurrent changes:** nine files changed after capture, including fingerprint-version handling and a new `adopt_verified_legacy_local_plan` helper. I inspected those diffs but did not include them in the runtime results. They are a later, unreviewed extension. The inspected later planner diff still contained the ordering comparison identified below. Acceptance must refer to a frozen complete revision, not combine tests from this snapshot with later code.

## Prior findings: closed versus open

| Prior finding | Fresh result |
| --- | --- |
| Blank remote guard falsely confirms after a rejected write | **Closed for tested revision.** After both databases are reopened, retry refuses; chunk remains `PENDING`, receipt remains `SYNC_PENDING`, remote cursor remains zero, and zero remote writes succeed. |
| Nonblank mismatch advances a chunk | **Closed.** Same hold behavior as the blank mismatch. Final confirmation also refuses because the remote journal remains incomplete. |
| Matching nonblank guard cannot confirm | **Closed.** Matching blank and matching nonblank cases both complete genuine readback, confirmation, and local acknowledgement. |
| Guard fields accidentally acknowledged as mutations | **Closed for tested cases.** Review Status remains dirty, Last Checked is acknowledged, and local-only Decision remains unchanged. |
| Local restart ignores changed Decision | **Closed.** Reopened SQLite refuses the frozen-guard mismatch without replay. |
| Expected-only Source Hash / between-read Decision drift escapes verification | **Closed.** Both refuse. |
| Unmentioned full-row drift produces identical evidence | **Closed at planning boundary.** A Review Notes change rejects the prior binding. Freshly previewed evidence has a different complete snapshot digest and plan. |
| Inactive local Company / foreign Company label accepted | **Closed for tested cases.** Local control and operation ownership mismatches refuse. |
| Company-first legacy order cannot reach publication planning | **Partially closed.** Exact Sheets planning now succeeds while local order is preserved; normal existing-plan recovery still refuses. |
| Complete durable legacy adoption absent | **Still an operational gate.** Absent from the tested snapshot. The later local adopter helper and complete cross-database lifecycle have not received independent runtime acceptance. |

Remote checks use actual reads from a synthetic remote repository, not fabricated readback dictionaries. `sheets_sync.py:778-799` requires and compares guard-only remote values before chunk advancement, returns them separately as `remote_guards`, and includes them in receipt fingerprints. They remain outside the mutation/dirty-acknowledgement fields. Missing evidence is no longer treated as an observed blank.

## Critical findings and required fixes

### 1. P1 — normal recovery rejects the corrected remote ordering

In the tested snapshot, `exact_legacy_migration.py:241-247` sorts the remote projection by exact Sheets tab/row order while preserving local legacy order. However, `exact_cycle_planner.py:367-369` reconstructs the projection directly from the local operation list and requires positional equality with that remote stream. The normal recovery branch invokes this validator at lines 625-629.

**Independent reproduction:** build a Company-first legacy plan. Its local stream remains Company-first and its remote stream starts with Job History. `plan_exact_scope` now accepts it. Save the candidate in a disposable inbox, create its matching unfinished cycle, and call the public `freeze_exact_cycle_plans` recovery entry point. It returns no planned/recovered companies and this hold:

```json
{"company_id":"COMP-0035","reason":"existing_exact_plan_v2_projection_invalid"}
```

The direct existing-plan validator fails identically. This is a safe refusal, not an overwrite, but blocks ordinary recovery of the repaired migration. Passing only the exact Sheets planner is insufficient.

**Required fix:** give migration creation and all existing-plan validators one consistent projection contract that permits a separately sealed remote order while retaining the complete local stream. Preserve exact keyed-operation, identity uniqueness, field, guard, and digest validation; do not remove semantic local-to-remote equality. Use a shared deterministic rule or retained ordering evidence rather than silently regenerating an approved plan after row movement. The public recovery regression must return `recovered` without changing the saved plan, digest, or cursor.

### 2. Readiness blocker — complete durable adoption remains unproved

The tested builder/preview are intentionally pure functions. Their binding now includes workbook, inventory/plan/cursor/count, full snapshot, selected-field readback, approved conflicts, protected guards, and publication profile/schema. Those pins are not an authoritative inbox compare-and-swap or a durable migration journal.

The temporary inbox test still correctly rejects replacing a retained completed legacy plan through `save_exact_plan`: `Exact v2 plan conflicts with existing frozen evidence`. The original plan/cursor remain and no receipt is created. Do not weaken that refusal or discard the old plan to bypass it.

The later local-only adoption helper requires separate review. A local verified application alone cannot settle ownership of the retained inbox plan, preserve its immutable predecessor, verify its actual blocked state, or recover a crash between the two databases. The builder's `inventory_blocked: false` is a required binding assertion, not a live inbox read.

**Required gate:** freshly load and CAS-bind the exact workbook/cycle/Company, retained legacy payload/digests/cursor/count, actual inventory blocked state, approved snapshot/conflicts, and controls. Durably preserve the original artifact and transition journal before replacing/linking a successor. Adopt existing rows without re-executing the 19 operations, keep remote delivery unconfirmed, and prove idempotent recovery of every partial cross-database step. No cursor reinterpretation, cleanup, automatic publication, or discard/recreate workaround is acceptable.

### 3. Required follow-up — fingerprint-version compatibility

The tested snapshot adds guard-only values to fingerprints globally; older immutable plans/receipts used the earlier definition. The later explicit version-handling changes address the appropriate boundary but were not part of this runtime review.

Test historical and newly migrated artifacts through local validation, chunk verification, receipt derivation, remote confirmation, acknowledgement, and terminal recovery. Carry the fingerprint version through every authoritative boundary. Preserve old evidence rather than silently recomputing or resealing it.

## Exact evidence and projection verified

A synthetic Davidson-shaped case produces **19 local operations, 10 remote operations, and exactly two protected conflicts**. The remote stream has one Company and nine Job History operations; all nine Job Evidence operations stay local. The changed rows contain no obsolete Review Status/Decision mutations. Review Status becomes a remote expected guard; Decision stays local-only. Planning leaves input rows, legacy plan, and inventory payload unchanged.

Every header in the selected local schema is included in the full snapshot. A changed Review Notes value rejects the prior binding, the double read detects an injected review edit, and approved conflict/current-guard evidence is bound. This accepts the planning checks, not any fresh production snapshot.

Davidson's real 19/19 cursor, two conflict identities, and earlier complete-record digest remain historical coordinator evidence from `DAVIDSON_LOCAL_MIGRATION_ASSESSMENT_20261119.md`. I did not open production records. A completed local cursor still does not prove Google publication.

## Tests and evidence reviewed

**157 supplied/focused/adjacent tests passed**, with warnings treated as errors. This is the selection independently executed here, not a reproduction of the coordinator's separately reported 160-test selection.

**14 independent checks passed:** 12 verify repairs or correct nominal behavior; two deliberately demonstrate the remaining recovery-ordering and legacy-adoption holds. Passing those diagnostic hold tests is not acceptance of the gaps.

The independent tests cover all four blank/nonblank matching/mismatching remote guard combinations, database reopen, one-attempt retry, chunk/cursor/receipt state, protected values and acknowledgement scope, full-row drift, Source Hash, between-read edits, ownership, controls, local restart, 19/10/9 projection, and public planner recovery.

Evidence: `HIGH_MODEL_MIGRATION_REVIEW_EVIDENCE/second-rereview/` beside this report contains `reviewer_probes.py`, `reviewer-probes.log`, `supplied-tests.log`, `source-manifest.json`, and the prior report as `prior-review.md`. The complete tested copy is the absolute path given above. Supporting source/tests came from the sanitized reconciliation copy plus the candidate overlay; no live records or credentials were copied.

Run only from that disposable tested copy:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error reviewer_probes.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -q test_exact_legacy_migration test_exact_local_plan test_exact_cycle_planner test_sheets_sync_exact_scope test_exact_cycle_sync test_exact_cycle_recovery test_exact_recovery_terminal test_publication_receipts test_durable_inbox
```

The existing interpreter was reused without installation. No real Google client performed network requests.

## Additional tests and safest next action

1. Make reordered-plan public recovery succeed unchanged. Cover opposite legacy orders, multiple Job History row IDs, duplicate identities, row movement, and immutable local/remote digests on restart.
2. Freeze the complete versioned/adoption package and interrupt every durability boundary. Cover unchanged versus altered retries, transaction/disk failure, blocked inventory, stale controls, changed approved conflicts, competing ownership, and cross-database partial progress. Assert no replay, lost predecessor, duplicate successor, premature confirmation, or cleanup.
3. Keep all four remote guard combinations as end-to-end regressions. Add missing/changed guards during already-confirmed chunk rereads and final acknowledgement.
4. Verify historical fingerprint-format compatibility through the complete lifecycle.
5. After independent source acceptance, prepare a bounded read-only compact preview of the exact ten remote operations, retaining all local evidence. Any operational migration or Google write remains a separate authorized action.

**Safest next action:** retain the legacy plan and evidence, repair the remaining recovery-validator ordering mismatch in isolation, and submit one frozen complete package containing the later fingerprint-version and adopter work. The remote guard repair passed and should remain. Davidson and the broad cycle stay held until durable adoption and operational gates are accepted.
