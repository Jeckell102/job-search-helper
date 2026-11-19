# F4 Jetson preflight and rollback procedure

Status: preparation only, 2026-11-19. No Jetson change has been made by this
procedure. It is intentionally separate from the source-only F4 evidence.

## Release boundary

The staged F4 files add authenticated, ownership-bound inference receipts to
the Jetson service. They do **not** by themselves prove that Ollama can attest
to an interrupted request's non-execution after service restart. Until a fresh,
independent backend-inactivity proof exists, a retained `UNCERTAIN` receipt
must remain lane-blocking. No retry, release, repair continuation, or automatic
orphan settlement may follow it.

This means a deployed status/cancellation feature can be verified, but F4 and
Milestone 6 cannot be marked complete from that deployment alone.

## Preflight: read-only evidence to capture first

Run these through the existing Jetson SSH connection and save sanitized output
under a new date-stamped directory in `/home/chris/AI/project-records/` on the
Jetson. Never copy tokens, SQLite rows, request payloads, prompts, task text,
or model output into the records or GitHub.

1. Confirm the intended host, current user, time, and available disk space.
2. Record `systemctl --user` active state and unit definition of
   `local-ai-orchestrator.service`; record the process PID/start time.
3. Record the current hashes and modes of the production source files that a
   release would replace: `server.py`, `wrapper_inference.py`, and any newly
   installed `inference_control_store.py`.
4. Record a health/status response and database integrity only in aggregate;
   do not export tasks, chat history, credentials, or receipt rows.
5. Record that the deployed wrapper endpoint is still the old implementation
   before the release. The source checkpoint for the proposed release is Git
   commit `9dd1070` on `codex/integration-automation-20261118`.
6. Save a consistent recovery archive using the existing Jetson/MuleLab
   encrypted recovery procedure and verify its checksum plus an isolated
   restore/integrity check. Save a separate source rollback copy of every
   file targeted by this release.
7. Write a pre-change note using the documented Jetson change log command:
   `python3 /home/chris/AI/benchmark-log/monitoring/manage.py note ...`
   The note must state that this is an F4 staged inference-receipt rollout,
   the exact source checkpoint, the rollback location, and that unresolved
   requests remain lane-blocking.

## Required deployment evidence before touching the service

- The staged source matches the reviewed checkpoint and has no credential,
  database, lock, cache, or private-inventory file.
- The current service is healthy and idle enough for a deliberately scoped
  restart. If it has active work, leave the deployment pending.
- A rollback script or exact manual rollback command is dry-run validated
  against the copied source list without changing the live service.
- The source-level suite remains green: 34 MuleLab checks and 13 staged Jetson
  checks. The endpoint tests need an ephemeral loopback server and should only
  run in an approved local test environment.
- A fresh independent reviewer has accepted the final staged diff including
  the legacy-payload lane guard.

## Controlled rollout sequence

1. Preserve the verified rollback snapshot and pre-change note.
2. Stop only `local-ai-orchestrator.service`; do not stop Ollama, Open WebUI,
   network services, or unrelated Jetson components.
3. Install only the staged F4 files, with restrictive normal source modes, and
   verify their SHA-256 values against the release manifest.
4. Start only `local-ai-orchestrator.service`; confirm the exact service PID,
   health endpoint, bounded database integrity result, and no unintended task
   execution.
5. Test, using a synthetic controlled request and no Job Search Helper task:
   authentication rejection, ownership rejection, owned status response,
   duplicate request non-replay, cancellation acknowledgement, and service
   restart handling of a retained running receipt.
6. Confirm the old three-field wrapper request is rejected by the upgraded
   HTTP service and that the MuleLab host submits the persisted control binding.
7. Record the actual change, exact commands, source hashes, test outcomes,
   service status, rollback location, and remaining backend-inactivity limit in
   the Jetson change log and its new project-records directory.

## Rollback trigger and method

Roll back if the service fails health checks, a protected endpoint accepts an
unowned request, an upgraded host cannot submit the bound request, database
integrity changes unexpectedly, or an unrelated service is affected.

1. Stop only `local-ai-orchestrator.service`.
2. Restore only the saved pre-change F4 source files from the rollback copy.
3. Remove only F4 files that were newly added by this rollout.
4. Start only `local-ai-orchestrator.service`.
5. Verify the original source hashes, service health, database integrity, and
   aggregate task counts. Do not restore the database unless separate evidence
   proves it was affected.
6. Record rollback cause and evidence in the same Jetson change record.

## F4 closure still required after rollout

The deployed service needs a positive, independent observation that a named
interrupted backend turn is no longer executing before an orphan can become a
terminal state. Current Ollama calls have no request-ID correlation that proves
this. Until that capability is designed and tested, `UNCERTAIN` remains the
correct durable hold and the only safe operator outcome is to leave the shared
inference lane blocked.
