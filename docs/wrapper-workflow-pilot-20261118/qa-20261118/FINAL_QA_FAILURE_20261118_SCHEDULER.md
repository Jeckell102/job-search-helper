# Independent final scheduler QA — 2026-11-18

**Verdict: FAIL. Do not deploy this candidate.** Findings 1–5 have supporting passing adversarial coverage; finding 6 is reopened by one new confirmed public-command regression. This is staged QA only, not installed acceptance or live integration certification.

## Confirmed blocker: status cancels healthy in-flight inference

Severity: high for unattended operation. `coordinator_campaign.py` `_campaign_reconcile()` unconditionally classifies every DISPATCHING inference receipt as a reconciliation error. `Coordinator.command()` invokes this method for ordinary `campaign-status`, `autopilot-status`, and queue reporting. The error branch disables queue/campaign controls and advances their generation. A healthy model response therefore loses its reservation ownership and is discarded.

Reproduction: `python3 -B work/wrapper-workflow-qa-20261118/reproduce_live_inference_status.py`. It creates only disposable tasks/files, starts the actual `Coordinator.session()` method in a thread, and blocks its injected model callback on an event. While that callback is verifiably running, the second thread issues the real public `campaign-status` command; then it releases the callback with valid usage and response. No real model endpoint, production task, service or repository is touched.

Observed in `final-qa-live-inference-status-reproduction.json`:

- Before status: campaign enabled, task RUNNING, control generation 3.
- After status: campaign disabled, generation 4, report PAUSED_RECONCILIATION.
- Returning valid callback: receipt RESPONSE_DROPPED, task PAUSED.

Expected: reading status during a healthy current inference leaves controls/generation unchanged, reports work in progress, does not select another company, and allows the owned response to finish normally. Crash uncertainty remains different: UNCERTAIN receipts and orphaned/mismatched DISPATCHING receipts must block advancement and automatic replay. A fix needs authoritative ownership checks (current task/run/session/identity, open session, active state and consistent reservation), not unconditional exemption of DISPATCHING or trust in a RUNNING label alone. Startup recovery must still convert interrupted dispatch to uncertainty. Existing owner-mismatch and no-replay tests must remain passing.

The preexisting `test_unresolved_inference_pauses_reconciliation_without_advance` changes the owner to PAUSED_ERROR before reconciliation. It covers an orphan but misses a healthy live callback. The focused suite is therefore green despite this failure.

## Reviewed coverage and passing evidence

I read the original QA assessment, roadmap, final QA plan, original reproduction mapping, the selection/claim and control transaction paths, canonical identity/registry and worker packet construction, immutable acceptance execution, inference reservation/finalization, and campaign result reconciliation. Existing assertion-based reproductions replace obsolete hook-based diagnostics appropriately.

Independently reran 84 tests from the clean host copy: campaign isolation, concurrent control transitions, identity integrity/registry, edit scope/frozen acceptance, inference reservations, and campaign completion. All 84 passed in 5.574 seconds with ResourceWarnings treated as errors. Log: `final-qa-scheduler-tests.log`. This verifies user pause/exclusion and cross-campaign/generic selection separation; atomic pilot activation rollback and competing requests; immutable company instructions and duplicate/retry registry; scope denial and independent original assertions; pause-before-reservation suppression and exactly-once accounting; durable terminal counts and explicit operator gates. Passing those tests does not override the new public-command reproduction.

All staged host Python source bytes match the clean host copy used for this rerun. Complete file SHA-256 values are in `final-qa-scheduler-source-binding.json`; canonical source-map digest: `7aaaaf6fe2a7c1c63dc8f6bbd93a9069be2fa1d87c2b0641e33c9f562ce8f6fe`.

Affected file hashes:

- coordinator_campaign.py: `a9af815186ca8137e8e88d69d0e98934ee749b2edcb344cffde9690342aa4121`
- coordinator.py: `e38f3c859122f8763c77cbdb97e5c06a358c8f89723a5b43d497bd631f5282e1`
- coordinator_inference.py: `0abce9be80411e913531c2bf3470e5f8a3110a9af062e2cf5f8578116b3a3f42`
- coordinator_store.py: `66aebf37b7580bdf674598799762121146405e62f877e47b1159f01731c3e581`

## Required next gate

Assign fresh repair and independent verification lanes for this failure. Add healthy in-flight public status coverage alongside orphaned dispatch, explicit pause during inference, restart uncertainty, and single-lane checks. Then repeat staged final QA with a new source binding. Deployment/recovery, migration, installed controls/health, GitHub parity and live/install gates are outside this report's PASS claim and remain pending their assigned reviewers.
