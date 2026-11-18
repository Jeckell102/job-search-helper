# Independent final staged QA v3

**PASS for the exact staged candidate. A new paused rollout and independent installed-state PASS remain mandatory.** This reviewer is independent of implementation. No production source, database, service or inference endpoint was changed or invoked by this reviewer. This decision does not certify installation, campaign activation, live scraper validation, generated-wrapper installation or complete job downloads.

## Exact candidate and bounded change

Canonical manifest `candidate-release-v3-manifest.json` digest: `245d082e77390f61675892c4ee333a1043aed309242eb514a5ddfad6bc0a0ab3`. Complete clean release `/tmp/wrapper-final-v3-pc17zqkl/release` digest: `ef40c3b7adddfbfec20220e8b625832bb15513b1412944bd36065831f29e4a0d`.

I independently verified all 67 source files, all 682 prerequisites, complete clean-release inventory and metadata, and every migration input. Compared with v2, only `host/coordinator_inference.py` changed and `host/test_startup_session_noop.py` was added. Deployment/rollback code, migration implementation and inputs, database precondition, runtime prerequisites, all other source and regression tests remain identical. The full current host hash map exactly matches independent startup acceptance. Evidence: `final-staged-v3-independent-binding.json`.

I read the original final plan, v2 staged report and machine-readable evidence, completion audit, installed startup failure and independent startup acceptance. The actual v2 startup failed its mandatory database equality gate: recovery added a false session field to 111 untouched tasks. Automatic rollback was independently verified; that is safety evidence, not installed acceptance. Preserve `FINAL_QA_FAILURE_20261118_INSTALLED_STARTUP.md` and `installed-v2-rollback-independent.json`.

The inspected production diff requires a nonempty matching session ID and an explicitly true open-session flag before closing, while retaining the pending DISPATCHING/UNCERTAIN barrier. Missing, mismatched and closed sessions cannot rewrite tasks. Genuine resolved open sessions close once. No installed comparison was weakened.

## Acceptance across the seven original groups

| Group | Staged result and evidence |
| --- | --- |
| 1. Membership, pause and isolation | PASS; unchanged source, assertions and exact-102 migration inputs retain v2 acceptance; complete current host suite passes. |
| 2. Atomic control modes | PASS; unchanged competing mode/failed-start regressions retain v2 acceptance and pass in the current full suite. |
| 3. Canonical identity and retry lineage | PASS; unchanged identity/registry regressions and exact-102 migration evidence remain bound. |
| 4. Exact scope and immutable acceptance | PASS; unchanged guard/assertion implementation and real sandbox acceptance evidence remain bound; refreshed two-company rehearsal passes. |
| 5. Inference stop, budgets and recovery | PASS; fresh independent startup acceptance verifies the repaired no-op case, real session closure, uncertainty retention, no replay and preserved counters; full host suite passes. |
| 6. Durable completion and truthful status | PASS; unchanged status repair binding plus current focused/full tests and refreshed rehearsal retain honest terminal totals and explicit next gates. |
| 7. Ownership, reproducible release and recovery | PASS in staging; deployment and ownership bytes are unchanged from independent 27-test acceptance, complete v3 assembly matches, and independent startup no-op acceptance closes the newly discovered staged gap. Actual installed equality remains pending. |

Fresh clean-release host execution passed **287/287 tests in 26.725 seconds**, with exit zero confirmed by the coordinating reviewer and the final log independently inspected here (`final-v3-host-suite.log`). Independent startup verification passed **44/44 focused tests in 6.412 seconds** (`independent-startup-noop-tests.log`), including inference storage/reservation, resilience and healthy in-flight status. Counts overlap and must not be added as unique tests.

The independent verifier copied the actual disposable migrated rehearsal database using a read-only source connection. Its **111 tasks and 102 registry rows** were preserved across **two recoveries**, with exact all-table and raw task JSON equality and **zero SQL mutation statements** each time. Controls stayed OFF, pilot unset and integrity `ok`. Source hashes exactly match this release. Evidence: `INDEPENDENT_STARTUP_NOOP_ACCEPTANCE.md` and `independent-startup-noop-verification.json`.

All v2 evidence hashes were rechecked unchanged except the intentionally refreshed two-company rehearsal. That fresh rehearsal passed with separate workspaces, pause/restart, real guarded tests, and `DRAINED_WITH_EXCEPTIONS`: one offline-ready company awaits live validation and one blocked company requires clarification. Four model callbacks are simulated. It establishes no live or installed success. Unchanged exact-102 migration and same-process parity evidence remain applicable because migration implementation, inputs, expected original database digest and prerequisites are identical. Redundant unchanged large suites were not rerun by this reviewer.

## Next mandatory gate

Deploy only the exact v3 manifest through the reviewed paused rollout, retaining backups, rehearsal, ownership journal and rollback. Independently verify installed source/forwarder parity, healthy single scheduler ownership, exact migration results, complete unchanged logical database from stopped verification through startup, controls OFF, pilot unset, no active work, and integrity. Then verify final GitHub delivery parity. Any candidate change invalidates this staged PASS; any installed failure reopens acceptance and requires rollback or a documented safe paused state. Historical completion-audit labels require reconciliation and cannot substitute for these gates.

Machine-readable decision, bindings and evidence hashes: `FINAL_STAGED_QA_V3.json`.
