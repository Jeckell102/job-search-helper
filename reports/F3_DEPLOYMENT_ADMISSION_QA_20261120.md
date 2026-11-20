# Sprint 1 admission guard QA

**Candidate admission and recovery: ACCEPT in the disposable rehearsal. Production deployment: HOLD pending host verification.**

Seven independent tests passed against the revised controller. The fixture used the production-matched 13-file rollback snapshot, accepted 13-file candidate, actual shell launchers and bootstraps, an editable console, kernel file locks, a disposable SQLite jobs database, and a simulated service manager and host attestation. All 17 controller tests and all 11 installer tests also passed. No production service, source, credentials, job data, or workbook was touched.

## Observed boundaries

| Boundary | Independent observation |
| --- | --- |
| Process exits before installer handoff | Marker and service hold persist. The canonical sentinel blocks direct startup and the bootstraps refuse admission. |
| Process exits immediately after real package exchange | The journal remains at `PUBLISHING`. The canonical package matches the complete target and the zero-byte extension blocks ordinary startup, including production-first imports with a fallback on the path and the editable console. The marker and service hold remain in force. |
| Canonical guarded verification is refused | The extension remains in place and normal imports stay blocked. The marker and service hold remain in force. |
| Process exits immediately after extension unlink | The journal already records `ADMISSION_READY` and the guarded canonical verification has passed. Direct help opens against the verified full package. The bootstrap and affected services remain held. A retry runs the admitted probe and completes release. The same boundary was exercised for rollback. |
| Admitted probe is refused | Direct startup remains open against the verified target. The controller retains the marker and service hold until a retry passes. |
| Extension is missing or replaced before admission | Recovery refuses both a missing extension and a matching empty replacement with a different inode. It preserves the recorded phase, marker and existing files. |
| Rollback is selected during guarded publication | A crash after re-parking leaves the original extension in the parked package and the sentinel blocking canonical startup. Replay rejects a switch back to install, restores the exact original source and completes guarded admission. |

Ordinary install and rollback also completed, and terminal replays returned their original result. Fixture non-scope package file contents, modes and inodes, the SQLite jobs database and the next-scan control were preserved. Process-exit injection exercises the actual exchange and unlink boundaries, including exit before the unlink's directory sync. Power-loss behavior remains untested.

I separately called the shipped host check's launcher probes on both pinned source versions in a disposable checkout. The two actual root wrappers and the temporary editable console refused ordinary help when parked or guarded canonical, and accepted it after admission. The explicit source-loader check succeeded on the retained package while ordinary startup was blocked.

## Remaining host gate

The empty extension closes fresh stock CPython imports that resolve the canonical package through the tested routes. A resident interpreter, an explicit file loader, an alternate-first checkout and a separate publisher can bypass that package lookup. Production preflight still needs to establish coverage and durable exclusion of the applicable host routes and source writers, confirm the effective interpreter and environments, and run the complete host attestation. The deliberate admission point is the extension unlink after guarded canonical verification. Bootstrap and service admission continues to depend on the final admitted probe.

The earlier [preflight](/tmp/jsh-s1-maint/QA_PREFLIGHT.md) and [recheck](/tmp/jsh-s1-maint/QA_RECHECK.md) reports remain intact. The [independent test suite](/tmp/jsh-s1-maint/test_end_to_end_qa.py) and [host route decision](/tmp/jsh-s1-maint/ROUTE_DECISION.md) document the rehearsal and its limits.
