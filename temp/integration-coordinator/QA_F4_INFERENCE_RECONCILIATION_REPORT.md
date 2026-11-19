# F4 inference reconciliation corrective QA

Date: 2026-11-19

Scope: isolated source only under `/tmp/job-search-helper-integration-automation`.
No production source, Jetson service, scraper, lock, Company record, job record,
or Google Sheets data was changed.

## Result

PASS for the five rejected source-level protocol requirements. This is not a
deployment approval and does not close F4 or later roadmap milestones.

1. Post-model response/usage failures now settle a returned model turn before
   propagating the error; duplicate request IDs cannot invoke it again.
2. An ambiguous native/backend transport error becomes blocking `UNCERTAIN`;
   a requested cancellation is not represented as completed cancellation.
3. A new Jetson service instance marks a retained `RUNNING` receipt
   `UNCERTAIN`. It requires matching ownership and positive backend-inactivity
   evidence for settlement, and never replays it.
4. Status requires both the shared wrapper token and per-request ownership
   headers. Returned status omits ownership credentials; DELETE remains
   ownership checked.
5. MuleLab persists the exact control binding before dispatch. Restart recovery
   queries the ownership-bound remote status and turns a retained completion
   into `RESPONSE_DROPPED`, never executing lost tool calls or recharging the
   request. A remote running/uncertain state remains lane-blocking.

## Evidence

- MuleLab focused suite: 34 passing tests from
  `test_inference_control_store`, `test_inference_host_protocol`, and
  `test_inference_store`.
- Jetson staged suite: 12 passing tests from
  `test_inference_control_store`, `test_wrapper_inference`, and
  `test_wrapper_control_routes`; the route tests used an ephemeral loopback
  server only.
- `git diff --check` passed after each suite.
- Added host-binding probe confirms the coordinator sends only the persisted
  binding and rejects a returned receipt for a different request ID.

## Remaining deployment gates

- Capture Jetson preflight, backup, version, service and rollback evidence.
- Define and prove the current independent backend-inactivity observation used
  to reconcile a Jetson orphan; ambiguous or unavailable evidence must retain
  `UNCERTAIN`.
- Deploy only through Jetson change management and verify the authenticated
  endpoints against the deployed service.
- Re-run independent deployed-system QA before treating F4 as complete.
