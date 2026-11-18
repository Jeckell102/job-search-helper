# Coordinator QA repair progress

Goal started: 2026-11-18 19:05:23 UTC. Goal remains ACTIVE until independent final QA passes and reviewed changes are backed up.

Production controls remain OFF; no integration campaign or Jetson inference started during repairs. Jetson remains one inference lane. All work and evidence stay on MuleLab.

## Accepted finding 1

Campaign membership, individual pause/exclusion, selection and claim isolation are accepted in staging. Independent reviewer: 16 campaign tests passed. Full host suite: 161 tests passed. Exact legacy 102-task migration tested on a disposable database copy: dry run unchanged, first apply 102, second apply zero, identical post-apply bytes, integrity OK, controls OFF, shortened cohort rejected. Production migration is deferred until combined deployment.

GitHub backup: `backup/wrapper-pilot-20261118`, commit `cf7a227` (push succeeded).

## Current finding 2

Atomic pilot/campaign/queue transitions. Initial 10 independent race/failure tests and full 171-test suite passed. Review then reproduced terminal-status laundering through pause and resume; this is a mandatory remaining blocker before group 2 acceptance. Implementation lane owns coordinator/Store. Independent verifier owns race/failure tests. Roadmap lane manages acceptance; primary coordinates and records evidence. No later finding implementation begins before this group passes.

## Remaining

3. Canonical identity and duplicate prevention.
4. Exact edit scope and independent acceptance tests.
5. Atomic inference reservation and pause precedence.
6. Durable campaign completion and truthful reporting.
7. Scheduler ownership, baseline inputs, reproducible deployment.

Then: independent final QA using fresh reviewers. Any failure creates a new report and fresh repair/verification lanes; the goal remains active until re-QA passes. Live scraper validation and installing generated wrappers remain separate gates.
