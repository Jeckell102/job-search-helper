# Private native Amphenol maintenance adapter — source/disposable stage

**IMPLEMENTED; native use remains held for independent QA and actual live qualification.** No production file, application store, service, observer socket, provider, workbook, Jetson or GitHub action was performed. All new files are inside this mode-0700 directory. No import, constructor or default `ready()` invocation creates a fence or starts a worker.

## Root entry contract

Load `native_window.py` only after measuring its exact pin. Root owns the measured seven-tool loader, independent qualification owner, actual manifest and fresh release entry.

```python
window = native_window.create_window(
    release_id="REL-53592bb86b62492840c58267",
    manifest_sha256="9b02e2bb924666d240ec666d5ad6292def584e8f7155f89bfa3c465999fc323e",
    manifest=exact_canonical_manifest,
    qualification_check=reopen_and_require_actual_live_owner,
    window_root=private_mode_0700_window_directory,
    native_modules={
        "controller": controller,
        "host_exchange": host_exchange,
        "host_checkpoint": host_checkpoint,
        "site_policy": site_policy,
        "two_tool_route_drain": two_tool_route_drain,
        "quiet_window": amphenol_operator_quiet_window,
    },
    wrapper_scope_sha256=independently_approved_current_wrapper_fingerprint,
)
window.ready()  # inspection only; requires actual qualification and observer
# Only root's explicit execute path:
run_fresh_operator_release(
    approval=approval,
    original_outcome="OUT-1dc536eeadea2d283052b05d",
    request_sha256="f8c53183ae54bb8b66f79f92edc68d1e0a9d136ed8d2e21a07d7ff497fde7feb",
    completed_task_id="WRAP-11dc97a3dd",
    maintenance_scope=window.hold,
    execute=True,
)
# Explicit restoration-only recovery after a held/crashed window:
window.restore()
```

The qualification callback must reopen the independently pinned owner, call its real `require(manifest)`, then return exactly `{'release_id': ..., 'manifest_sha256': ...}`. A missing/wrong/held qualification stops before module loading, observer inspection or writes. Do not supply a test callback in a native entry.

The current wrapper fingerprint is `controller.unscoped(PROJECT / 'dev/wrapper-coder/tools', set())`, measured and approved independently as part of the current source scope. It binds the current complete wrapper directory's physical metadata as well as content. The historical -03 fingerprint cannot simply be compared after -05 changed Store's inode/mtime; its old receipts remain unchanged. The new window independently checks the exact historical terminal/transaction/source guard and exact current -05 receipt + source pair, then requires this fresh current fingerprint.

The three site modules **must originate from** the exact historical `.../s5-operator-trigger-20261121-03/host-check/<module>.py` ZIP paths. `_modules()` verifies full archive SHA `c0bec31ab59dbdc1064e2ee7003b9aa68e115d5902c34e43ebbe75058bf2a53e` and each member's hash via ZipFile. Loose copies are refused even when their individual bytes match. Root must also validate transitive import origins in its loader. Other supplied modules remain physical source files with the fixed accepted hashes in `MODULE_PINS`.

## What the adapter does

- Pins installed -05 receipt `60b29ffc98f4ef35399f9c9fdefe949f42f34b928a35b51e766dc0ba41d480cf`, -04 receipt and original -03 terminal/transaction, nine scoped endpoints, current host/Store, canonical package and parked guard identities, plus restored historical routes.
- Uses new observer identity `s5-amphenol-qualified-release-20261121-06` and `/run/jsh-s5-amphenol-release-06/observer.sock`. Both known restricted helper processes must receive a real authenticated current observation. Recovery also requires this before any service action. No observer is created or renewed by this module.
- Acquires only the existing `dev/wrapper-coder/repairs/deployment.lock` across the worker. No historical Controller terminal context and no scraper/writer lock is retained across yield.
- Re-enrolls a fresh HostExchange generation/control/journal using the existing three restored physical route pairs and the original approved module. Original policy, journal, terminal proof and route pins are not rewritten. It performs the existing prepare/close/restore transitions.
- Adds a private durable assistant-bridge condition fence and prior-state receipt; verifies stop/cgroup drain, then uses the unchanged accepted `OperatorQuietWindow.hold()` for wrapper/sync. It does not use the quiet window's historical-task `run()` convenience method.
- Requires exact source/config/dependency equality for unchanged-before or this exact COMPLETE release before restoring routes. A nonterminal application journal leaves the fences held for recovery. Wrapper readiness uses bounded observations without a second restart.
- Restores the original service states and exact route identities. Partial close and restoration cuts replay through `restore()` without invoking the worker, fetching provider data or replaying a remote write. A restored replay only verifies the retained terminal.

Files written by a future native invocation are limited to its supplied private window, fresh exchange control, the exact bridge/window condition files and service state covered by the existing fence. Source installation, application/retry/database/workbook effects belong exclusively to root's qualified worker.

## Disposable proof and limits

Nine tests pass under `/usr/bin/python3 -B -m unittest -v test_native_window` from this directory. This uses **real Linux directory exchanges, file custody, fresh exchange policies/journals and flock**, plus a byte-identical copy of the accepted quiet-window implementation. Services, root observer, current native lineage and application-state/qualification reads are substituted I/O boundaries.

Covered: missing approval/observer produces no effects; successful close→worker→restore with scraper lock available and deployment lock excluded; crash after a real first swap before journal update; wrapper restoration failure and re-fence; bridge start taking effect before error and re-fence; nonterminal application refusal; observer missing before recovery has no service effects; restored replay has no second worker/start; old receipt bytes preserved; exact archive/member/origin checks, including rejection of loose host_exchange.

Native lineage, real Systemd/cgroup behavior, current wrapper fingerprint, observer and actual qualified manifest require the independent native lane. This is not a deployed or application release acceptance. The adapter currently admits a **first install from the before source**; restoration is supported, but a second worker entry after an already-COMPLETE activation is not claimed by these fixtures. The accepted application one-shot has that recovery capability; qualifying any additional native re-entry window is a separate bounded requirement if the retry remains incomplete. Do not reuse a spent window to run the worker twice.

Private preparation can stop before its first native-window journal is written, leaving a fresh unused exchange preparation. Preserve it; do not delete/rewrite it to manufacture an unused attempt. No service or route closure occurs before the bridge prior state and fresh exchange binding are durable in native-window.json.

## Exact pins and debug history

| File | SHA-256 |
|---|---|
| native_window.py | `8f40d99f3718cee74cb5d522e648f41befde5ca1f3a4282650b711fc555ef069` |
| test_native_window.py | `0581e8a7020a553d2624ececc542b4adb48d07415a543e60285c712568f068ad` |
| DISPOSABLE_RESULT_SEALED.txt | `4c29a2f406e28dab674134903da6fac2db2db875373e08e83f3961976a3fb470` |
| vendor/host_exchange.py | `8168d900979d68aebc950d7bb8495705a5190368e8ca3ac932a7da4d4c7dfb1f` |
| vendor/quiet_window.py | `8b124170b12897dcc37a82d6a5af5ed38538fee22d9194ddf4146c2565a2fdc4` |

Earlier passing result files remain separate. A manual constant-length check found a copied 63-character -03 journal digest before this freeze; it was corrected against the saved independently accepted report and covered by an exact/grammar regression. Root's review then identified loose transitive site imports; the two site modules and subsequently host_exchange were restricted to the pinned ZIP, with negative fixtures. No service test or native dry-run was attempted to discover these issues. No display or tool transport failure occurred.
