# Independent QA for the site journal adapter

2026-11-20 16:36 EST

**ACCEPT for source composition.** No required source repair found. Host activation and a real policy remain pending.

- The archive requires both the adapter and controller sources. The parser reconstructs the pinned policy path and digests, generation, positive release UID, and ordered canonical/parked pairs. The adapter calls only the controller's read-only `witness("closed")` and checks UID, control directory, policy SHA-256, generation, intent SHA-256, phase, absence of terminal proof, and the exact ordered pairs. `site_bundle.py:10-21`, `site_policy.py:65-78`, `alternate_exchange_witness.py:29-42`.
- The API independently validates the sealed policy, physical path and lock pins, mount namespace, journal intent and completed count, and current sentinel and parked original placement. The witness opens a shared read-only lock, which is released when the observation returns. `host_exchange.py:170-208`, `host_exchange.py:257-320`, `host_exchange.py:344-357`, `host_exchange.py:452-459`.
- The site requires the exchange's canonical roots to equal its unique approved alternate inventory, requires its release UID, and refuses cover mixing and production overlap across canonical, parked and control paths. It scans the parked routes alongside canonical and production routes, and checks closure and the process drain twice before returning `verified`. `host_checkpoint.py:295-328`, `host_checkpoint.py:371-425`.
- Independently ran the existing adapter module as UID 1000 using a fresh pytest directory under `/tmp`. All 11 passed in 0.81 seconds. The cases include journal payload/inode/mtime/ctime preservation, foreign identity, reordered paths, interrupted close and replay, completed restoration, a substituted parked directory, a process in the parked checkout, incomplete inventory, and policy archive round-trip. `test_alternate_exchange_witness.py:33-130`. The coordinator separately reported its 82-test suite passing.

Before compiling a real site policy, establish continuous exclusive control of the approved policy, control directory and canonical/parked routes, including their writable parents, and obtain a successful close return or acknowledged close recovery. Persisted `closed` can be read after journal replacement but before the directory sync is acknowledged. The two read-only samples establish observed closure and do not establish continuous exclusion between samples or after return. Maintain the operating boundary through the release and until authenticated terminal evidence permits restoration. `host_exchange.py:333-342`, `host_exchange.py:395-450`, `host_checkpoint.py:393-425`.

QA was local and did not create a real policy or modify live systems.
