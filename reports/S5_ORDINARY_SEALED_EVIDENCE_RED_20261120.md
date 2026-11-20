# Sprint 5 ordinary scrape to sealed evidence

**Reproduced.** The default-off case passed. The exact reviewed qualification case reached the same normal worker and then failed only at the missing authoritative evidence handoff. Both cases consumed a real disposable company-only request, fetched Forterra through the normal Rippling dispatcher, and produced one immutable `UNKNOWN_CAPABILITY_HOLD`. The reviewed case matched the exact installed Company revision, capability, mapping and configuration digests. Its mapping-fact descriptor remained empty and none of the three sealed State fields appeared.

| Case | Reviewed qualification | Durable mapping fact | Sealed cycle fields | Immutable outcome |
|---|---|---|---|---|
| Default off | Absent | 0 | 0 | `UNKNOWN_CAPABILITY_HOLD` |
| Reviewed | Exact match | 0 | 0 | `UNKNOWN_CAPABILITY_HOLD` |

## Fixture and reproduction

The isolated checkout is `/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW`. Its source template is copied from the accepted Sprint 4 dispatcher-binding QA snapshot. Each run generates a separate runtime copy, then changes only the synthetic Forterra mapping and its matching installed-manifest fingerprint. The real installed resolver loads that coherent pair. Only the reviewed fixture writes one qualification into its disposable descriptor. Neither fixture writes a mapping fact, calls the evidence checkpoint, seeds a qualified outcome, or starts a coordinator task.

The test enters through `runner.scrape_main(['start', ...])`, the normal worker CLI entry, with the normal SQLite lease and runtime measurement. It uses the real Engine, provider routing, Rippling parser and outcome writer. It skips the outer scrape-first-pass controller. The only storage scheduling substitution is a synchronous drain into in-memory Sheets before the normal outcome write. Both runs verify zero remaining pending cells and agreement between the local State and local Scan Cycles mirror, plus unchanged fake-workbook Company source and no job rows. The network/OAuth barriers fail the test on any attempted connection.

The same pinned synthetic capture supplies an employer-page link to the current Forterra board, a wrong-tenant response for the stale configured path, and complete scoped Forterra and PDW list/detail evidence. The independent observations use the existing normal parsers, with stable posting identity, full descriptions and final listing reread checked. The current-board and PDW observations are fixture evidence only. Normal dispatch gets the stale response; no trusted fact is handed to it.

```bash
cd /tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -q -rx --basetemp="$PWD/test-work/recheck" tests/test_ordinary_sealed_evidence_red.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -q --runxfail --basetemp="$PWD/test-work/red-recheck" tests/test_ordinary_sealed_evidence_red.py
```

The first run returned **1 passed, 1 strict xfail**. The second returned **1 passed, 1 deliberate failure** with `MissingSealedEvidence`. The strict expectation recognizes only that specific failure after successful normal dispatch, measurement, fake publication and exact qualification. An unrelated fixture failure remains an ordinary failure.

[Fixture tests](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/tests/test_ordinary_sealed_evidence_red.py) · [Normal worker probe](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/tests/ordinary_probe.py) · [Pinned public fixture](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/fixture_data/public-rippling.json) · [Side-by-side evidence](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/comparison.json) · [Expected-failure run](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/third.log) · [Forced-red traceback](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/forced-red.log)

## Smallest safe implementation seam

Use the normal runner's exact post-observation boundary immediately before `record_cycle_outcomes`. For one qualified, incomplete ordinary-cycle item, accept a bounded, structured Rippling scope observation and the independently verified employer, candidate inventory and regression digests. Bind them to the frozen cycle and Company, current source revision, installed capability/mapping/configuration and runtime. Read the exact qualification before doing optional verifier work. A foreign slug or a free-form partial reason alone cannot establish a qualified defect. Preserve existing precedence for actual access, temporary, storage and stale-source outcomes.

Persist the closed fact under the owned cycle/Company and its exact fact identity in runtime State, or its reviewed adjacent evidence store. The current `mapping_fact_by_id` reads a static descriptor in the immutable package. Runtime evidence written there would change the measured source tree. Reuse the existing checkpoint group's reread and all-or-none validation behind a narrow runtime-owned fact lookup. Reuse the sealed Jobs writer to derive the outcome. Prove default-off, duplicate replay and a fault between fact persistence and checkpoint sealing before wiring the repair coordinator. [Outcome boundary](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/frozen-source/src/job_search_helper/runner.py:1075) · [Checkpoint group](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/frozen-source/src/job_search_helper/engine.py:425) · [Static fact lookup](/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/frozen-source/src/job_search_helper/source_configuration_snapshot.py:482)

No production source, provider, Jetson, real workbook, release, or live state was touched.
