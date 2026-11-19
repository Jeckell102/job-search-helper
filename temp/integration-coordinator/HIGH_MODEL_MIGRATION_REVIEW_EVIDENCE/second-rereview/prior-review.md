# Independent senior review: Davidson legacy-to-v2 migration

Date: 2026-11-19. Recommendation: **REJECT for migration, installation, or publication.**

The planning helper preserves the two changed review fields in the nominal case and correctly keeps Job Evidence out of the compact remote projection. The revised local guard verification and guard-only fingerprinting close the original local restart and between-read drift reproductions. However, the remote readback does not carry the newly fingerprinted guard values: a blank guard can still falsely confirm after a rejected write, and a matching nonblank guard prevents successful confirmation. There is also no durable, compare-and-swap migration/adoption operation. Keep Davidson and the broad cycle held.

This was a source review with synthetic, disposable local tests. No production database, protected checkout, Google Sheet, service, lock, queue, or Jetson was changed. No live records or credentials were copied. The historical live counts and Davidson digests below come from the coordinator's assessment, not a fresh production inspection by this reviewer.

## Reviewed revision and evidence

The shared candidate changed during review. I incorporated its binding parameter, corrected fixtures, exact protected-field list, local guard revalidation, and the subsequent guard-only `record_fingerprints` change requested for re-review, then retested. Findings below supersede the first saved review. Earlier fixture, local-restart, expected-only Source Hash, and between-read Decision defects are not reported as unresolved.

**Late revision boundary:** during final delivery, `exact_legacy_migration.py` changed again to SHA-256 `108e63f632f281a71e3a3b5b9cf8310a1021a2fae316be9f72e709eb54b14d0f`. I inspected that diff. It adds full-row snapshot pins, workbook/profile/conflict bindings, local control and operation-ownership checks, and remote ordering. Those changes address the design of findings 2 and 4 and part of finding 3; those findings below are retained as evidence for the tested predecessor, not claimed as reproduced against this new planner. The 128-test and 12-probe results belong to the explicitly hashed snapshot below. The late planner has not received runtime acceptance here. The remote synchronizer and receipt hashes remained unchanged, so finding 1 and the missing durable-adopter boundary still prevent acceptance. Freeze and test the complete revised package before the next acceptance request.

Candidate directory:
`/tmp/job-search-helper-integration-automation/temp/integration-coordinator/protected-exact-candidate-20261119/`

