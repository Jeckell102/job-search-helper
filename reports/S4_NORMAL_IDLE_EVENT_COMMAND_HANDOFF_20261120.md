# Sprint 4 ordinary Company-event operator command

The source-only candidate is `/tmp/jsh-s4-ordinary-cli.bj6uhual`. The five owned files are `job-search-scraper`, `release_admission_bootstrap.py`, `src/job_search_helper/runner.py`, `src/job_search_helper/ordinary_company_event_command.py`, and `tests/test_ordinary_company_event_command.py`.

## Operator interface

```text
./job-search-scraper ordinary-company-event admit-fetch --request-sha256 SHA256
./job-search-scraper ordinary-company-event admit-fetch --request-sha256 SHA256 --cycle-id CYC-ID
./job-search-scraper ordinary-company-event publish --request-sha256 SHA256 --cycle-id CYC-ID
```

Supply the canonical exact SHA-256 from the existing bridge receipt. The operator selects an already bridged request. An eligible outbox row alone confers no execution authority. The first form admits one queued request and freezes its observation. Both forms of admit-fetch can replay a unique consumed admission through its immutable SHA-addressed archive. The explicit saved-cycle form rejects a different cycle. Neither form refetches an existing frozen observation, rewrites a newer queue pointer, nor replays an ambiguous provider claim.

Publish requires the consumed admission, exact saved cycle, matching confirmed runtime and frozen observation. It has no fetch callback. A local-only terminal branch receives a lazy compact main-workbook reader through `remote_reader`, with `write=False, interactive=False, schemas=COMPACT_SCHEMAS, evidence_archives=False`. Its writer callback raises before constructing any Sheets writer. Publication with rows receives the separate lazy compact writer using `write=True`. The local Jobs, State and Inbox writers open only after read-only candidate checks. Lower-level exact publication, typed no-publication settlement and outcome/delivery semantics remain owned by the coordinator.

## Admission and restart

The launcher and isolated pre-import bootstrap reuse the existing scraper lease and retained-operator SQLite runtime pins. The runner verifies the inherited descriptor and canonical Jobs/State identities. The command takes the existing Jobs writer lease before opening the canonical stores and requires their persisted compact profile and exact configured Inbox workbook. It revalidates bridge provenance, current Company identity, unfinished State and mirror work, and frozen source facts before acquiring mutable repositories for the selected operation. A fully durable pending admission can restart the same cycle when its State, mirror and Company membership agree. Incomplete or inconsistent evidence before that checkpoint holds for reconciliation. A recorded provider claim without a durable result also holds.

Generic start and `--pipeline run` now hold ordinary event work before review preparation. The generic worker checks again under the existing scraper lease, and named exact sync excludes the ordinary event cycle. Explicit manual/full work keeps its existing lifecycle when the local ownership checks allow it. An explicitly reviewed exact earlier normal resume can preserve a parked ordinary event, subject to the existing queued-event provenance and disjointness verifier. The generic runner's startup bridge invocation was removed. Its terminal bridge can still write a later request under its existing boundary. The older bridge fixture and F1 dispatcher fixture that expect ordinary event acquisition through a generic `start` target must be migrated when the coordinator integrates the dispatcher. Keep the dispatcher disabled until then.

## Verification and integration

The 30 focused tests pass using offline SQLite, fake Sheets and provider fixtures. They cover narrow idle admission, held historical State and mirror work, held writer contention, malformed and foreign input, exact restart, forged frozen source evidence before writers, duplicate fetch prevention, immutable archive replay over changed pointers, pre-import lease ownership, generic entry holds, a real positive exact publication against offline Fake Sheets, and replay from the terminal publication archive. Two mocked terminal command cases verify the separate compact reader and rejection of any writer invocation. The isolated lower-level publisher snapshot predates `remote_reader`. A test-only compatibility adapter for the positive publication drops that one keyword when the lower-level signature lacks it. The current shared coordinator publisher already accepts the keyword. Integrate the five files with that publisher, then exercise actual integrated typed zero, temporary and blocked settlement to verify the lower-level result mappings and factory behavior.

Run from the candidate root.

```bash
env TMPDIR="$PWD/test-work" PYTHONPATH="$PWD/src:$PWD" PYTHONDONTWRITEBYTECODE=1 \
  /home/chris/job-search-helper_old/.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  --basetemp=test-work/final --tb=short \
  tests/test_ordinary_company_event_command.py tests/test_ordinary_company_event_fetch.py \
  tests/test_ordinary_company_event_publication.py
```

No production runtime, credentials, services, dispatcher flags, provider or Google access was used. Bootstrap tests use disposable local locks and mock process replacement.
