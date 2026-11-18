# Independent final QA: release and rollout

Date: 2026-11-18
Reviewer: final_qa_rollout (independent of implementation)
Verdict: **FAIL — do not deploy this candidate**.

This is the staged release gate, not an installed-system certification. No production service, source, database, inference endpoint, or scheduling controls were changed. All executed adversarial behavior used disposable directories and fixture controllers.

## Exact candidate

- Manifest digest: `ef9f1771c30572410f685de65d04b549d24404390b315bf71251dc256f9206b6`.
- Clean release: `/tmp/wrapper-final-release-1c9vcbff/release`.
- Release digest independently verified: `c21f6f39c7317ec34ef632680f3b44459863b7d16c37919ad7b7b49fe10bbf28`.
- Current staged source equals the manifest. Clean release equals the complete expected source/prerequisite inventory.
- `deploy_campaign_update.py` SHA256: `deadd22ca089688a4a2839e6ffdbb34cd8b3e5a9846c5e384e8863d3a9facf15`.
- `rollout_controller.py` SHA256: `7c27df0021debd45d063cebb202f191952d9222b6b8c5bca8896230980672215`.
- `release_bundle.py` SHA256: `6b0e4a5c4d6db089f83aab0dc026eb4c4557d3df7f6948c6622d8c2f18b449ed`.

## R1 — High: concurrent rollout can publish while service runs and corrupt transaction outcome

`deploy_campaign_update.py:53` (`rollout`) and `recover_archive` have no shared deployment ownership guard. The scheduler lock does not guard these operations: the deployment stops the scheduler and never acquires an independent deployment lock. Distinct archive/prepared directories let two invocations pass all preconditions against the same original database and paused service.

A deterministic interleaving of the real deployment engine demonstrates:

1. First transaction passes both preflights, stops the service, backs up, and finishes rehearsal.
2. Suspend it at the existing `after_rehearsal` fault boundary.
3. Second transaction against another prepared directory and archive completes and returns `INSTALLED_PAUSED`, restarting the shared service.
4. First transaction resumes and publishes its tools directory while that service is running.
5. Inject an error immediately after that unsafe publication. First rollback restores the original database but restores the second transaction's new tools as its apparent prior source, producing mismatched source/database state and `ROLLBACK_FAILED`.
6. The second archive still reports `INSTALLED_PAUSED` although its installed database state was undone.

Evidence: `reproduce_concurrent_rollout.py`, `final-qa-rollout-concurrency.json`. Run `python3 -B work/wrapper-workflow-qa-20261118/reproduce_concurrent_rollout.py` from the project root. The script asserts the two observed defects and exits successfully when they reproduce. It invokes actual `rollout` logic with fixture controllers sharing one service-state variable; it does not contact systemd, SSH, production databases, or the AI. This deterministic scheduling seam isolates the missing deployment ownership contract; production controller migration checks would detect drift later, after unsafe publication, and therefore cannot prevent it.

Expected: a contender must fail before service, source, database, or journal mutation while another apply/recover owns that production base. A completed rollout must not be undone by a concurrent transaction whose backup predates it.

Required correction and verification:

- One exclusive ownership guard for both apply and recover, covering the entire transaction including preflight, archive creation, service changes, backups, publication, rollback/recovery, readiness verification, and terminal journal persistence.
- Contenders must have no deployment side effects. Test apply/apply, apply/recover, and recover/recover with separate processes and separate controller objects.
- Lock lifetime must survive all ordinary exception paths and release on process death without permitting a new apply to silently bypass an unfinished durable transaction. Bind recovery to that outstanding transaction, or require explicit safe reconciliation before a new apply.
- Include a crash case where an incomplete earlier archive exists, a fresh apply is attempted, and recovery cannot subsequently undo a newer successful deployment.
- Rebuild the candidate manifest and clean release; rerun independent QA after repair.

## Passing checks, insufficient to override R1

- Existing deployment engine/controller tests: 15/15 passed independently.
- Release builder tests: 5/5 passed independently.
- Clean release assignment baseline and process ownership tests: 18/18 passed independently, including cross-process ownership, direct/private entry points, copied input drift, immutable pin migration, and error-path release.
- Source inspection confirms reviewed source/runtime prerequisite hashes, original database binding, exact 102-record migration, idempotent migration second application, nonmember/historical record preservation, startup database drift rejection, and rollback verification are represented in the implementation and corresponding tests.

These tests did not cover deployment transaction concurrency. The reproduced failure reopens Group 7. Installed QA, GitHub final parity, and production migration remain pending and must not be reported as passed. Final QA for other groups is owned by the parallel independent scheduler reviewer.
