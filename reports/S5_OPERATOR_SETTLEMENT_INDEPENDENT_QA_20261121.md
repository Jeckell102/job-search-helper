# Independent named operator setup and settlement QA

**ACCEPT** for the staged named Amphenol operator entry and local typed-partial settlement.

| Reviewed source | Exact SHA-256 |
|---|---|
| `operator_amphenol_settlement.py` | `b3d57c0f8037b184ca0c133fc08bd45ef9465a338bce3b0bfb9add9a0138b77c` |
| `runner.py` | `de3c0f5045e1ad07d0b1e2e8b1da8b8dbce2acd3767182ddf9d1c7dbbaefb87b` |
| `release_admission_bootstrap.py` | `1258ac47b647d61361fa84ccdda14816a184e6c15cd4c6e7c78e6b27cd228d45` |
| `job-search-scraper` | `8fb9939560f004a213ca94724cdada7734996072c31194679017fea492841f72` |
| `tests/test_operator_amphenol_fetch.py` | `38ef296263ecb1e18ef12add12dfcf315721b9442738a08a8a0199fed9f4b5c3` |

The copied normal launcher independently passed its focused pre-import test under system Python 3.11. The named command held when exact SQLite stores were missing and passed the co-located State and Jobs layout to the disposable runner when both existed. The named application runner takes the inherited scraper lease and existing writer lease and opens only a compact workbook reader for the first provider scope check. Its settlement writer, terminal State, and Inbox are local.

The initial exact settlement `ee885f72…` exposed successful replay while the originally owned queue acknowledgement was still pending, and separately accepted an immutable outcome with a changed stored timestamp. Both independent failed fixtures are preserved. Revised replay finishes the exact checkpointed request acknowledgement before exposing outcome authority and re-syncs its directory. A distinct queued request is unchanged. The recorded outcome now matches every indexed field, exact canonical payload and timestamp before idempotent reuse and after first storage. Wrong readback holds without healing.

The maintained terminal-State cut produced no outcome until the exact terminal State was saved. The corrected path emitted one durable qualified outcome and recovered it without a second provider or workbook action. A nonqualifying observation preserved the queue without creating a cycle or outcome. Five guarded disposable tests and the separate actual copied launcher test passed. No native source, credentials, application, services or network were accessed. Downstream host delivery and live activation are outside this result.
