# Sprint 5 AcquireTM typed pagination observation

Staged for independent source review. The normal AcquireTM dispatch can now return a bounded typed witness for the delayed page-two transition. The original scrape stays partial with zero jobs in the witnessed branch. The staged source does not settle a Company event or start a repair.

## Scope and pins

| File | Original SHA-256 | Staged SHA-256 |
| --- | --- | --- |
| `src/job_search_helper/acquiretm.py` | `88893583bb01ed0b8878020d9b71ddb9043bbfcdb70d6e0eb6b2475bc8855392` | `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61` |
| `src/job_search_helper/ats.py` | `a43ca8a0b337ff8a61d63a81619390c9860791af84cff6115f87581ff6313a29` | `111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e` |
| `tests/test_acquiretm.py` | `5bace6904b1630871477aa2b5b408a591813a834742a2bcca85c757c8dd5e908` | `dca8d436b5c7840beecba2c14b6ffc01d4d279adab3a5fb5083d681713d891f1` |

Compared 248 copied source, fixture and public text inputs against the original tree. The three staged files above were the only differences.

## Exact observation

- Scope is Amphenol Aerospace COMP-0490 at the existing exact AcquireTM source. The original page-two click and first wait remain in use. Evidence is considered only when the exact pre-click and immediately reread first-page rows still agree, the total is unchanged and the first-page count is smaller than that total.
- A bounded, read-only observation follows the same click and waits for a new same-board posting ID. It re-parses the exact board URL with the existing inventory parser. The late rows must be nonempty and disjoint from page one, with the same advertised total and combined membership within that total. Rate-limit content, missing or malformed listing, a persistent repeated page, changed total, or a timeout has no typed evidence. No second click, additional navigation or detail retrieval occurs on this diagnostic branch. The existing immediate-refresh path still returns the complete result when its normal detail and reread checks pass.
- The `outcome-failure-v1` envelope uses category `pagination_regression` and code `acquiretm_updatepanel_premature_read`. It carries the page, advertised total, first and refreshed counts, sorted membership SHA-256 digests and elapsed milliseconds. The validation contract preserves the exact existing access/temporary envelopes and requires the closed witness shape only for this code. No raw HTML, titles or IDs leave the adapter in the witness. A later owner must independently bind that witness to the exact measured attempt and scope before producing a qualified terminal outcome.

## Verification

The new deterministic asynchronous regression uses the actual `with_browser_fallback(fetch_inventory)` top-level dispatch with a synthetic Playwright page. It proves the typed delayed transition and holds for initial timeout, persistent same page and changed total. Immediate refresh completes both details and repeat inventory, with no typed evidence.

- **56 passed in 1.18 seconds** across `tests/test_acquiretm.py`, `tests/test_outcomes.py` and `tests/test_scrape_outcome_producer.py`.
- The unchanged new regression failed on the two original pinned source files, at the missing membership observation after the first premature wait. The baseline run ended `1 failed, 6 deselected in 0.17s`.
- System Python 3.11 ran with `-I -S -B`, copied test support and a native socket audit guard. All test files, fake browser state and outputs used the disposable source snapshot. No production edit, model-proposal workspace change, operator admission, Jetson, Sheets, release, or real network operation took place in this lane.