Re-review source/test comparison at **2026-11-19 19:43:15 UTC**: all 29 candidate Python files matched the disposable review copy. Key SHA-256 hashes:

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/exact_legacy_migration.py` | `ba34d46e2b93bfa52b3470ee1633949691519385bf848382e6ff63d05ae8f7cc` |
| `src/job_search_helper/exact_local_plan.py` | `e449720770e5c3f8f26e69890776c225235024a0649c86cdbc6bc55c4e75981e` |
| `tests/test_exact_legacy_migration.py` | `b309d0b4e47f1ae9e9eba9603a83d4eacb6685651fad52d33de01f238caed895` |
| `src/job_search_helper/sheets_sync.py` | `29d3032915133a491c41233fec12b8fa76d6e70773c4d49815a93de67dee92ef` |
| `src/job_search_helper/publication_receipts.py` | `a03241a80bae133fc7b528661c97197371e4b3ea14a4e92b295f37a0338a9d8a` |

Reviewed the coordinator status first, then `DAVIDSON_LOCAL_MIGRATION_ASSESSMENT_20261119.md`, `DAVIDSON_LEGACY_PLAN_PREVIEW_20261119.md`, the protected-baseline reconciliation report, candidate README, the three requested files, and the relevant planner, inbox, receipt, synchronizer, SQLite, repository, and compact-profile implementation. Dependencies came from the existing sanitized source/tests copy at `/tmp/job-search-helper-protected-reconciliation-o8XL4Q`; the candidate overlay was applied only to my disposable copy.

The assessment identifies:

- Cycle `CYC-B639C6D864EC`, Company `COMP-0035`, legacy operation count/cursor `19/19`.
- Legacy plan digest `3c4883bd6b8c5e75e449e9e5f1bca6fe7f174c22e5c20c52aa06482d7e8f553c`.
- Inventory digest `4a807ce9ef52d5f68511b2eceaa7d96d7826110bb5e7d0b5b8cb6e0b7d07b7af`.
- Complete current-local-record digest `287eeb8ea22754ae3c49c47d0cd3b21204a151eca27927e280caccb283f4a634`.
- Exactly two permitted conflict identities: `1fcbce2fe62c6285edabaa47ab912195715143c8f126f373707d500b00879c99` and `3b2ae86948defef2f205284e61c17a9f0f707df3fd987b1feeb3a4138804978d`.

The unadjusted projection digest in that assessment is explicitly not publication approval. The completed legacy cursor is not remote-delivery evidence.

## Critical issues and required fixes

### 1. P1: remote readback omits the guard values now required by fingerprints

Relevant code: candidate `sheets_sync.py:745-806`, `819-869`, `912-918`, `956-1025`; `publication_receipts.py:55-117`; migration conversion at `exact_legacy_migration.py:84-86`.

Migration removes changed Review Status from mutations and retains it in `expected`. The revised fingerprint correctly includes this guard-only field. However, `readback_exact_scope` still checks only identities, mutation values, and appended-note presence, and returns `actual` containing only `evidence['fields']`, which are mutation fields. `_exact_readback_records` reconstructs rows from this reduced `actual`. The fingerprint then substitutes an empty string for each omitted guard. It therefore hashes a synthetic blank rather than the value actually read from the remote row. Chunk confirmation also advances before any guard-fingerprint comparison.

**Reproduced after the requested fingerprint repair, with real temporary SQLite/inbox journals and an in-memory remote repository:**

| Frozen Review Status | Actual remote Review Status | Result after database reopen/retry |
| --- | --- | --- |
| `Human Reviewed` | Different status | First commit refuses; retry incorrectly confirms the chunk, but final receipt confirmation now refuses. This closes the original nonblank receipt bypass only. |
| Empty string | Different status | First commit refuses; retry confirms the chunk **and reaches `SYNC_CONFIRMED` with zero successful remote writes**. The omitted actual guard is substituted with the expected blank. |
| `Human Reviewed` | `Human Reviewed` | Remote commit succeeds and the remote row is correct, but final receipt confirmation refuses because the observed fingerprint substitutes a blank guard. |

The blank-guard case is a supported builder input: the current local Review Status can be blank while the legacy mutation was nonblank, and reconciliation turns that difference into an expected-value guard. I have not asserted that either real Davidson row has a blank status. The nonblank matching case is independently sufficient to block a correct migration's delivery. These checks prove both a remaining false-confirmation path and a new availability failure; no protected value was overwritten in the fixtures.

**Required fix:** retain actual remote guard-only values in the readback evidence, compare them before advancing any chunk/cursor, and include them in the confirmation digest without expanding the mutation/dirty-acknowledgement field set. Missing evidence must not be silently treated as an observed blank. Apply this consistently to uncertain-attempt recovery, confirmed-chunk reread, and final confirmation. Retain the new distinction between historical baselines for mutated/noted fields and guard-only fields. A typed preflight guard rejection must remain a nonterminal hold while the mismatch remains. Decision is local-only in compact-v1 and must remain a local guard rather than becoming a requested Google column.

### 2. Tested predecessor P1; late planner repair awaits verification: incomplete local snapshot

Relevant code: `exact_legacy_migration.py:62-106`, `138-143`; `publication_receipts.py:55-106`.

The reconciliation loop compares `on_insert` and `values`, and its second read now fingerprints mutations, guard-only expected values, and note suffixes. That fixes the missing-guard cases, but fields absent from those mappings remain outside the evidence. The returned `local_readback_digest` is still a digest of a reduced operation/guard projection, not the assessment's complete current-record digest.

Re-review results:

- A changed Source Hash named only in `expected` is now correctly rejected.
- Changing an otherwise unmentioned Review Notes field produces an identical plan digest and identical `local_readback_digest`.
- A Decision change injected after the first row read but before the final row read is now correctly rejected.

The revised `_resolved_row_scope`/`_revalidate_row_scope` also catch later local guard changes, including across an actual database reopen. Those repairs are accepted for the cases tested. They do not prove the complete reviewed snapshot or restrict allowable drift to precisely the two approved exceptions.

**Required fix:** take a consistent selected-row snapshot and bind the complete reviewed record set, stable identities, schema/profile, and current control state. Validate the exact approved exception identities and their before/current field digests; reject additional conflicts rather than automatically accepting any Review Status/Decision drift. Use a separately named full-snapshot digest and a separate guard digest. Recheck those pins at the durable adoption boundary under the normal exclusion/transaction rules. Never equate the existing reduced fingerprint with the assessment's full-record digest.

### 3. P1 readiness blocker: binding validation is not durable migration/adoption

Relevant code: `exact_legacy_migration.py:47-59`, `109-165`; `exact_local_plan.py:215-278`; `inbox.py:260-309`.

The new mandatory binding is useful: it rejects a caller's mismatched plan/inventory digest, count, cursor, or labels. It only compares supplied values, however. It neither reads an authoritative retained inbox binding nor performs a database compare-and-swap. It does not pin workbook identity, blocked state, the complete local snapshot, or the two approved conflict identities. The helper intentionally writes nothing, and its migration dictionary is not a durable journal.

Two additional builder probes succeed when they should be held at an operational migration boundary: current local Company Status is `Hold` while supplied controls say `Active`; and caller labels/binding/controls all name another Company and cycle while the operations still name `COMP-0035`. The latter shows missing operation ownership validation, not a bypass of a genuinely trusted, independently pinned binding. No trusted binding loader or adopter is present in this candidate.

The existing `save_exact_plan` correctly refuses to replace the retained legacy plan. A temporary inbox containing the legacy plan at its completed cursor reproduces `Exact v2 plan conflicts with existing frozen evidence`, with the legacy plan retained and no receipt. Conversely, routing a newly saved v2 plan through the ordinary local-apply path would invoke `_commit_in_transaction`; it does not adopt the already completed legacy work without replay.

**Required fix:** implement and separately review a narrow adopter. It must load the authoritative exact cycle/Company/workbook inventory and legacy plan, verify all approved pins and current local controls, persist the immutable original artifact and migration journal, then CAS-install or link the v2 successor without deleting history. It must adopt verified existing local records without re-executing the 19 legacy operations and without asserting remote delivery. Cross-database steps need explicit recoverable states and idempotent evidence; same-database journal/transition changes must commit atomically. Old and successor plans must never both become actionable. No receipt, cleanup, remote write, or cycle advancement belongs to merely building this candidate.

This is missing required functionality rather than an accusation that the deliberately pure builder itself writes unsafely. It nevertheless prevents accepting the candidate as the solution to the retained-plan blocker.

### 4. Tested predecessor P2; late planner repair awaits verification: remote operation ordering

Relevant code: `exact_cycle_planner.py:296-343`; `sheets_sync.py:519-573`, `685-708`.

The builder preserves legacy operation order when projecting. Exact scope planning sorts by tab priority and local row ID, then pairs the sorted scope with the frozen projection positionally. In a synthetic Company-first legacy plan, migration seals successfully but `plan_exact_scope` refuses with `Exact Sheets scoped plan differs from the frozen projection`. The supplied nominal fixture also begins with Company work but does not exercise publication planning.

**Required fix:** prove deterministic compatibility with exact scope planning before a candidate is declared ready. Either freeze the remote stream in the publisher's required ordering while preserving the complete local stream, or make the consumer pair operations by exact identity. Validate baseline, dirty-field, Source Hash, insertion, salary, and append-note requirements at the same boundary. I did not inspect live Davidson operation ordering, so this finding demonstrates an uncovered compatibility case, not a claim that its current ten-operation projection has that ordering defect.

## Correct behavior verified

- A synthetic 19-operation case produces 19 local operations and 10 remote operations: one Company and nine Job History rows. All nine Job Evidence operations remain in the local stream. Input rows, legacy plan, and payload remain unchanged.
- On the two changed rows, Review Status and Decision are removed from the obsolete mutation values and retained in local guards. Review Status remains a compact remote `expected` guard. Decision is correctly absent from the compact remote schema and all remote mappings.
- The latest exact protected-field-list validation rejects omissions and duplicates.
- The revised local scope verification refuses a changed Decision after closing/reopening SQLite, without replaying local mutations.
- The revised guard-only fingerprints reject expected-only Source Hash drift and a Decision change between the builder's two reads. Historical expected baselines for mutated/noted fields remain excluded.
- Completed-cursor, duplicate-target, stable-identity, profile, and plan/projection digest checks provide useful existing boundaries. They do not resolve the findings above.

## Tests and reproducible evidence

Final re-review migration plus adjacent matrix: **128 tests passed**, with warnings treated as errors. This comprises the nine supplied migration tests and 119 tests across local plans, planner, exact Sheets scope, exact sync, recovery, terminal recovery, and receipts. This is the exact selection independently run here; the coordinator's separate 145-test report is not substituted for these results.

Independent reviewer suite: **12 checks passed**. Six diagnose remaining unsafe behavior or the remote confirmation regression; two demonstrate outstanding adoption/order holds; four verify nominal projection and repaired local/guard behavior. These are diagnostic reproductions, not twelve acceptance tests. The suite's docstring and this report make that distinction explicit. The two requested original reproduction paths were rerun; the original nonblank remote case now stops at final confirmation, but the blank-guard variant still falsely confirms and the matching nonblank variant cannot complete.

The original fixture's missing `rows` attribute and an intermediate SQLite fixture's missing compact schema column were corrected in the shared candidate during review. An intermediate copy also briefly mixed tests requiring `binding` with the older helper. None of those intermediate results determines this recommendation; the final coherent snapshot passed all 128 supplied/adjacent tests.

Evidence directory beside this report:
`HIGH_MODEL_MIGRATION_REVIEW_EVIDENCE/`

It contains `reviewer_probes.py`, `reviewer-probes.log`, `final-focused-tests.log`, `final-source-manifest.json`, and `late-planner-diff.patch`. The disposable source/test tree is `/home/chris/Documents/Codex/2026-11-19/job-search-migration-review/work/migration-review`. That tree retains the tested snapshot, rather than silently receiving the later planner revision.

Reproduce from that disposable tree only:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error reviewer_probes.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python3.11 -W error -m unittest -q test_exact_legacy_migration test_exact_local_plan test_exact_cycle_planner test_sheets_sync_exact_scope test_exact_cycle_sync test_exact_cycle_recovery test_exact_recovery_terminal test_publication_receipts
```

