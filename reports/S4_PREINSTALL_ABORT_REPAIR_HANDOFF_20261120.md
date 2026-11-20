# Sprint 4 pre-install alternate-checkout recovery repair

2026-11-20 17:57 EST

**Staged and verified in disposable fixtures.** Production enrollment, any real install or restore, and separate release acceptance remain with the root coordinator.

- Stage and runbook are at `/tmp/jsh-s4-preinstall-abort-repair.KmZxSmEx` and `/tmp/jsh-s4-preinstall-abort-repair.KmZxSmEx/README.md`.
- The source response addresses `/tmp/jsh-s4-preinstall-abort-independent-qa.md` and adds the requested explicit never-invoked and durable supervised launch paths.
- `preinstall_abort.py:142` binds the original physical capsule, candidate and canonical source, plan and tools, approved checker/site policy and protected pin. The enrollment binds application and controller lock identities plus a separate private custody directory and lock at line 181.
- `preinstall_abort.py:253` writes the launch intent before spawning the original controller and captures its boot, PID, start ticks, raw stdout/stderr and direct waited status. Each terminal child has an exit record. Only the exact preflight refusal and the original empty private transaction directory can produce the separately approved refusal record.
- `preinstall_abort.py:293` verifies the logical baseline with the original approved checker archive in a sealed descriptor and an isolated interpreter. The original real scraper lease is authenticated in the verifier, and all originally pinned leases are held and rechecked with the refusal boundary. The restore callback runs inside the original exchange lock and refusal evidence is cross-checked against the private original transcript at line 308.
- `preinstall_abort.py:396` and line 400 provide the separately approved never-invoked route. Both require a pristine original attempt directory and an absent installer transaction. Even an ambiguous spawn attempt leaves durable launch evidence that excludes this route.
- Recovery reuses the same approved plan for the same closed generation, intent, policy and ordered paths, including after a simulated exit following the first restore swap. Any existing controller journal requires the recorded joint-controller recovery. A marker, sealed wrapper image, hold sentinel/drop-in, staged or loaded guard, or changed transaction directory blocks this contingency.

## Verified results

Run from the stage:

```bash
python -B -m pytest -q -p no:cacheprovider test_preinstall_abort.py test_host_exchange.py
```

Result: **48 passed in 73.00s**. The staged original controller ran against a disposable capsule and exited at the checker preflight boundary. Tests invoked the original approved protected-state implementation against a real disposable SQLite baseline, rejected logical drift and a missing real scraper lease, rejected copied or changed identities and transaction lookalikes, verified both seal-side refusals, exercised interrupted replay and separate approval types, preserved waited output for status 0 and 7, and refused the never-invoked route after uncertain spawn. The external host attestation intentionally refused in the fixture. A production-policy attestation, successful production install, production restore and runtime performance were unmeasured.

## SHA-256

```text
28a5bd750148eb7cb892a8a6552550ba9d4afc9bfbca0b146ba56f97c39f77b4  preinstall_abort.py
2a0a909dce78b68560e45318c621933c79bfbb84670cddafcae5623f6dd0aee0  test_preinstall_abort.py
19c3d18efab978f8e676af0e15056fc3547977c11364a1e4ac702d071d809741  README.md
a4a45a1de5ad9076d223ef3e535cf1c8a4d73e96142ce7bb315959a3f62cd786  controller.py
93d195ad013b2bf9cf02070000742c5d0f7decd3ac34aa0fa43f47c37d6846bb  gate.py
796e8b04cca48c7641c45480611ab43f2d19a2a96da9dc9a08d548d029fc1ee4  installer.py
8168d900979d68aebc950d7bb8495705a5190368e8ca3ac932a7da4d4c7dfb1f  host_exchange.py
4a0bc5c54ec3bc9c3695314e6c84eae7e04ba19a84ed8842e2d35838414426da  test_host_exchange.py
```

The process proof depends on exclusive custody and launch through the supervisor. A supervisor interruption without a waited exit is an uncertain attempt even if the process may have exited. Keep the durable evidence and original closure for investigation. No production writes, service changes, GitHub activity, or Jetson changes were made.
