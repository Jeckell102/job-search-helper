# Sprint 4 selected pilot outcome readback review

**ACCEPT** for the pinned staged helper as read-only review evidence for one selected outcome. The caller must already own the scraper and writer leases and supply the approved compact Jobs repository, runtime binding, and pilot identifiers. The resulting digest is an input to separate one-address delivery review. It grants no delivery authorization.

## Reviewed pins

- `/tmp/jsh-s4-company-intake.R5s9VWJ6/pilot_outcome_readback.py` — `a06aa6e2541d42ff8f4b763c0345adb58fafcc0c5932f8a253a84dece679f8a1`.
- `/tmp/jsh-s4-company-intake.R5s9VWJ6/test_pilot_outcome_readback.py` — `a935e46fd31cce583a64c55c601dbe02f8a610f2aff687d9d347e753c278dbf7`.
- Dependencies and adjacent tests from `/tmp/jsh-s4-dispatch-binding-qa.i45G33KN/{src,tests}`.

## Findings

- The helper checks ready, read-only compact Jobs and holds any active journal or pending request, including a pending path that is a symlink. It requires the exact archived settlement and consumption for the request SHA and reservation, plus the approved runtime binding, event, company, source revision and blocking cycle. It holds verified-zero and other nonconfirmed settlements before sender lookups. `pilot_outcome_readback.py:15–39` and `retained_operator_journal.py:254–318`.
- The retained outcome reader reopens the original consumed request and exact independent consumption receipt. It verifies signed event binding, acknowledged current source, complete inventory against the saved plan, and confirmed terminal evidence against retained session, local publication, exact acknowledgement and first-pass release evidence. It independently classifies the selected facts and accepts the immutable row only if its complete canonical serialized payload and indexed metadata match. The helper further requires a current source, successful complete classification, and exact retained event, request, company, source, derived cycle and reservation identities. `pilot_outcome_readback.py:41–49`, `retained_event_outcome.py:23–84,255–302` and `retained_work_publication.py:78–145`.
- Sender readback queries the canonical consumer for one exact outcome ID. Its read-only preflight validates the canonical record, public schema and any existing attempt or receipt. Its digest comes from the exact saved sender payload and is returned with the publication and workbook fingerprints. A caller can distinguish ready evidence from an existing attempt or terminal receipt. `pilot_outcome_readback.py:51–65`, `scrape_outcome_delivery.py:68–110` and `sqlite_repository.py:1116–1128`.
- The call path uses local reads and no sender drain, remote reader, provider request or application writer. Jobs and retained session SQLite connections open in read-only mode. The supplied fixture compares unchanged State, Inbox, Jobs and retained session database files, checks repeatable evidence and forbids connection attempts and sender drain. The helper relies on the caller to hold the leases through readback. It does not reread Sheets or start a live delivery attempt. `sqlite_repository.py:60–95`, `retained_operator_run.py:33–45`, `test_pilot_outcome_readback.py:13–55`.

## Tests

- Three focused cases passed. Confirmed nonempty publication returned the exact stable sender-record digest, verified zero was held, and nonmatching source or pending request was held.
- Three adjacent retained-operator regressions passed. These exercised confirmed publication and exact replay, selected sender receipt, and stale-source delivery hold.
- All runs used disposable fixtures. The source review and report exercised no live services, live application state, or network.
