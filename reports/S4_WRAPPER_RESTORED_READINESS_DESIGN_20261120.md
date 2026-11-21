# Sprint 4 wrapper startup and rollback recovery design

2026-11-20. Independent design from isolated source only. No live project, process, service, database or network was inspected or changed during this assignment. Current native state and measured churn below are coordinator-reported, not independently reobserved here.

## Decision

Separate two changes:

1. **Immediate held rollback recovery:** a narrowly approved replacement checker may add a bounded restored-stage settling period and retry an entirely fresh original attestation. It must preserve every existing acceptance check and original pin. This is a safe availability improvement, not a durable wrapper readiness guarantee. A failed or timed-out final pass still leaves the controller held.
2. **Permanent readiness:** add a cooperative startup-complete and database-activity barrier to the wrapper and controller in a separately reviewed source slice. An unchanged prior wrapper has no such interface; a controller-only delay cannot manufacture continuous serialization. Do not call a listener-only or sleeping wrapper application-ready.

The reported rollback has exact prior source installed, installer `ROLLED_BACK`, and controller `RELEASE_REFUSED` targeting `ROLLED_BACK`. Preserve that held transaction while testing. An expiring observer window does not authorize changing its evidence or racing another attempt.

## Verified source facts

Source roots used:

- `/tmp/jsh-s4-enrollment-release.EHxLVsCF` (controller, installer and candidate host/store).
- `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/tools` (isolated coordinator and supervision).

`candidate/dev/wrapper-coder/tools/host_server.py:265-270` binds its listener, constructs `Coordinator`, starts its background thread, then starts supervision asynchronously. The listener can therefore exist before initialization or the first supervision tick finishes.

`coordinator.py:573-615` returns from `start()` after thread start; the thread performs recovery inside its loop. `coordinator_supervision.py:195-210` starts a separate thread whose first action is `tick()`, with no readiness acknowledgement. The tick invokes catch-up, reads protected Jobs/Inventory with `mode=ro` (`:28-74`), and records supervision status through the coordinator Store (`:132-152`). `coordinator_store.py:194-276,675-683` initializes/open-closes writable SQLite connections. These are concrete concurrent storage seams, not proof of which file caused a given native failure.

`controller.py:425-442` treats systemd active as restored. `:932-937` then invokes the restored checkpoint immediately. There is no application-ready handshake or shared storage barrier between those operations. The coordinator reports that a final rollback replay observed 370 task WAL/SHM create-delete pairs, four main task DB modifications, and Jobs/Inbox sidecar activity during the startup/rehold interval. That demonstrates activity; it does not, by itself, identify which original logical records changed or which artifact triggered the failing comparison.

## Immediate checker-only recovery: conditions

Keep `controller.py`, `installer.py`, all application source, source manifest, original protected logical pin, original physical records, installer journal and every existing receipt byte-identical.

For `restored` only, before attempting acceptance, the new checker may perform a bounded wait for a quiet interval. A quiet observation is never success. Each acceptance attempt must construct a **new** request-scoped continuity object and rerun the complete original sequence: current stage/policy/owner, source/route/units/listener, full original logical protected witness, physical snapshot, launcher check, final owner/runtime/route checks, and continuity finalization. Use the same original request and target; emit exactly one verified response only after a complete successful pass.

- Retry only a separately classified transient SQLite/physical-continuity change that the reviewed checker explicitly permits retrying. Never retry away an unclassified error, changed source, changed original logical evidence, wrong owner, missing listener, failed publication evidence or expired external observation.
- Discard all partial attempt-local observations after a failed pass. Do not reuse a previous pass's listener, owner, physical snapshot, partial success or continuity `pending` state.
- Preserve bounded failure diagnostics and attempt count; do not report only the last success as if no interference occurred.
- Bound the total wait **inside the controller's existing 180-second non-short checkpoint deadline**, leaving room for one full attempt and cleanup. No unbounded sleeps or busy loop.
- Repeat finalization and exact physical checks after any slow checks. A future background tick is allowed only after the genuine successful measurement; it cannot be assumed absent merely because a quiet prefix was observed.

