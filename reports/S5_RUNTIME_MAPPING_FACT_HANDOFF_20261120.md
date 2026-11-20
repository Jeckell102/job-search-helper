# Sprint 5 runtime mapping-fact custody

Implemented in `/tmp/jsh-s5-runtime-mapping-fact.FNwS9PUY` using the accepted Sprint 4 binding QA snapshot as the isolated source base. **44 focused tests passed**, including the existing packaged-fact and sealed checkpoint compatibility suite.

## Contract for the next caller

- `persist_runtime_mapping_fact(state, repository, runtime_binding, cycle_id=..., company_id=..., fact=...)` accepts one closed fact already produced by an authorized verifier. It returns the existing canonical fact ID on identical replay. It never fetches, qualifies a provider observation, edits the installed package, seals the Engine checkpoint or emits an outcome. The caller owns the ordinary scraper admission and Jobs writer boundary and supplies its measured runtime binding.
- It reopens the exact ordinary cycle and saved Company member, rechecks the current local Company, installed configuration snapshot, exact qualification and any existing sealed group. The owner also binds request identity, runtime, canonical State and Jobs file identities and workbook. Copies to different database inodes do not inherit the fact. The append-only State SQLite table holds one row per cycle and Company. First creation and insertion share an immediate transaction. Readback verifies the canonical record, owner binding and independent fact ID. Missing, stale, substituted, competing and foreign records fail closed.
- `read_runtime_mapping_fact(..., cycle_id=..., company_id=...)` can reopen an owned receipt through read-only State/Jobs and leaves a legacy database without the table unchanged. For ingestion, `source_configuration_snapshot.mapping_fact_by_id(cycle_id, company_id, fact_id, state=..., repository=..., runtime_binding=...)` selects only the exact ID. A valid existing runtime slot bars package fallback for another ID, and a corrupt or stale slot raises. With no runtime slot it can use the existing exact packaged fact, after checking the contextual owner. The original three-argument package lookup keeps its existing behavior.
- The next Engine integration should add an explicitly owned runtime-fact entry or opt-in lookup to its existing stable-ID checkpoint method and leave the current three-argument legacy path intact. It should pass the result through the existing sealed group validator before outcome recording. Keep the authorizing verifier and checkpoint caller separate from this persistence module. Do not treat the synthetic test digests as independently verified provider facts.

Package descriptor and complete source-tree digests were checked before and after persistence and replay. Tests also cover changed Company source, changed installed capability bytes, removed or restamped qualification, incompatible runtime, request substitutions, corrupt raw rows, a substituted SQLite relation, a foreign cycle/Company and a copied or aliased State file. A fault during insert leaves no partial record. An existing partial sealed group fails closed. No Engine or runner edit was required or made.

## Owned files

| File | SHA-256 |
|---|---|
| `src/job_search_helper/source_configuration_snapshot.py` | `28c201c668a85e94e25264d9d700a810ef280e7082023dbb453e0cbad06cc361` |
| `src/job_search_helper/runtime_mapping_facts.py` | `da02abdd8d7e0f82575a61b63eb216956aa25b5f0f5a5b5a567721d11b1c8fd0` |
| `tests/test_runtime_mapping_facts.py` | `365e87886015d8c580152ba09a08e6011d6f786c0786ed307bb4ae91e7cecef0` |

```bash
cd /tmp/jsh-s5-runtime-mapping-fact.FNwS9PUY
env PYTHONPATH="$PWD/src:$PWD/tests" PYTHONDONTWRITEBYTECODE=1 \
  /home/chris/job-search-helper_old/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp="$PWD/test-work/recheck" tests/test_runtime_mapping_facts.py \
  tests/test_source_configuration_snapshot.py tests/test_source_configuration_cycle_state.py
```

The fixtures supply synthetic evidence digests and disposable SQLite stores. The existing compatibility suite uses in-memory transport fixtures. No production data, service, network, provider, Jetson or Sheets operation was performed.

[Runtime custody](/tmp/jsh-s5-runtime-mapping-fact.FNwS9PUY/src/job_search_helper/runtime_mapping_facts.py:145) · [Optional contextual lookup](/tmp/jsh-s5-runtime-mapping-fact.FNwS9PUY/src/job_search_helper/source_configuration_snapshot.py:482) · [Tests](/tmp/jsh-s5-runtime-mapping-fact.FNwS9PUY/tests/test_runtime_mapping_facts.py) · [Passing run](/tmp/jsh-s5-runtime-mapping-fact.FNwS9PUY/acceptance.log)
