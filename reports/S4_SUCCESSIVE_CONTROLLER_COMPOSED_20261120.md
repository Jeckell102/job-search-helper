# Independent composed successor-guard fixture

Verdict: PASS for the bounded disposable Controller composition below. This is source/test acceptance only; no deployment or native host acceptance is claimed.

Completed 2026-11-20 22:17 Eastern (2026-11-21 03:17 UTC). Command:

```text
/usr/bin/python3 -I -B /tmp/jsh-s4-successor-guard-composed/test_successive_controller.py
```

Result: 1 test passed in 20.248 seconds. No test failure or source repair was needed. The test is a multi-transition scenario, not a single unit assertion.

## What ran

The earlier accepted disposable harness was copied as test infrastructure, with four harmless synthetic Python endpoints: one package module plus the three permitted wrapper endpoints. No application code was imported or run. Its ordinary subprocess Controller, installer, verifier, file locks, journals, source replacement, import guards, and physical package exchange ran normally. Host/service/alternate-checkout observations were substituted fixtures.

1. An exact historical predecessor Controller performed CLI install and rollback. Its final Controller phase was RELEASED, target and installer receipt phase ROLLED_BACK; the original source package was restored.
2. A separate successor capsule was created with its own hold ID, candidate, plan, handoff, checker, policy generation, policy file, installer state directory, and locks. Both exchange policy files and their actual digest pins existed. The predecessor's restored-exchange observation was explicitly synthetic fixture evidence.
3. The frozen successor Controller read the actual predecessor journals and validated the handoff. It wrote a real durable CLOSING record. The test killed only that fixture process before host unlink and package exchange.
4. At that cut, the recorded inherited guard matched the exact prior directory identity; the original package remained canonical, and the parked guard directory and marker identities were unchanged. The successor state directory, installer lock, and Controller lock had distinct physical identities from the predecessor.
5. A fresh normal CLI invocation resumed the successor installation to RELEASED/INSTALLED. Repeating install preserved the terminal journal bytes.
6. The successor rolled back to RELEASED/ROLLED_BACK. Repeating rollback again preserved terminal journal bytes. Source, unscoped fixture files, and fixture service configuration matched the original harness's acceptance checks.
7. The inherited guard directory and marker identities remained exact after install and rollback. All 25 predecessor bundle files retained their device/inode, mode, link count, and content hash throughout the successor operation. That includes both original journals, tools, candidate, checker, and exchange evidence.

## Evidence

- Test: `/tmp/jsh-s4-successor-guard-composed/test_successive_controller.py`
- Run directory: `/tmp/jsh-s4-successor-guard-composed/run.bbc9olna`
- Scenario: `/tmp/jsh-s4-successor-guard-composed/run.bbc9olna/test_successor_closing_restart_install_and_rollback_preserve_predecessor.cgm4u0eg`
- Scenario evidence includes `composed-result.json`, `invocations.jsonl`, `atomic-faults.jsonl`, `attestations.jsonl`, `routes.jsonl`, and separate complete `capsule/` and `successor/` journals.
- Exact source pins: run `pins.json`.

| Input | SHA-256 |
|---|---|
| Frozen successor controller.py | `927063a9797c121a8c6e4b73011a79ea2874d72427c64387e969355503b092eb` |
| Frozen successor gate.py | `7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537` |
| Both installer.py | `796e8b04cca48c7641c45480611ab43f2d19a2a96da9dc9a08d548d029fc1ee4` |
| Both verify_hold | `fc7c2c717877d8da060d2b1f0981af335dcf35b256bf3bf578c79e3f674183f6` |
| Historical predecessor controller.py | `e5a93fce3b92c1a2a4b3610bb6fa2b68b25436f92da57fc8abba726dfcd9e76d` |
| Historical predecessor gate.py | `93d195ad013b2bf9cf02070000742c5d0f7decd3ac34aa0fa43f47c37d6846bb` |
| New scenario test | `50ca9f0083bb58671bffd4d4e9055e2474cc98d15b16c514443a667946a520eb` |
| Copied base harness | `bde564333faddf420533c1ced63851c7772fb3881d1ff17e5c315de4fa28788b` |
| Adapted fixture-only host stubs | `d8379aa4639e48be5c848f2aea0db73c8088d5da9917d6c7afd7514732f900b5` |

The source `preinstall_abort.py` pin `5d4c94876a2b9325fc5f7f22bb4e8099a973ff66a67e642ef3ac7b56743562ea` was checked against the frozen stage but that module was not executed in this composed test.

## Limits and ownership

No production files, DBs, services, network, Jetson, or GitHub were accessed. All created artifacts are under this tests-only directory. The frozen staged source and the original harness directory were not edited.

The earlier harness's host/systemd/consumer/listener checks are simulated, not real host observations. The protected baseline and restored alternate-exchange attestation are fixture inputs. This test does not prove native listener ownership, real alternate checkout exclusion, actual SQLite quietness, private capsule preparation, preinstall-abort refusal receipts, or production safety. Those stay separate acceptance gates. It specifically adds successive real Controller/installer/gate composition, durable pre-exchange binding, crash recovery, terminal replay, and predecessor preservation evidence to the maintained and independent boundary tests.
