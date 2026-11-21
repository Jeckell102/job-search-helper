# Corrected scoped repair retry admission replay

**ACCEPT** the scoped source correction for replay admission.

- `/tmp/jsh-s6-retry-admission-replay.mh7czve4/src/job_search_helper/repair_retry.py` SHA-256 `1e3636e206724ee535699f16d4cbf82ac8ca28f047eeb537ff6167be0585555c`
- `/tmp/jsh-s6-retry-admission-replay.mh7czve4/tests/test_repair_retry_admission_replay.py` SHA-256 `f0f4dc0f518c37c104078c064cd6f6aac1b125afd66034ebbe6f70b903a1664f`
- Unchanged independent `test_independent.py` SHA-256 `6747251e2d4eb5281f0e093670548d1a3e95aef98bb2dc1d14bd4620c8135aae`

All 20 tests passed in 14.07 seconds, comprising 12 maintained tests and the eight original independent cases. The unchanged missing and foreign installed runtime, competing retained owner, and truncated intake cases all held. Completed and superseded admitted cycles still returned the same retry identity. The foreign pending queue stayed byte-identical, a State file without the expected table held, and the ordinary SQLite read connection was read-only and closed. Normal requested-scan fixtures covered the request-consumption cut and the complete busy intake payload.

The empty-slot readback still requires exact persisted request ID, fingerprint and retry binding. It now uses the ordinary receipt binding to validate scope, frozen source, competing owner exclusion, and the installed COMPLETE runtime. For the intake payload it reconstructs the normal measurement with the frozen observed boundary when the saved condition was busy, then compares canonical serialized values. This resolves the original four findings without relying on the mutable current mirror for historical timing. The original rejection remains in `INDEPENDENT_QA.md`.

The run used isolated system Python 3.11 with bytecode and pytest plugin autoload disabled, socket and child-process audit refusal, staged source import verification, and disposable scratch databases. No live operations or candidate edits occurred. The review covers replay admission only.