The interpreter was reused without installation. All repositories instantiated by these checks are synthetic memory repositories or temporary SQLite files. No Google client performs network requests.

## Additional acceptance tests required

1. Convert each unsafe-behavior reproduction into a rejection test. Test blank and nonblank guards with matching, mismatching, missing, and changed remote values. Persist a refused attempt, reopen both databases, and prove chunk, receipt, acknowledgement, cleanup, and cycle-finalization state cannot advance while the guard mismatch remains. A matching nonblank guard must successfully confirm through the genuine readback path.
2. Exercise the full synthetic 19/10/9 shape with exactly two approved conflict identities, full snapshot/guard digests, all 17 unchanged records, and byte/semantic preservation of Job Evidence. A third changed review row or changed current value must hold.
3. Test drift in expected-only Source Hash, Review Notes, append-note surroundings, local-only evidence, salary, identity/URL, Company controls, profile/schema, and inventory/finalization. Include missing/duplicate identities and rows moved between reads.
4. Inject changes before, during, and after snapshot capture, preview, journal persistence, adoption, local verification, each remote read/write boundary, and final confirmation. Cover both protected fields and ordinary values.
5. Kill/reopen at every adopter durability boundary. Verify immutable original evidence, exactly one successor, cursor semantics, retry idempotence, no legacy mutation replay, and no receipt from a local cursor. Test journal-write/fsync failure, partial cross-database progress, duplicate invocations, altered retry pins, and pre-existing conflicting v2/receipt evidence.
6. Run migration through real temporary SQLite baselines/dirty state and the exact scope planner using both legacy ordering and reordered local row IDs. Test insertion, formula/occupied-row refusal in the Sheets fixture, source/salary protections, and preservation of manual Opportunities.
7. A projected-row preview must use only compact columns, perform no writes/receipt creation/cleanup, and be bound to the same full migration evidence and payload that any later approval would name.
8. Version or explicitly handle the fingerprint-format change for pre-existing sealed plans/receipts. Prove old durable evidence is preserved and held or deliberately migrated; do not silently recompute its immutable expected records under a changed fingerprint definition.

## Safest next action

Keep the retained legacy plan, all local evidence, the two newer review decisions, and the broad cycle unchanged. First repair the remaining remote guard readback/confirmation hole and add the blank/nonblank end-to-end regressions. Freeze and test the late planner's snapshot, ownership, binding, and ordering changes together with that repair. Then implement the separately journaled, exact-binding adopter and prove crash recovery on disposable copies without reapplying legacy operations.

After independent acceptance of a frozen source hash set, prepare the exact ten-operation compact read-only preview and its durable evidence package. Any production migration/install or bounded Google write remains a separate gate; this review authorizes neither. Do not discard the legacy plan to make `save_exact_plan` succeed, do not interpret `19/19` as publication, and do not run broad recovery to bypass these holds.
