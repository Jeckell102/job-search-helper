# Sprint 5 runtime mapping fact custody repair

The three independently reproduced custody failures are covered by passing offline regressions. The isolated repair candidate is `/tmp/jsh-s5-runtime-mapping-fact-repair.jQCMdWmA`. The original candidate at `/tmp/jsh-s5-runtime-mapping-fact.FNwS9PUY` retains the SHA-256 pins recorded by independent QA. [Independent findings](/tmp/jsh-s5-runtime-mapping-fact-independent-qa.md)

## Repair and evidence

- State and Jobs are opened as a managed pair. At open, the module verifies an unaliased, single-link canonical file, identifies the one new matching Linux file descriptor, and binds the exact SQLite connection and open-file identity. Custody checks reverify that descriptor, SQLite's main path and the current canonical inode, and read the workbook ID from `main.meta`. Physical replacement of either State or Jobs stopped both first insert and replay through the old handle. A fresh managed reader also rejected inheritance of an already-recorded receipt when either store changed. Workbook drift stopped reads and replay even with the original value available in a temporary `meta` table.
- The durable slot catalog, lookup, creation and insert all use SQLite's `main` schema. An empty temporary slot could neither hide the durable receipt nor receive a successful substitute. Contextual custody also refuses temporary relations that could shadow the repository's Company authority tables.
- Contextual packaged fallback validates the exact frozen source configuration, current qualification and sealed evidence group. An alternate mapping for the same cycle and Company stayed available through the unchanged three-argument package lookup while contextual lookup returned no match. A matching packaged fact remained available through a managed read-only pair without creating the runtime table or changing either main database. Partial sealed evidence stopped contextual fallback.
- Existing exact replay, source and qualification drift, foreign cycle and Company, copied State, payload substitution and rollback regressions passed. A fresh managed writable scope also persisted and reopened evidence with the normal State and Jobs handles already open in the same process.

## Caller contract

Under the existing ordinary scraper and Jobs writer holds, open `open_runtime_mapping_stores(state_path, jobs_path, workbook_id, writable_state=True)` around persistence. Use its yielded State and read-only Jobs handles with `persist_runtime_mapping_fact(..., cycle_id=..., company_id=..., fact=...)`. Use the default read-only managed pair for `read_runtime_mapping_fact` or for `mapping_fact_by_id(cycle_id, company_id, fact_id, state=state, repository=jobs, runtime_binding=...)`. Use the exact saved ordinary-cycle runtime binding. Existing runner handles can stay open for their own operations. Keep their transactions out of the managed write scope and close the managed scope before releasing the holds.

The proof depends on Linux `/proc/self/fd` and one attributable descriptor per managed open. Missing or ambiguous descriptor evidence stops the operation. Managed path detection is scoped to the established, cooperative lease and same-process open discipline. It does not provide protection against a separate actor that can arbitrarily replace files during the transaction. A legitimate database replacement also cannot inherit the old inode-bound receipt. The existing verifier or a future authorized producer must supply actual verified fact evidence. Engine and runner integration, live observations and automatic promotion remain outside this source candidate.

## Exact owned files

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/runtime_mapping_facts.py` | `3d6e0f558cc3cffee5d50571c18c150094596f9bcf9d4c6018a9fcdb3c54f073` |
| `src/job_search_helper/source_configuration_snapshot.py` | `fdd8b7049c2920001b6925139d9e625a8a0cb55f22e6123812034be95d9a6ef0` |
| `tests/test_runtime_mapping_facts.py` | `981964c421d54e8459addda42a73e080d77ff628106c0d3f459d4a9fc1c11689` |

Content comparison to the original candidate found changes only in the three paths above. Production source, data, services, providers, Sheets and Jetson were untouched.

## Test run

**55 passed in 4.88 seconds** using disposable local SQLite databases and synthetic evidence. From the repair candidate, with an unused fixture basename, the test command was

```bash
env JOB_STORAGE_BACKEND=sqlite PYTHONPATH="$PWD/src:$PWD/tests" PYTHONDONTWRITEBYTECODE=1 \
  /home/chris/job-search-helper_old/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp="$PWD/test-work/final" \
  tests/test_runtime_mapping_facts.py tests/test_source_configuration_snapshot.py \
  tests/test_source_configuration_cycle_state.py
```
