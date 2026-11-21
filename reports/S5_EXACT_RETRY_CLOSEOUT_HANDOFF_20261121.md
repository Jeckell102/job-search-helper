# One published release retry closeout

The scoped application seam is `close_published_repair_retry(engine, cycle_id, company_id, *, attempt_id, release_id)` in `src/job_search_helper/exact_cycle_recovery.py`. It accepts an opened local Engine with the exact admitted runtime after the separate publication operation has released its locks. It acquires the normal scraper lock, then the local writer lock. It verifies the local authorities, exact admitted retry, current Company revision, active release, finished Company stage and matching confirmed Inbox and Jobs acknowledgement before either local write.

Existing `Engine._sync_cycle` advances only the exact local Scan Cycles mirror and State checkpoint. If interruption left the mirror ahead of State, the existing exact completion timestamp is reused without rewriting the mirror. The existing sealed `record_repair_retry_success` adds one immutable COMPLETE outcome after readback. Replay returns the same outcome, and pending, absent or conflicting evidence holds. The helper does not start the retry, touch the queue, fetch a provider, construct a spreadsheet client, or invoke broad cleanup. Closeout is local. The helper does not publish the Scan Cycles mirror to a remote workbook.

## Frozen scope and pins

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/exact_cycle_recovery.py` | `e9ad790842de5d1406f90d816e45ec0bc39fe5b5545e5df8c1a0e09c5758074f` |
| `tests/test_repair_retry_closeout.py` | `5ea08ffc8e6915350452b8fed66a160d8671afd573ba1413568b444ef92d22e6` |
| `src/job_search_helper/exact_cycle_receipt.py` (coordinator-owned dependency, copied unchanged) | `7602084179e929f0cc06ec664e60ebe30c7afcccbc052d26c490d9060a7b9ce6` |
| `test_saved_amphenol.py` (private proof only) | `a193eafc4a86b0bcf0a9c211e59a3e8b7de26ecd1dcbe73e6c9e4a62fc726dec` |

## Evidence

- Nine maintained focused cases and one archived-state proof passed together. The focused cases use normal request admission, local deferred inventory and the existing exact publisher with an in-memory workbook. They prove fresh closeout, both durable interruption boundaries, no persistent replay changes, refusal for either busy lock, wrong Company/attempt/release, and absent or pending publication evidence.
- The archived proof copied and checked the existing already-published Amphenol SQLite files, archived request and release journal. One COMPLETE outcome was added for `CYC-8F35E1D030EF`. Both retries of the call returned the same outcome. The prior outcome and unrelated cycle, 18 job rows and corresponding Job Evidence rows, receipt and archived authorities remained unchanged. Original fixture hashes matched before and after.
- The affected regression run passed 44 tests with the same 12 failing older tests as the unmodified baseline, which passed 35. `BASE_AFFECTED.log` and `COMPOSED_AFFECTED.log` retain both lists.

Tests used the isolated system Python 3.11 interpreter and existing test dependencies. The runner denied sockets and child processes. No native app, production, provider, Google, Jetson, installation, or deployment effects.
