# Independent final QA gate

Goal started 2026-11-18 19:05:23 UTC. Completion depends on verified acceptance, not elapsed time.

The seven original finding groups are repaired sequentially under REPAIR_ROADMAP.md. A passing implementation unit suite is necessary but does not replace independent final QA.

Final QA must inspect the final deployed source, tests, migration audit, and paused controls. Use disposable task databases and workspaces for adversarial execution; use read-only checks against the real services. Do not start the integration campaign or perform live inference merely to test scheduling.

Required acceptance:

1. User pause and exclusion survive campaign start, another company's completion, and restart. Generic tasks and other campaigns cannot enter this campaign's lane.
2. Competing pilot/campaign/global controls have one committed winner; failed pilot startup leaves no slot or queued work.
3. Canonical company identity controls worker messages/evidence. Conflicting identities and cross-batch duplicates fail closed without creating work or resetting budgets.
4. Out-of-scope writes fail. A worker cannot replace host-owned acceptance assertions with passing stubs. Additional regression tests remain possible within explicit scope.
5. Pause committed before an inference reservation prevents the call. Already reserved work is recorded honestly, retains cumulative budgets, and cannot perform new writes after stop.
6. A bounded two-company rehearsal proves fresh context/workspace, pause/restart behavior, terminal totals, explicit exceptions, and accurate next actions. Offline readiness never implies live validation or installation.
7. All scheduler entry points honor process ownership. Baselines pin every copied test input. Re-running the deployment reproduces tested files, preserves state, and has rollback evidence.
8. Installed focused/full checks pass; controls remain OFF, pilot unset, no active tasks, database integrity OK. GitHub contains the exact reviewed source and reports, without credentials or runtime database.

If any mandatory acceptance fails, save a new dated QA report with reproduction, expected/actual behavior, severity, and affected source hashes. Assign fresh repair and independent verification lanes, repair one finding at a time, and repeat final QA. Do not mark the goal complete with a failing or skipped mandatory gate.

Deliberate gates remain: generated integrations require separate live scraper validation and production installation approval/evidence. Final coordinator QA is not a claim that every job has been downloaded.
