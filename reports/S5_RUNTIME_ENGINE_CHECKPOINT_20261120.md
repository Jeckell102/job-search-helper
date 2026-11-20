# Sprint 5 Engine runtime checkpoint

The isolated Engine candidate at `/tmp/jsh-s5-runtime-sealed-checkpoint.Lum2G5u0` passed 69 focused tests. The new composition passed 14 cases. This is a provisional Engine source pin based on the first repaired custody implementation. Independent custody QA found two further gaps in that baseline. The Engine path opens fresh private handles, and the independent custody fixes still require a combined rerun. [Current custody verdict](/tmp/jsh-s5-runtime-mapping-fact-repair-independent-qa.md)

## Exact operation

The private class method `Engine._accept_runtime_source_configuration_defect_evidence(cycle_id, company_id, fact_id)` takes only exact stable IDs. It requires the configured co-located SQLite owner and consumes the existing verified pre-import scraper descriptor through the runner's admission context. The context remeasures installed source, configuration and dependencies. Engine also takes the existing Jobs writer lock and opens fresh private managed State and read-only Jobs handles. Missing, competing or mismatched authority stops before the sealed checkpoint. The operation reads only the exact runtime receipt and returns its fact ID on success.

The checkpoint accepts an ordinary Company attempt with a saved incomplete observation and no existing failure envelope. It uses the current source and qualification from the existing all-or-none checkpoint. A completed matching group is an exact replay with no rewrite. The three-argument packaged lookup and its existing Engine route retain their behavior.

The test fixture starts and runs an exact ordinary Company through normal Engine admission and local processing with one synthetic blocked inventory. It persists synthetic verifier evidence, seals through the new Engine path, verifies synthetic compact storage with an in-memory workbook, then calls the normal outcome producer and sealed Jobs writer. Before recording the outcome, Engine sealing leaves no Jobs write or outcome. The strategy preserves the first immutable unknown outcome if evidence arrives later. Testing also covered missing/wrong fact IDs, foreign Company/cycle, runtime/config/source drift, foreign provenance, missing and busy leases, typed access evidence, queued work and a State checkpoint fault followed by a restart.

There is no launcher, runner, provider, verifier, network, task-promotion or production wiring in this candidate. The inherited admission descriptor is one-use. A future normal-worker integration must place the exact checkpoint before the first outcome write and arrange for the same measured scraper and writer ownership to span observation handoff without reacquiring a lock it already holds. The present private operation demonstrates a separate guarded admission and does not change the sticky terminal rule.

## Pin

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/engine.py` | `78d4a1d45300c3347a81834c270dabd5f606bf188941a096c172807a391794dd` |
| `tests/test_runtime_sealed_checkpoint.py` | `ef5194c592b026e6359f88d21ae265bf3938978148f0b1412f3370285dc7e895` |

The imported Engine base was `3ede2b3b9ee4d3fa429c8eca2e4a96428ca69730dee71bf806165ce5812e17d9`. The byte-identical copied launcher bootstrap is fixture infrastructure only and is not part of the Engine pin. Its SHA-256 is `c508a85743d54f0840b4906d17bb6780c3c8daad2914d53f58a5006602e70862`. The original custody pin was preserved.

```bash
env JOB_STORAGE_BACKEND=sqlite PYTHONPATH="$PWD/src:$PWD:$PWD/tests" PYTHONDONTWRITEBYTECODE=1 \
  /home/chris/job-search-helper_old/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp="$PWD/test-work/expanded" tests/test_runtime_sealed_checkpoint.py \
  tests/test_runtime_mapping_facts.py tests/test_source_configuration_snapshot.py \
  tests/test_source_configuration_cycle_state.py
```
