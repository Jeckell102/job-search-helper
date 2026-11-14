# Unused-row read optimization — 2026-11-14

Appending a few jobs previously downloaded full CellData, including repeated dropdown rules, for every row between the last identifier and the bottom of the grid. The writer now scans that area with values.batchGet and FORMULA rendering. Full cell details are fetched only for existing affected rows and the bounded insertion destinations.

A second lightweight tail scan detects content added during validation. Formula cells whose calculated value is blank still count as occupied; so do zero and false. Manual orphan rows remain above the insertion point. Newly occupied destinations abort before writing, rather than moving a write into rows whose validation was not loaded. Missing tail responses and populated columns without headers also abort. Identity, duplicate, formula, dropdown, atomic write, and uncertain-write replay checks remain enabled. Existing-only updates do not gain tail reads.

## Verification

275 offline writer and synchronization tests passed against the installed-source staging copy, including 11 new append-tail regression cases. No live spreadsheet writes or scraper restarts were used for validation. The staging copy included the installed title configuration required by the existing tests.

The GitHub branch contains a separate baseline commit for the already-modified installed repository.py and Sheets fixture, followed by this optimization. Other pre-existing installed-source modifications are not included in this focused backup. The 275-test result applies to the complete installed-source staging copy, not an independent checkout of all older files on this backup branch.

## Response-size comparison

Synthetic fixture: 200 existing jobs, 23,829 unused rows carrying four dropdown rules, and two successive batches of 100 inserted jobs. Both versions used the same range-aware offline API. Bytes are decoded JSON response sizes, not compressed network traffic or measured live elapsed-time improvement.

| Append batch | Before bytes | After bytes | Reduction | Reads before / after |
| --- | ---: | ---: | ---: | ---: |
| First, without cached locations | 27,340,602 | 2,828,687 | 89.65% | 4 / 6 |
| Next, with cached locations | 25,906,492 | 1,497,877 | 94.22% | 1 / 3 |

Each batch retained one atomic write. The two additional lightweight reads preserve occupancy checks while removing validation metadata from unused rows. Small sheets can incur extra request overhead; the improvement targets large, validation-heavy unused areas. The fixture retains empty grid-cell structures in identifier scans, so these bytes should not be presented as a production prediction.

Raw measurements are in `unused-row-read-benchmark.json`. Run the synthetic comparison with `PYTHONPATH=src:tests python tests/benchmark_unused_tail.py`, using the appropriate source version. Google documents FORMULA rendering and omitted trailing empty rows in https://developers.google.com/workspace/sheets/api/samples/reading.

The installed code takes effect in newly started scraper processes. An already-running Python process retains its imported writer code.
