# Independent repair-retry publication binding QA

Verdict: **ACCEPT this exact source slice.** No proven blocker was found against the requested receipt-binding contract. This is isolated source/test acceptance, not production deployment, real Google publication, provider validation, qualification-authority approval, or deferred State recovery acceptance. The coordinator owns the complete disposable replay; another reviewer owns recovery.

## Reviewed source pins

All four files under `/tmp/jsh-s5-repair-retry-publication-binding.ifqH1hT9/src/job_search_helper/` matched `/tmp/jsh-s5-amphenol-publication-rehearsal/publication-source-pins.json` before and after tests.

| File | SHA-256 |
|---|---|
| `exact_cycle_receipt.py` | `f44d1ea8c52e829a3fb7bbe6b4f6c809c53c44690949173217e5e7b4bde8d334` |
| `exact_cycle_planner.py` | `0932566520c9807e7e5066bf4f7787c3a88b057f011f68167eed0bcb1425063b` |
| `exact_cycle_sync.py` | `e7268d3eb103ef2deb7300e05d595892d55135764186f92a8f57e330a131139d` |
| `inbox.py` | `145042f27d25c1c2d2f21588ce28097acf7b17ab7bad25163a7bfe60e4dd8d9c` |

Focused maintained test `tests/test_repair_retry_exact_publication_binding.py`: `9a1ca8eec407cefc54633247fc77bb42ea10e91a2a88d2f3a5d644b2092e0c85`.

## Source findings

- `exact_cycle_receipt.py:197` derives the receipt from the canonical one-company repair retry. Validation ties the request ID to the immutable attempt, original failed request, Company, source revision, full release manifests and activation time. The frozen eligible Company fact must match the source digest and the cycle's admitted runtime must equal the activated release. The receipt stores the actual `company-retry:RTRY-...` request, Company, current source revision, release ID and full release-binding digest; its schedule uses the immutable activation time.
- `exact_cycle_receipt.py:235` reuses the existing active-COMPLETE release authority and current Company-source authority. `:248` rejects a conflicting remote intent, legacy cycle/request alias receipt, or competing record receipt before inserting a new receipt. `:271` requires an exact compact-v2 plan, matching payload/records/digests, frozen retry binding, and no competing lineage.
- `exact_cycle_planner.py:852` checks the admitted runtime/current source/release before freezing. It rejects existing unbound plans instead of rewriting them. The repair binding participates in the frozen plan digest, and preserved Company source guards are required.
- `exact_cycle_sync.py:504` derives the same binding before publication, rechecks current authority before receipt creation, carries that identity into the remote intent, and rechecks before remote commit and terminal acknowledgement. `_fallback_receipt` no longer substitutes the cycle ID for a repair retry.
- `inbox.py:1917` requires the durable receipt to equal the frozen repair plan binding before remote registration. An ordinary cycle alias cannot register a repair plan. Existing ordinary-event, selected-temporary-retry and generic branches remain distinct; retained and competing lineage are rejected for the repair branch.

## Executed evidence

`126 passed in 10.18s`, exit 0. The run used staged source, disabled bytecode and pytest cache, fixture SQLite stores beneath this scratch directory, and in-memory remote repositories. No provider/public fetch, Jetson call, real Google client, credential access, native event, or production write was performed.

The run comprised 121 maintained checks across the new repair-binding fixture and existing ordinary-event receipt, exact planner/sync, publication receipt, repair retry and retained publication suites, plus five independent probes. Existing selected-temporary-retry dispatch/receipt branches were checked in the focused source diff; this report does not claim an additional dedicated selected-retry suite run.

The maintained positive fixture confirms one exact terminal `SYNC_CONFIRMED` receipt with the guarded request/source/release identity and one remote batch. The existing unbound-plan case preserves the old plan and sends no write. Legacy cycle-ID and actual-request aliases, rolled-back release and changed Company source hold with unchanged receipt rows, no remote intent and no remote batch.

Independent probes exercise changed failed-request provenance, removed repair metadata, mixed Company-event lineage, a direct legacy-cycle receipt passed to remote registration, and changed runtime source manifest. All hold before creating a new receipt/remote intent or sending a remote batch. These probes are in `test_independent_receipt_binding.py`, SHA-256 `57391c84fefca1ad7ea7bf653dbb139262139e4a3a9c69d717fcaddbe633c76c`.

Result log: `pytest.log`, SHA-256 `f5455233f2dbf465c24ea7e499a87c20135ac6cb2ac7f7d8a2a42231f47a64d5`.

## Reproduction

Use the production virtual environment's Python with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH` ordered as the staged `src`, staged `tests`, then `/home/chris/job-search-helper_old/tests`. Run pytest with `-q -p no:cacheprovider` and a fresh scratch `--basetemp`, selecting:

- Staged `tests/test_repair_retry_exact_publication_binding.py` and `tests/test_ordinary_event_receipt_binding.py`.
- Maintained `test_exact_cycle_planner.py`, `test_exact_cycle_sync.py`, `test_publication_receipts.py`, `test_repair_retry.py`, and `test_retained_work_publication.py` from the production test directory (read only).
- This scratch directory's `test_independent_receipt_binding.py`.

The maintained positive fixture constructs an admitted cycle in disposable storage. Full guarded application admission and end-to-end receipt custody remain the coordinator's separate disposable replay evidence; this review does not relabel that fixture as a real production request.
