# F4 single-inference recovery assessment

Status: open implementation requirement. This assessment makes no Jetson,
service, scheduler, or task-state change.

## Verified current boundary

The MuleLab coordinator reserves a durable request ID before calling the
Jetson, charges its bounded budget immediately, allows only one request in
`DISPATCHING` or `UNCERTAIN`, and pauses the coordinator after an interrupted
request. Restart recovery deliberately does not replay an uncertain request.

The current Jetson `/api/wrapper-turn` endpoint accepts only messages, tool
schemas, and a token limit. It returns a synchronous response but does not
accept the MuleLab request ID or retain a queryable/cancellable request status.
Therefore, a transport loss after Jetson inference begins cannot be reconciled
as either a retained result or an acknowledged cancellation. It remains a
safe hold, but does not close F4.

## Required bounded change

1. MuleLab sends its already durable inference request ID with each Jetson
   call. The Jetson rejects malformed or duplicate payloads without starting
   a second inference.
2. The Jetson retains only minimal control metadata keyed by that ID: request
   fingerprint, owner generation, state, timestamps, cancellation state, and
   response digest/usage. It must not retain prompts, wrapper source, job
   inventory, or model private reasoning.
3. A protected status endpoint reports the retained state and digest. A
   protected cancellation endpoint returns an explicit acknowledgement only
   when cancellation has reached a safe state.
4. MuleLab restart recovery asks for that status before changing an uncertain
   receipt. A completed result is never blindly re-executed; an absent or
   ambiguous remote status stays held. A confirmed cancellation can settle the
   request without recharging or silently resetting its budget.
5. Tests cover duplicate IDs, MuleLab disconnect before/after Jetson start,
   restart while running, retained completion, acknowledged cancellation, and
   a subsequent distinct company only after safe settlement.

## Orphan reconciliation operational proof

An orphan is not safe to expire on a timer. A Jetson restart marks the prior
`RUNNING` receipt `UNCERTAIN` and holds the single-inference lane. It may be
settled only after a current, independent backend-inactivity observation for
the exact wrapper execution lane (and a matching request fingerprint and owner
generation). A cancellation request alone is not that observation. The
deployment procedure must record the command/output used for this proof and
must keep the receipt blocked when the backend cannot be queried or its state
is ambiguous.

## Deployment boundary

Implement and test this in isolated source first. Before any Jetson deployment,
locate its existing modification log, record backup/version/rollback evidence,
then make one reversible change and verify the protected endpoints. No model
request or repair task is authorized by this assessment.
