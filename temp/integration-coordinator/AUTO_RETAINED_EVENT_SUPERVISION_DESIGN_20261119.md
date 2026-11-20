# Automatic retained Company-event supervision — design only

## Goal and non-goal

Add one opt-in branch to the existing `CompanyIntakeDispatcher` tick for an
event-bound, one-company request that the ordinary queue reports as blocked by
exactly one unfinished historical cycle. The branch invokes only the existing
public `job-search-scraper run-retained-company-event` route. It does not
activate exceptions, bypass the retained admission/publisher, create a second
scraper, or change ordinary `start` behavior.

The default remains disabled. A signed exception must be activated separately
through the existing public `activate-retained-exception` command. No service,
Google access, or source change is part of this design pass.

## Call graph

```
sync_cli watch
  -> bounded Sheets cycle; writer.lock released
  -> CompanyIntakeDispatcher.run_once
       -> reconcile normal First-Pass workflow first
       -> reconcile retained consumption receipt / retained child first
       -> CompanyEventBridge.process_pending
       -> validate canonical event request + request digest
       -> ordinary queue status
            READY_FOR_START -> existing normal ownership + public `start`
            exactly-one-cycle blocked -> retained eligibility preflight
                 -> public `run-retained-company-event` child (nonblocking)
                 -> retained route: active signature -> immutable admission ->
                    frozen retained start -> exact publication -> FIRST PASS
                    release -> settled start journal -> archive/unlink/receipt
            any other status -> existing hold
```

The retained branch is considered only after the existing normal workflow
reconciliation. It is considered only for `WAITING_SAFE_BOUNDARY` with one
exact current blocker; it is never a fallback for a ready normal request, a
foreign request, a malformed request, a multi-cycle block, or an ordinary
child failure.

## Durable dispatcher journal

Keep the existing `company-intake-dispatch.sqlite3`, but introduce one
authoritative `request_ownership` row per request ID (with immutable request
digest) so the normal and retained routes cannot both reserve it.

| State | Meaning / next tick |
|---|---|
| `NORMAL_STARTING`, `NORMAL_CHILD_LAUNCHED`, `NORMAL_WORKFLOW_COMPLETE` | Existing normal path only; retained branch returns `HELD_NORMAL_OWNERSHIP`. |
| `RETAINED_PREFLIGHTED` | Exact request/digest, one blocker, active signed record, key fingerprint, and manifest digest were read and pinned before spawn. |
| `RETAINED_STARTING` | Durable reservation written before `Popen`; a restart may retry only the same request/digest/key/manifest binding. |
| `RETAINED_CHILD_ACTIVE` | PID and Linux process-start identity match a live child; hold and never launch another child. |
| `RETAINED_RECOVERABLE` | Child is absent after a prior reservation. Reinvoke only the public retained command, which recovers its own frozen journal/remote receipt rather than starting duplicate work. |
| `RETAINED_CONSUMED` | Exact archive and consumption receipt prove `FIRST_PASS_RELEASED_CONSUMED`; terminal for this request. |
| `RETAINED_HELD_*` | Invalid/missing configuration, invalid/expired signature, manifest drift, ambiguous/multiple blocker, changed request, or unreadable authority. Keep request unchanged. |

The existing normal `dispatches` table may be retained for compatibility, but
both `_reserve()` and the retained reservation must consult the shared
ownership row in one SQLite immediate transaction. Existing normal dispatch
records seed `NORMAL_*` ownership. A request ID with a different digest is
always `HELD_REQUEST_ID_REUSED`.

Persist retained fields: request ID/digest, event ID/company/source revision,
exception cycle, manifest digest, key ID, SHA-256 fingerprint of the configured
public key, child PID plus `/proc/<pid>/stat` start-time, command fingerprint,
last result/error, and timestamps. Do not persist the key itself or private
authorization material. A missing or changed configuration fingerprint is a
hold, never a reason to use a different key for an already-owned request.

## Eligibility and restart rules

