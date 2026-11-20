# Sprint 4 retained-event ownership and development host QA

**ACCEPT for the targeted source gate.** The previous writer-alias failure is closed on the frozen candidate. The authenticated HTTP handler blocks each direct outcome intake action and delivers the exact configured local outcome through its receipt bridge.

## Snapshot and scope

- Candidate source and tests were frozen from `/tmp/jsh-s4-receipt-candidate.i8gYgB0N` into `/tmp/jsh-s4-ownership-independent-9ozdd6_n`. The 763-file source and test inventory, content hashes and modes matched before, during and after the copy. Snapshot SHA-256 was `27ce66f27d015849ae240e5d417bae816876c2ee791a5ae1b0af87e99e09a65f`.
- The earlier verdict and original alias reproduction remain at `/tmp/jsh-s4-retained-event-final-independent-qa.md`.
- All execution used disposable SQLite state, a fixture signer, a stub provider and a fixture workbook. The independent probe blocked network connect, bind and lookup and called the actual HTTP handler in memory. The exact selected drain used real sender and receiver SQLite stores and the actual host drain and receipt bridge. Production and deployment were outside this gate, as was actual retry-successor integration.

## Evidence

- **Writer ownership.** The generic writer refused five requests that identified the same real staged event. These covered a matching canonical request and declared ID, a canonical request with no declared ID, a canonical request with a substituted declared ID, an opaque request carrying the real declared ID, and a different canonical-shaped request carrying the real declared ID. Every refusal left zero local outcomes, and no provider call occurred before the signed execution. The signed event and exact terminal replay produced one durable outcome and one fixture provider call. The candidate checks both IDs in the same SQLite transaction as the insert. See `src/job_search_helper/sqlite_repository.py:1004`.
- **HTTP intake.** Each of `ingest-scrape-outcome`, `ingest-scrape-outcome-record` and `ingest-scrape-outcome-delivery-v1` returned HTTP 403 with both an authenticated request and a request without the fixture bearer. Authenticated requests used the corresponding action payloads, including the actual sealed record for the record forms. An extra caller-supplied record on either drain was rejected. A different selected ID and a broad drain stayed held. None of these requests reached the coordinator or created intake. See `dev/wrapper-coder/tools/host_server.py:204`.
- **HTTP positive and replay.** The configured exact selected drain accepted one record. The in-process coordinator received exactly one typed receipt command containing the record loaded from the sender ledger. A repeated selected drain returned no results. The sender and receiver stored byte-equal receipt representations and equal record digests. One intake and one sender delivery were durable, with receiver status `RECORDED_NO_REPAIR`, zero repair intake rows and zero coordinator tasks. See `dev/wrapper-coder/tools/host_server.py:142`.
- **Focused regression.** 109 tests passed in 17.06 seconds across retained operator execution, outcome production and classification, host bridge, two-sided delivery and coordinator receipt. The separate independent composed probe also passed.

No blocker remains within these two targeted source boundaries.
