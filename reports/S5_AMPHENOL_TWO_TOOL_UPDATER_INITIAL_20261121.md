# Independent two-tool forward updater review

**REJECT on updater `21b605101f9716248cc9bd86142eb64963e01fa05f242f872c2b07f91f9f46cf`.** The three maintained fixtures passed. An independent fixture reproduced a failed rollback after the replacement host starts with a wrong loaded hash. The rollback stop callback stops the host and then reports a lost response. `deploy_two_tool_forward.py` lines 305–310 exit before consulting the independent stopped probe. Both candidate files remain installed, the host is stopped, and there is no terminal receipt. The normal apply entry requires both predecessor images and unused backups, so repeating it cannot recover this state.

Catch an exception from the rollback stop callback long enough to consult the same exact stopped predicate used after initial stop failure. If it proves the unit stopped, continue the existing reverse-order restoration and predecessor readiness readback. If it cannot prove that state, preserve the hold before any source write.

The reviewed forward path writes Store then host under the existing deployment lock and compares the before and after loaded hashes. Its rollback is ordered host then Store, followed by an original-hash readback. Both receipt types carry the fixed current and historical predecessor pins, which the apply path cross-checks against the injected terminal and exchange evidence. The eight unaffected paths are checked before apply and before restart. The single service is the existing wrapper host. Actual loaded identity, restored exchange and native authority are outside this disposable review.

| Artifact | SHA-256 |
| --- | --- |
| Maintained tests | `0ab6e58b6260918ddf409af778239248e9ac0689d55561f530e5f1730b2ee697` |
| Maintained run | `c2d64d41edcb4d9a0b7a81fcc964ceb8d2b7d73d7d92491bb17f24d0bbaea6d3` |
| `tests/test_independent_rollback.py` | `23ea7c001f16a8a8d8e35674dffe99b9685e84dac2b0a97eda6c70ed58494cd2` |
| Independent failure | `4523ddabb0103b42faa2d27b17fb23bfff5da256550af38c0f475f943059ca84` |