1. Reuse `is_event_bound_company_request()` and the full request digest.
2. Read the queue result and State read-only. Require exactly one unfinished
   blocker and require it to equal the signed exception manifest cycle.
3. Build the verifier from configured key ID/public key, then call the existing
   `_active_record()` and `revalidate_manifest()` read-only. This proves ACTIVE
   state, real signature, expiry, exact cycle, and unchanged local evidence
   before reserving/spawning.
4. Do not call a retained route while a normal First-Pass workflow exists or a
   normal ownership row exists. Do not create the normal handoff sidecar for
   retained work.
5. Before each child action, first inspect the exact consumption receipt. It
   must name the request digest and `FIRST_PASS_RELEASED_CONSUMED`, and the
   archived request must equal the pinned request. A different current
   `next-scan.json` is explicitly preserved. This moves the row to
   `RETAINED_CONSUMED` without a new child.
6. For a retained child, PID alone is not proof of completion. While its PID
   and recorded process-start identity are live, return `RETAINED_CHILD_ACTIVE`.
   Once absent, mark `RETAINED_RECOVERABLE` and run the same public retained
   command once. That command's frozen start/session/publication records are
   its idempotent recovery authority; the dispatcher never infers publication
   or FIRST PASS from process exit.
7. If a newer different `next-scan.json` arrives, retain it. The recovery child
   may complete only the archived pinned request, as the current retained route
   already verifies and preserves a replacement before writing its old receipt.

## Status and controls

Add separate durable controls, both false in a new journal:

* `intake_enabled` (existing normal intake gate)
* `retained_intake_enabled` (new additional gate)

`intake-status` should expose booleans, configuration-present/key-fingerprint
only, per-route state counts, current request ID prefix/digest prefix, child
liveness, pinned exception cycle, and last retained error. It must not print a
public key, approval envelope, or full request. Add explicit
`intake-retained-enable` and `intake-retained-disable`; enabling normal intake
must not enable retained intake. A disabled retained gate returns
`HELD_RETAINED_DISABLED`, leaving the request untouched.

## Service configuration

No systemd/service unit exists in this sanitized source snapshot. The existing
supervision point is the manually/externally started `sync_cli watch` process.
When a host unit is later approved, it should run that one watcher only and
load a root-readable environment file, for example:

```
COMPANY_RETAINED_INTAKE_ENABLED=false
COMPANY_RETAINED_KEY_ID=
COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64=
COMPANY_RETAINED_SHEET_REQUEST_INTERVAL=1.1
```

The durable SQLite gate is authoritative; the environment is only required
configuration. A service restart does not enable retained intake. Missing,
malformed, or changed key material produces a retained hold/status and never
falls back to normal start. Do not put authorization envelopes or private keys
in the environment, command line, unit file, logs, or journal.

## Required tests

1. Default-disabled retained gate; normal gate alone cannot launch retained.
2. Exactly one blocked canonical request plus valid active signed exception and
   configured key launches one absolute public retained command, not `start`.
3. Ready request uses normal `start` and is never offered to retained route.
4. Missing/invalid/expired/mismatched key, missing ACTIVE record, stale
   manifest, wrong cycle, malformed request, and multiple blockers all hold
   without child/fetch/write.
5. Shared ownership races: normal reservation then retained attempt, and the
   reverse, each result in exactly one owner/child.
6. Live child with matching PID/start-time prevents a duplicate across a new
   dispatcher instance; dead child restarts only the public retained recovery
   command.
7. Crash after retained reserve before spawn; after spawn before journal update;
   after frozen admission; after exact release; after archive/unlink before
   receipt; and after receipt before dispatcher update. Each converges only on
   the exact receipt, without duplicate fetch/publish.
8. A different newer next-scan request survives old retained recovery and then
   remains eligible for its own later normal/retained decision.
9. `sync watch` reports retained statuses/errors separately from Sheets sync;
   `once` remains excluded and sync failure/backoff remains unaffected.
10. If/when a host unit is added, a temporary environment-file/service harness
    proves default disabled, no secret logging, restart recovery, and that only
    one watcher process owns the tick.
