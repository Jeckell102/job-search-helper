# Sprint 5 runtime custody SQLite follow-up

The separate custody candidate `/tmp/jsh-s5-runtime-custody-v3.4smZRC32` passed **63 focused tests**. The unchanged Engine checkpoint pin combined with this custody repair in `/tmp/jsh-s5-checkpoint-custody-composition.y8voh14Y` passed **77 focused tests**, including all 14 Engine composition cases. Both original source pins remain available for independent comparison. [Independent custody findings](/tmp/jsh-s5-runtime-mapping-fact-repair-independent-qa.md) · [Engine pin and operation](/tmp/jsh-s5-runtime-sealed-checkpoint-handoff.md)

## Exact repairs

- Direct and contextual reads, first insert and replay require idle State and Jobs handles. They refuse pre-existing explicit transactions before reading authority. They also refuse an unfinished SQLite statement that can hold a WAL read snapshot while Python reports autocommit. The exact write transaction still performs its private durable readback. The regression covers stale workbook identity during first insert and replay, deleted State cycle visibility, and both stores holding stale data through an unfinished cursor. Public refusal leaves the caller's transaction or cursor intact. [Guard](/tmp/jsh-s5-runtime-custody-v3.4smZRC32/src/job_search_helper/runtime_mapping_facts.py:145) · [Regression cases](/tmp/jsh-s5-runtime-custody-v3.4smZRC32/tests/test_runtime_mapping_facts.py:280)
- The opened handle guard refuses attached SQLite databases on either store. Jobs lookup also requires both exact Company tables in the main catalog and retains the temporary-relation fence. A fixture removed both main relations, demonstrated that the unqualified repository method obtained Company data from an attachment, and verified that all public custody routes refused it. The missing-main case stayed held after detaching. Restoring both main relations allowed the original exact receipt to replay. [Opened handle guard](/tmp/jsh-s5-runtime-custody-v3.4smZRC32/src/job_search_helper/runtime_mapping_facts.py:112) · [Attachment regression](/tmp/jsh-s5-runtime-custody-v3.4smZRC32/tests/test_runtime_mapping_facts.py:348)
- The statement-idleness proof uses SQLite's `sqlite_stmt` virtual table. The fixture interpreter uses SQLite 3.37.2 with `ENABLE_STMTVTAB`. A missing or inaccessible statement-status table fails closed. Linux descriptor proof and existing cooperative scraper and Jobs writer leases remain required. [Capability refusal fixture](/tmp/jsh-s5-runtime-custody-v3.4smZRC32/tests/test_runtime_mapping_facts.py:386)

## Source pins

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/runtime_mapping_facts.py` | `94b4d0d8b1bfc3569af59931c9916241799d4872908313c5085bf211e45644d4` |
| `tests/test_runtime_mapping_facts.py` | `dbaaa96a156639219e6982942c4144bbe596bc2bc706977a8899656faccfff29` |
| `custody-repair.patch` | `d1fc466b9229860211ad0284f27afdcd55e01aa68a99ba4d892c1c753c5677e8` |

The patch passed `git apply --check` against the first repaired custody candidate `/tmp/jsh-s5-runtime-mapping-fact-repair.jQCMdWmA`. The combined fixture uses the verified Engine SHA-256 `78d4a1d45300c3347a81834c270dabd5f606bf188941a096c172807a391794dd`, byte-identical to its separate pin. [Exact source and test patch](/tmp/jsh-s5-runtime-custody-v3.4smZRC32/custody-repair.patch)

## Verification command

Run from the combined fixture. Omit the first test file for the standalone custody run.

```bash
env JOB_STORAGE_BACKEND=sqlite PYTHONPATH="$PWD/src:$PWD:$PWD/tests" PYTHONDONTWRITEBYTECODE=1 \
  /home/chris/job-search-helper_old/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp="$PWD/test-work/final" tests/test_runtime_sealed_checkpoint.py \
  tests/test_runtime_mapping_facts.py tests/test_source_configuration_snapshot.py \
  tests/test_source_configuration_cycle_state.py
```

The runs used disposable SQLite databases, synthetic evidence and the Engine fixture's in-memory workbook. No production source, services, live provider, Sheets, Jetson or deployment work was performed.
