# Restored-stage SQLite startup fixture

2026-11-20. Independent tests-only prerequisite for Sprint 4.

**PASS for realistic settled-data acceptance by the existing bounded checker.** Ten disposable cases passed in **10.874 seconds** using native `/usr/bin/python3 -I -B` (Python 3.10.12 / SQLite 3.37.2). This is not a durable cooperative startup barrier, a live service test, deployment acceptance or a new pilot result.

Only this directory's test and report were added. The staged checker tree was not edited. No live checkout, database, service, external network, Jetson or GitHub was used. No access problem occurred.

## Executed command

Working directory: `/tmp/jsh-s4-realistic-readiness-fixture`.

```text
/usr/bin/python3 -I -B test_realistic_readiness.py
Ran 10 tests in 10.874s
OK
```

## Behavior proved for both INSTALLED and ROLLED_BACK

| Scenario | Exact observed/asserted disposition |
| --- | --- |
| Three asynchronous startup ticks, deterministic clock | Real coordinator SQLite open/close and supervision writes occurred; real Jobs/Inbox read-only opens created sidecars. After those ticks stopped, the checker waited through its next quiet interval and passed one complete fresh attestation. Virtual elapsed time: 6 seconds. |
| Three asynchronous startup ticks, real clock | The unchanged checker used its actual 1.5-second sleeps while a separate startup driver and real supervision thread performed SQLite work. Both targets passed after at least 3 seconds, with one complete fresh attestation and unchanged original logical pin. |
| Prolonged churn | Forty-six actual SQLite supervision ticks advanced the checker's unchanged deadline arithmetic to 69 virtual seconds. No quiet interval was accepted and no complete attestation ran. Exact result: `Restored service did not reach a stable protected checkpoint`. |
| Protected logical evidence changed during startup | After two actual ticks a synthetic protected manual-choice row was added. At the first quiet complete attempt, the original witness raised `protected state differs from private pin`. Exactly one attempt ran; the checker did not retry that difference into acceptance. Original pin bytes remained unchanged. |
| Churn after the first full logical proof | A real supervision tick ran at the first launch-check boundary before continuity finalization. The first proof failed physical continuity. The checker constructed a distinct new continuity object and reran the full attestation; the second passed after stabilization. Process/listener/route/launcher boundaries were exercised again; no partial first-pass proof was adopted. Virtual elapsed time: 4.5 seconds. |

Each scenario runs once against the fixture's after-source endpoint (`INSTALLED`) and once against its before-source endpoint (`ROLLED_BACK`). The real `verify_host_path` selects and checks the correct endpoint bytes, owner and mode.

The fixture explicitly asserts coordinator WAL creation followed by removal at connection close and initial Jobs/Inbox read-only WAL creation. It retains real file metadata comparisons. No sidecar is excluded, no witness failure is suppressed, and no baseline is resealed after the startup activity.

## Fidelity and boundaries

The tests execute the exact staged `wait_for_restored_stability`, `host_checkpoint.attest`, `ProtectedContinuity`, full original logical witness and physical snapshot. They reuse the staged synthetic protected-state fixture to create actual State, Jobs, Inbox, session and coordinator SQLite files; all contents are invented fixture data.

They also execute the actual isolated `CoordinatorSupervision.start()`, first/repeated `tick()`, `_record()` and `external_retention_snapshot()` against those files in a real thread. The small fixture Store repeats the reviewed connection-through-close contract. Startup scheduling uses a queue to make interruption cuts deterministic; two additional cases retain the real clock and unchanged 1.5-second wait interval. The remaining cases accelerate only the checker clock, not SQLite operations or the worker thread.

The complete Coordinator scheduler, native host process and real service are not launched. Native unit, listener, process, alternate-route and owner observations are explicit fixtures; launcher probing is a callback whose boundary can inject the late real SQLite tick. Thus the suite proves how the bounded checker handles real asynchronous storage behavior, not that an actual native listener or process is currently healthy. Existing native/owner/source acceptance remains separate.

The original pin bytes are checked after every scenario. Settled cases independently rerun the original full logical witness. Prolonged churn leaves the same logical data but correctly fails physical stability. A changed logical row remains a failure even after all physical activity stops.

No persistent barrier was added. Real future background activity can still overlap a later check. Success requires an actually complete stable measurement interval; continuous churn still holds. The permanent cooperative startup/serialization mechanism described in `/tmp/jsh-s4-wrapper-readiness-design.md` remains separate work.

## Exact pins

The staged source pins were checked before execution and rechecked afterward. All 11 Python modules embedded in the reviewed archive also match the corresponding staged source files byte-for-byte.

| File | SHA-256 |
| --- | --- |
| New `test_realistic_readiness.py` | `0f2796e0a471069966b1903529e913418601bf19744b6e9238ef039ac4f2d43b` |
| Staged `host-check.rollback-reviewed` | `b96589be7d70647187eb61e41f9cc5beec08e6c4e0c2e982c13862dabe5bda98` |
| `host_check_main.py` | `562c0cd36119f0575f9b87f3ec5a59287ebcb35ff479b8b06df751061a220ab9` |
| `host_checkpoint.py` | `fe5ac8bed3ab1e88ff645859ba6f156229694643d3b3549415748c8952016e43` |
| `protected_state.py` | `9c317392293dd245fab3a73c24a4075d9f65ca5b4fe53378f35df710dce446e3` |
| `protected_continuity.py` | `66b8334311cb2fd593947548ff47137bb0fa9a6a3b408d6b2d7b0da31af0e9ca` |
| `physical_protected_witness.py` | `546b4fdee2b2768ff01086e8dc962408563c83657d68fe736220a8f14fcc4201` |
| Existing `test_protected_state.py` fixture | `042074ae118ae3d19786065d5c30e759e3e70657756ea1660335c3a304c6e564` |
| Isolated `coordinator_supervision.py` | `5a6a943a16c9bc7bb2b32fe0c4cea325abf2aace2bb4ead42547dac6454d56f3` |

Checker source/archive root: `/tmp/jsh-s4-restored-witness.KT8wKPcI`.
Supervision source: `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/tools/coordinator_supervision.py`.
