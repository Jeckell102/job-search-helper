# Independent installed final QA — 2026-11-18, candidate v2

**FAIL. The candidate was automatically rolled back; do not reattempt this release.** The independent staged PASS does not override this installed acceptance failure.

Manifest digest: `3fb8c7ce00a4bed1ca7a6c93784eba04678552b4b35ca0ad1dcfbf21e919a17f`.
Archive: `/home/chris/job-search-helper_old/dev/wrapper-coder/repairs/rollout-v2-20261118`.

## Confirmed failure

The actual paused rollout published the candidate, migrated the exact reviewed cohort, and passed stopped verification. `Controller.verify_running()` then rejected the installation with `ValueError: Database changed during paused service startup`. Its required comparison is the complete logical database and controls after migration versus after healthy service startup. Journal phase is now `ROLLED_BACK`; no installed PASS was published.

The coordinating reviewer's disposable reproduction (`startup-recovery-drift-reproduction.json`) applies startup recovery to the exact migrated database and confirms changes to 111 task records, limited to `inference_session_open`; the recovery path adds `false` to previously absent fields. Only the tasks table changed and no model call occurred. Thus even untouched paused tasks were rewritten by startup. This violates the explicit no-mutation installed gate. Do not weaken or skip that comparison to accept this candidate. Repair recovery so absent/already-closed sessions do not cause task rewrites while genuine interrupted session recovery still behaves safely; verify independently and rebuild a fresh manifest before another rollout.

The archived failed `coordinator_inference.py` SHA-256 is `0abce9be80411e913531c2bf3470e5f8a3110a9af062e2cf5f8578116b3a3f42`. This finding reopens Group 7 installed startup parity and its recovery regression coverage.

## Independent rollback verification — PASS

Fresh read-only checks completed at 2026-11-18 20:47 UTC:

- Entire installed tools and Jetson mirror trees match the archive's original metadata exactly; configuration hashes and live service unit metadata also match.
- Complete live logical database equals both predeployment evidence and SQLite backup, digest `77fda4b0f1d2b9af39399898b075735931c8d09c1d245a33158867a3aeb5215f`. This includes all 111 tasks, original counters, task history, settings and receipts.
- Queue/autopilot OFF, pilot null, no active task or unresolved receipt; database integrity `ok`.
- Prior service is active/running/enabled, PID 551967; authenticated health is healthy with worker alive and zero snapshot/control failures. The scheduler process ownership lock excludes a second owner.
- Remote Jetson forwarder is unchanged, SHA-256 `0bdef715ad92b7f9a7d571ed42b98c3c18df0ea819e23ce5dcf167483f7ab11f`.
- Rollout journal is terminal `ROLLED_BACK` and the durable pending marker is cleared. Failed source and rollback evidence remain preserved in the archive.

Evidence: `installed-v2-rollback-independent.json`. The first sandboxed SQLite read failed with `unable to open database file`; the authorized read-only verifier was rerun with the access needed for the live WAL database and completed successfully. It did not change services or scheduling, invoke inference, or alter production source/task content.

## Next gate

Keep the original release paused. Obtain a fresh independent repair acceptance, a new manifest-bound staged PASS, another protected paused rollout and independent installed PASS. Final GitHub-to-installed delivery parity remains pending. Historical stage and rollback successes must not be described as successful installation of this candidate.
