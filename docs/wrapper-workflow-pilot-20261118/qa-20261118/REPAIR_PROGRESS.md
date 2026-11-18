# Coordinator QA repair progress

Goal started: 2026-11-18 19:05:23 UTC. Goal remains ACTIVE until independent final QA passes and reviewed changes are backed up.

Production controls remain OFF; no integration campaign or Jetson inference started during repairs. Jetson remains one inference lane. All work and evidence stay on MuleLab.

## Accepted finding 1

Campaign membership, individual pause/exclusion, selection and claim isolation are accepted in staging. Independent reviewer: 16 campaign tests passed. Full host suite: 161 tests passed. Exact legacy 102-task migration tested on a disposable database copy: dry run unchanged, first apply 102, second apply zero, identical post-apply bytes, integrity OK, controls OFF, shortened cohort rejected. Production migration is deferred until combined deployment.

GitHub backup: `backup/wrapper-pilot-20261118`, commit `cf7a227` (push succeeded).

## Accepted finding 2

Atomic pilot/campaign/queue transitions accepted after the terminal-status bypass was fixed. Independent transition tests12/12 and full host suite174/174 passed. GitHub backup `4ef6dde` pushed successfully.

## Accepted finding 3

Canonical identity and company registry implemented. Exact102-member identity migration passed on a disposable database: dry run unchanged; first apply102; second apply0 and byte-identical; old budgets, statuses and history preserved; integrity OK; controls OFF. Independent testing caught an activation-fields mutation bypass after the initial188-test pass; post-update validation now rolls it back. Final independent full suite190/190 and focused45/45 passed. Roadmap accepted. Group4 exact edit scope and independent acceptance assertions now in progress.

## Remaining

3. Canonical identity and duplicate prevention.
4. Exact edit scope and independent acceptance tests.
5. Atomic inference reservation and pause precedence.
6. Durable campaign completion and truthful reporting.
7. Scheduler ownership, baseline inputs, reproducible deployment.

Then: independent final QA using fresh reviewers. Any failure creates a new report and fresh repair/verification lanes; the goal remains active until re-QA passes. Live scraper validation and installing generated wrappers remain separate gates.
