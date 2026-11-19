# F4 backend-inactivity contract

Status: proposed implementation contract, 2026-11-19. Derived from a
read-only live Jetson inspection. No Jetson service was changed.

## Why the existing design is incomplete

The sole Jetson model process is system service `ollama.service`, currently
with a long-lived `ollama serve` main process. The orchestrator's source-only
receipt can retain `RUNNING`/`UNCERTAIN`, but the Ollama API does not attach a
caller-provided request ID to an in-flight generation status or cancellation
acknowledgement. A successful status response, a model remaining loaded, an
orchestrator restart, or a missing HTTP connection does not prove whether the
old model process is still generating.

The existing orchestrator service has `TimeoutStopSec=15`, while a wrapper turn
may wait up to 270 seconds. Its current shutdown path does not wait for all
HTTP handler threads. Therefore a clean-looking orchestrator restart cannot
be used as the proof either.

## Supported resolution rule

A retained `UNCERTAIN` receipt stays lane-blocking by default. It may become
terminal only if its owner supplies a current backend-generation observation
that proves the exact Ollama process generation recorded at dispatch is gone.

The first supported positive proof is a deliberate, recorded restart of only
`ollama.service` after the orchestrator has observed a retained uncertain
receipt:

1. Record the old Ollama generation from `systemctl show ollama.service`:
   `MainPID` plus `ExecMainStartTimestampMonotonic`.
2. Request shutdown/cancellation of the wrapper receipt, but do not label it
   cancelled yet.
3. Stop/restart `ollama.service` through the existing service manager.
4. Confirm the old PID has exited and the new active Ollama generation differs
   in both a process-liveness check and the recorded systemd generation.
5. Submit the owner-bound settlement request containing the recorded old and
   observed new backend generations. The Jetson independently re-reads the
   current generation; it never trusts a client assertion.
6. Persist `FAILED` or `CANCELLED` with the backend-generation proof receipt,
   release the sole inference lane, and leave the MuleLab request in a visible
   recovery state. Never replay the original inference.

A normal completed request, a retained terminal response, or a graceful
coordinator/MuleLab transport loss does not require the Ollama restart. The
host reconciles the terminal Jetson receipt by its persisted ownership binding.

## Required implementation boundary

The staged Jetson receipt store must persist a bounded `backend_generation`
for each controlled request. It should be a validated object containing only
the service name, positive PID, and positive systemd monotonic start timestamp.
No prompt, response text, user data, environment data, command line, or token
belongs in this receipt.

The server supplies the generation from a local `systemctl show` query at
atomic admission time. If that query fails or reports no active Ollama main
process, controlled inference fails closed before `native_turn` starts.

Add an owner-bound `POST` endpoint for orphan reconciliation. It validates the
recorded generation, independently queries the current service generation, and
accepts settlement only when:

- the receipt is `UNCERTAIN`;
- the ownership binding matches;
- the original PID is absent; and
- the active Ollama PID/start generation differs from the stored generation.

The endpoint returns a sanitized terminal receipt. It must reject same-
generation, missing-service, malformed, stale-owner, and already-terminal
requests. It must never start inference, restart Ollama, or accept arbitrary
process IDs from MuleLab.

MuleLab reconciliation can call the endpoint only after its existing retained
status query returns `UNCERTAIN`; the caller must persist the terminal outcome
once and keep the repair task paused. This preserves accounting and prevents a
lost response from being replayed.

## Required regression evidence

1. Store rejects malformed backend generation values.
2. Admission fails before native inference if the independent generation query
   is unavailable.
3. Same-generation reconciliation fails closed and leaves `UNCERTAIN`.
4. Changed generation plus absent old PID settles only the matching owned
   uncertain receipt; a duplicate settlement is idempotent.
5. Wrong owner, request ID, or source generation cannot settle another
   receipt.
6. Host recovery sends only the persisted ownership binding and records the
   returned terminal result without replaying a model call.
7. Deployed-system test uses a synthetic controlled request, injects a
   bounded transport loss, then deliberately restarts only Ollama and proves
   the old generation ended before the lane reopens. It must not use a real
   Job Search Helper task or a user prompt.

## Operational constraints

- This recovery has a real availability cost: it restarts the local model
  service and can interrupt normal Jetson chat. It is a controlled operator
  recovery, not unattended self-healing.
- A crashed/missing Ollama service is insufficient proof; a replacement active
  generation and an absent recorded old PID are both required.
- The service restart itself must be recorded in the Jetson change log and the
  F4 project-records directory with before/after generation values, no private
  request data, and rollback evidence.
- Until this contract is implemented and live-tested, the existing permanent
  `UNCERTAIN` hold is correct. It is not a completed F4 recovery capability.