This can safely pass only if an actual complete stable interval exists. With frequent open/close churn it may never pass; that is a legitimate held result, not a reason to broaden criteria. It does not solve later steady-state verification races.

## Exact checker-binding amendment

There is no existing public checker-replacement operation in this controller. Replacing `host-check` alone makes normal recovery reject the transaction.

| Reference | Consequence of a checker change |
| --- | --- |
| `controller.py:103-106` `ref()` | Binds file device/inode, mode, ownership and digest; a hash-only journal edit is insufficient. |
| `controller.py:484-501` current `binding.files` | Includes `host-check`, controller, installer, verifier, plan and manifest. Only the exact checker entry is eligible for amendment. |
| `controller.py:532-550` `load()` | Requires the persisted journal binding to equal the newly measured binding. Checker and journal must form an explicitly reconciled pair. |
| `controller.py:514-515` `hook()` | Rechecks the current checker against that full recorded reference immediately before launch. Keep this unchanged. |
| `installer.py:392-411` transaction binding | Names the `verify_hold` path and exact source manifests, not the host-check digest. The completed installer transaction and receipt need no rewrite for this checker-only change. |
| `site-source/protected_continuity.py:75-81` | Its existing receipt binds `verifier_sha256`. Keep the old receipt unchanged; it cannot serve as the new checker's short-check proof. |
| `pilot_restore_command.py:20-24,57-73,93-97` | Selection includes the host-check hash and verifies it against controller binding. Preserve the old selection and prepare a fresh separately approved selection after amendment; do not relabel the prior approval. |
| `controller.py:990-1007` restoration terminal evidence | Includes the controller journal hash and original installer receipt hash. Any later restoration approval must use newly observed terminal evidence, not an older journal hash. |

The amendment must be a separate, independently reviewed local recovery helper with its own immutable input and durable journal. It should accept **only** the exact observed controller phase `RELEASE_REFUSED`, target `ROLLED_BACK`, completed rollback source/receipt, and all original identities. Hold the original controller/application/installer exclusion throughout; prove no controller process is concurrently running. Do not edit those lock files or substitute a new lock namespace.

Its approved input binds: original checker bytes and full file reference; new checker bytes and independently reviewed digest; original controller journal exact bytes/hash; the sole allowed replacement of its `binding.files[absolute_host_check_path]` reference; unchanged controller/installer/manifest/policy/protected-pin references; the exact rollback receipt; and an amendment ID. Embedded policy must remain identical except for separately enumerated diagnostic behavior in executable source—no new data baseline or ownership scope.

Persist and sync the amendment intent and recoverable old/new checker and journal images **before** touching the canonical pair. Preserve originals as immutable audit artifacts. Use exact preimage comparisons and durable replacement. The helper must recognize only:

1. old checker + old journal: pending, may install the approved new checker;
2. new checker + old journal: interrupted pair, may finish the sole approved journal binding update;
3. new checker + approved amended journal: verify and durably complete the amendment;
4. every other combination: hold without guessing or overwriting.

The normal controller must remain unable to run in the mixed state. After any crash, only the amendment helper reconciles that state under the same original exclusions. A controller journal must not be marked `RELEASED`, have its phase/target/source/receipt changed, or be given newly fabricated owner evidence by this helper. Preserve the exact original journal as historical evidence; the amended journal is an explicitly linked successor, not a rewritten account of the old run.

**Phase-specific advantage:** `controller.py:1056-1084` resumes this exact `RELEASE_REFUSED`/`ROLLED_BACK` state without rerunning the completed installer. Its next path is `release()`/`reopen_wrapper()` with full before-host-reopen, restoring and restored checks. It does not consume a short held continuity receipt. Restrict the helper to this path. Any earlier phase or resumed installer work needs genuine new held-controller enrollment and must not silently reuse or rewrite the old receipt.

No migration is accepted merely by this design. Test the paired-file interruption cases and the real controller's load/resume path before preparing a live amendment.

