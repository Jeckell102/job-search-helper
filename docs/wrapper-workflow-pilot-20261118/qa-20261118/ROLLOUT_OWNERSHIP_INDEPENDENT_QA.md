# Independent rollout ownership repair QA — 2026-11-18

**PASS for this bounded staged repair.** This does not certify installed production, migrations, final full-source QA or GitHub parity. The original final-QA failure report and reproductions are preserved unchanged.

I inspected the original concurrency finding, current engine/controller lock boundaries, durable pending marker lifecycle, recovery identity binding and terminal verification. I independently added seven tests in `test_rollout_ownership_independent.py`. They use disposable directories, SQLite fixtures, separate OS processes and simulated service controllers; no production service, task, inference endpoint or source was changed.

Verified behavior:

- A separate process holding an actual apply transaction rejects apply and recovery contenders before service callbacks, archive creation or source/database changes. CLI prepare and rehearse use the same owner.
- A separate process holding actual recovery rejects another recovery and a fresh apply. The successful first operation retains its expected final source/database result.
- Process death after pending-marker persistence, rehearsal, and first source publication releases the OS lock but leaves a durable barrier. Fresh apply and nonmatching recovery reject without changing the marker or calling service controls. Matching recovery restores exact old source/database, preserves the workspace, restores prior service state and clears only its matching pending marker.
- Pending recovery also blocks public CLI prepare and rehearse. The permanent lock inode remains present; installed-terminal recovery preserves the inode and does not roll back the installed files/database.
- A crash immediately after the installed terminal journal is recovered through verification of the current installation, not restoration of an earlier backup. Verification failure retains the pending marker and prevents a newer apply. Repeating recovery after marker clearance rejects.
- An existing malformed `null` marker fails closed. The worker's final corruption fix was present in the executed run.

Combined independent execution: **27/27 PASS**, 2.007 seconds, ResourceWarnings treated as errors: seven new independent ownership cases, seven existing rollback/fault-boundary cases, eight real-controller guard cases, and five release-bundle cases. The seven new tests include subcases for three abrupt crash boundaries and all public preparation operations. Existing checks retain reviewed-manifest/database binding, exact-102 migration behavior, no-op repeat migration, source/dependency parity, readiness/owner checks and rollback detection. Log: `rollout-ownership-independent-tests.log`.

Ownership acquisition may create/fsync its permanent lock infrastructure even on a refused operation; refusal makes no deployment/service/database/journal mutation. The safety claim assumes all deployment clients use these public entry points and the privileged operator does not manually unlink the permanent lock. It does not infer scheduler ownership from a stale lock filename.

Exact executed source hashes:

- `deploy_campaign_update.py`: `18a64009faf670adc60da9df944d18c0711a51f29b9dc07b3df020ee70548a40`
- `rollout_controller.py`: `d511d808bf85df0cacf9c97894430e3b154bf9164f647b119f85bf7ec6426a9a`
- `release_bundle.py`: `6b0e4a5c4d6db089f83aab0dc026eb4c4557d3df7f6948c6622d8c2f18b449ed`

Machine-readable evidence: `rollout-ownership-independent-verification.json`. Rebuild the reviewed release manifest and repeat final staged QA before any paused production deployment.
