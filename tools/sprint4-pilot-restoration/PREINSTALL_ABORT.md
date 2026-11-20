# Sprint 4 pre-install alternate-checkout restoration

This helper handles two narrow cases after the approved alternate exchange durably acknowledges closure. One is a supervised original install that exits with the controller’s exact preflight refusal. The other is a closure that ends before the original install is invoked. Both require an independent approval of the requested restoration and exclusive custody of the enrolled capsule, attempt log, application writers, alternate checkouts, and exchange control until the restore reaches its durable terminal phase.

An existing controller journal moves recovery to the recorded joint-controller workflow. A marker, parked application package, installed or staged guard, service-hold sentinel or maintenance drop-in, either sealed wrapper image, or an unexpected transaction directory disqualifies this helper. Preserve those routes as evidence when the helper refuses.

## Before the first launch

Use the independently reviewed stage and its matched controller, gate, installer and exchange modules. Before parking the alternate checkouts, retain the original private maintenance capsule and the two empty mode-0600 controller and installer gate files. Create a separate canonical, owner-private mode-0700 attempt directory outside the source, capsule and exchange routes. Its sole initial entry must be an empty mode-0600 `attempt.lock`. Keep these paths and inodes under exclusive custody.

After preparing the exchange and building the original approved checker, call:

```python
from pathlib import Path
from preinstall_abort import enroll_abort

enrollment = enroll_abort(
    Path("/absolute/original/capsule"),
    attempt_directory=Path("/absolute/original/attempt-directory"),
    approved_checker_sha256=approved_checker_digest,
    approved_protected_pin_sha256=approved_protected_digest,
)
```

Save the exact returned bytes in a separate owner-private location and retain the enrollment SHA-256 independently. Keep the checker and protected-state pin digests from the independent release approval. The enrollment binds the original capsule and scoped candidate, controller tools and plan, application before image, checker archive and embedded exchange policy, protected pin, process custody directory, application and controller locks, and canonical source directory. The approved exchange must be closed before attempted installation or contingency observation.

## Supervise the original install

After closure and explicit authorization to run the real install, invoke the original controller only through this supervisor. Use the original approved launch environment.

```python
from preinstall_abort import capture_refused_install

refusal = capture_refused_install(
    enrollment, approved_enrollment_sha256=enrollment_digest,
)
```

The supervisor writes and syncs `launch.json` before spawn. It writes raw `stdout` and `stderr` to separate private files, records the original boot ID, PID and process start in `process.json`, then records the waited exit code in `exit.json`. The output and exit files are the coordinator’s record even when the helper reports a non-abort outcome. A successful install has exit code 0. Unexpected exit codes and recorded hold state require the matching controller recovery. Without a waited exit record, treat the invocation as uncertain and retain the entire directory.

An exact controller preflight refusal with empty stdout, exit code 1 and the original empty private transaction directory produces `refusal.json`. It binds the output to the enrolled original and acknowledged exchange. Review this original transcript and retain the refusal digest independently before requesting restoration.

## Observe and restore the approved disposition

After a witnessed refusal, use the refusal bytes and independently held digest.

```python
from host_exchange import encode
from preinstall_abort import observe_abort, restore_abort

plan_bytes = encode(observe_abort(
    enrollment, refusal,
    approved_enrollment_sha256=enrollment_digest,
    approved_attempt_sha256=refusal_digest,
))

restored = restore_abort(
    enrollment, refusal, approved_plan_bytes,
    approved_enrollment_sha256=enrollment_digest,
    approved_attempt_sha256=refusal_digest,
    approved_sha256=approved_plan_digest,
    enable_host_writes=True,
)
```

If closure ended before any invocation began, a separate observation and approval apply.

```python
from host_exchange import encode
from preinstall_abort import observe_not_invoked, restore_not_invoked

plan_bytes = encode(observe_not_invoked(
    enrollment, approved_enrollment_sha256=enrollment_digest,
))

restored = restore_not_invoked(
    enrollment, approved_plan_bytes,
    approved_enrollment_sha256=enrollment_digest,
    approved_sha256=approved_plan_digest,
    enable_host_writes=True,
)
```

In either case, submit the exact canonical plan bytes from observation to the independent approver first. Use the returned approved bytes and independently held digest for restore. An existing attempt record disqualifies the never-invoked route, even when spawn or exit evidence is incomplete. An approved never-invoked plan cannot be used once an invocation has started.

The observation and restore paths verify the full logical protected-state baseline using the original pinned checker archive in an isolated interpreter. The verifier requires the actual enrolled scraper lease. The helper checks the rest of the original leases, source images and refusal boundary on both sides of that verification. The mutation calls the same verification inside the approved exchange lock before any restore step. On an interrupted restore, use the same exact plan, enrollment, and refusal where applicable. Verify the returned witness is `restored`, its original generation and ordered paths match, and its terminal proof SHA-256 equals the approved plan digest.

## Verification scope

Fixture tests use a disposable checkout, the actual staged joint controller, the approved protected-state source in the checker zipapp, a real SQLite protected baseline, and the approved exchange implementation. The fixture checker’s external host attestation deliberately refuses. Separate output-routing tests use disposable processes to exercise success and unexpected exit handling. No live capsule, checkout, service, or Jetson was modified or tested.