## Permanent startup and serialization mechanism

Add one wrapper-owned maintenance barrier shared by **every** route that can open protected SQLite, including constructor/recovery, scheduler idle polling, supervision/retention/catch-up, HTTP status and mutation routes, and shutdown. Cover connection open through final close: read-only opens can create sidecars, and close can remove them. An outer loop lock that releases before `close()` is insufficient.

Provide two distinct in-memory states, exposed without opening SQLite:

- `STARTING`: real constructor, recovery and first supervision observation are unfinished. A bound listener is not readiness.
- `READY_QUIESCED`: startup completed, all protected-store users are drained, no new protected-store user may enter, and the normal listener/HTTP loop remains responsive. The status response is strictly in-memory and names the current process incarnation plus release attempt.

A durable maintenance record binds the requested barrier to the release attempt and source generation; a stale PID or readiness file is never sufficient. The wrapper reestablishes this barrier on process restart. Controller verifies the matching current process/response, retains the barrier through the full restored witness and durable release decision, and explicitly releases it afterward. On controller death, the wrapper remains maintenance-held for a bounded recovery decision rather than treating the lost connection as approval. Ordinary controls remain disabled as required by the roadmap.

Startup may perform its normal initialization before acknowledging readiness; it may not change protected historical logical evidence and then approve a replacement baseline. If normal recovery changes a protected record, the original witness must hold and that change needs its own explanation.

Both prior and new deployed wrapper images must implement the same barrier before using it as a future rollback contract. The exact untouched prior image presently lacks this seam. Therefore introduce the common mechanism as a distinct reviewed prerequisite release or transparently named recovery support patch; retain the real original image and its evidence. Do not describe a patched prior image as byte-exact rollback. Do not use SIGSTOP, a fake listener, a cached health reply, or suppress the first supervision tick to pretend initialization completed.

## Realistic disposable fixture and gates

Use real SQLite files, the isolated `Store`, `Coordinator.start()` and `CoordinatorSupervision.start()`, and real threads. Seed only synthetic settled tasks/outcomes and disabled controls. Supply forbidden-network inference/catch-up callbacks and an external retention probe pointed exclusively at fixture Jobs/Inventory. Model listener readiness separately from worker readiness; test the listener remains available throughout quiescence.

1. Release a thread barrier after listener bind but before recovery/first tick. Show the existing restored check can overlap actual database/sidecar activity. Record per-role database/WAL/SHM/journal existence and stat changes, without inferring a row mutation from metadata alone.
2. Show a checkpointed fixture opened by the actual retention `mode=ro` reader can create sidecars. Show coordinator connection open/close and supervision writes independently, so a failing role can be discriminated.
3. New checker settling: transient startup churn ends, then an entirely fresh complete original attestation passes; continuous churn exhausts the deadline and remains held. Inject a stable changed protected row, wrong owner, wrong listener and unclassified error: none may be retried into success.
4. Permanent barrier: wait for real startup completion, request quiescence while a database user is deliberately blocked mid-transaction, and prove readiness is withheld until commit/rollback **and close**. Hold the barrier through the witness; all new scheduler/supervision/HTTP database entries wait or return maintenance status without opening SQLite. Exact original logical and physical checks pass without changing their rules.
5. Crash/restart: before readiness acknowledgement, after acknowledgement, during full witness, after controller release intent and before barrier release. Old readiness cannot be reused; no new scheduler or inference lane appears; watchdog distinguishes intentional quiescence from worker failure.
6. Checker amendment: inject a crash before intent sync, after checker replacement, after amended-journal replacement and after completion. The untouched real controller refuses mixed bindings, resumes the approved final pair, preserves installer/source/protected receipts and takes only the exact rollback-restoration path. Old rollback-selection pins refuse the new checker; fresh selection uses the linked amended evidence.

These are required staged tests, not executed acceptance evidence in this report. The immediate next implementation should be the smaller bounded-checker experiment and amendment fixture; retain the broader barrier as the permanent design if no full stable interval exists.
