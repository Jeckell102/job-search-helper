# Sprint 1 design QA: F3 maintenance exclusion

**Feasible for a closed, verified set of production entry points. A package
rename alone does not establish universal exclusion. Production installation
remains gated.** This review made no production, service, job data, GitHub, or
Jetson changes. The commands that would mutate production below are design
examples for a later authorized operation.

## Evidence from this review

- All 13 paths in the preflight rollback copy matched the production bytes and
  permission bits. All 13 candidate permission modes also match. The prior
  eight-file check against `37512dd` remains a host preflight item. That commit
  did not resolve in either local checkout inspected here.
- The production venv's editable-install `.pth` points straight to production
  `src`. A fresh default venv `find_spec` resolved to the production package
  without importing it. With `PYTHONPATH` set to
  `/home/chris/job-search-helper_old_copy/src`, the same probe resolved to the
  alternate package. There is also a backup checkout. The scraper shell wrapper
  appends inherited `PYTHONPATH` on its module route, and the old bootstrap
  appends inherited paths on worker exec. Treat alternate checkouts that can
  point to the same state, job DB, or workbook as production writers. Clean
  default resolution proves one invocation, not all launch environments.
- Production `src/job_search_helper` is a real directory on the checkout's
  ext4 mount. A holding directory directly under `src` is a practical
  same-mount destination, subject to a mount and inode check on the real host.
  libc exposes `renameat2` here. The available `mv` does not expose
  `--no-copy`; it is unsuitable as the safety primitive.
- The wrapper host inserts production `src` and imports production modules
  inside request handlers. Its user unit has `Restart=on-failure` and the
  tunnel wants it. The sync user unit launches `sync_cli watch` directly.
  The expiry timer's service only disables and stops sync. Keep sync disabled.
  The assistant bridge entry point has no application-package import and
  reads application SQLite in read-only mode and Sheets with read-only scope.
  It writes its own credentials/cursor in its bridge directory. Its static
  dependencies give no reason to hold it for this source upgrade. Verify the
  effective service command and overrides on the real host.
- This environment could not inspect the live user or system D-Bus, the full
  host process table, or the user's cron spool. Service and process coverage
  remains unverified here. No crash test of the exact installer was run in
  this design review.

## Smallest robust design within that boundary

1. Reserve the checkout with the installer lock already used by the other
   installers, `.integration-install.lock`. Coordinate an explicit hold on
   editing, Git operations that rewrite files, and any other installer for
   the window, including recovery. The lock serializes only cooperating
   writers and disappears when its owner dies. Recheck the accepted and
   rollback manifest, modes, base bytes and shared temporary-retry work
   under the hold. Snapshot the current non-scope package fingerprints to
   detect unexpected package edits while it moves. Keep a durable maintenance
   record on the production filesystem outside the moving package, with the
   exact base/target manifests, original package inode, all holding paths,
   intent, prior service state and recovery phase. Store recovery code and
   source-only rollback bytes durably outside that package. The existing
   `/tmp` copies are QA inputs, so a reboot-recoverable installer needs durable
   copies before any mutation.
2. Block service activation persistently, then stop and drain existing units
   and all child processes. A separate user-unit drop-in with
   `[Unit]` and `ConditionPathExists=!/absolute/path/to/maintenance-hold`
   can protect the wrapper host and sync across restart and reboot while
   preserving present enablement. Make the drop-ins and sentinel durable,
   reload the user manager, and verify effective configuration. A runtime
   mask is lost at reboot. The service files already occupy the usual
   per-user mask path, so do not assume a regular user mask will apply.
   Stop any other inventoried scheduler or launcher that may auto-retry,
   resolve a different checkout, or start a process with old launcher code.
3. Close admission before editing any of the 13 files. Atomically park the
   package at `src/.f3-maint-<id>/job_search_helper` under a private mode-0700
   directory, then fsync both parent directories and verify that the
   ordinary name is absent and the parked inode matches. Also park the two
   root shell launchers and root bootstrap by no-clobber renames before
   beginning replacements if retaining their entry points would permit a
   fallback or untracked bootstrap invocation. Keep normal root names
   absent during replacement preparation. A permanent package-rename-only
   scheme is insufficient if any alternate path remains reachable by
   production launchers. Explicitly close those launchers or isolate their
   access to the production resources. If such a writer cannot be ruled
   out, the design is a no-go.
4. With fresh starts closed, perform a second host census and drain all
   processes that entered before closure. Include idle Python sessions,
   reusable pools and forked children, pre-import or partially imported
   interpreters, scripts with an open file or directory descriptor, and
   processes already holding parsed launcher code. A Python module retained
   in memory will keep working after its filename moves. A suspended
   process could later resume with mixed code, so drain and exit it instead.
   Obtain and hold existing app writer locks as a second line of defense.
   For SQLite, candidate order is `scraper.lock`, `writer.lock`,
   `review-writeback.lock`; with Sheets mode deduplicate to `writer.lock`.
   Resolve the real backend and lock directory for every launch environment,
   and audit any additional writer locks. Never remove/re-create the lock
   inode to clear a clash. App locks are advisory and expire with the
   installer. Keep the persistent service/import boundary in force.
5. Replace the ten scoped files inside the parked package, preserving the
   non-scope tree, and stage the three root files while it is unreachable.
   Stage exact-file replacements beside their destinations, set and verify
   modes, fsync each file, replace atomically and fsync the containing
   directory. Verify intended hashes, modes, no unexpected tree changes and
   no stale bytecode for changed modules before restoring visibility. Old
   direct-module routes can consume timestamp-valid caches. Use a deliberate
   cache invalidation method confined to changed modules or prove every
   supported invocation bypasses their stale caches. Restore all three
   verified root files while canonical package admission is still held.
   Make the package's no-clobber rename back to its original name the final
   code-visibility commit, with service holds and live locks still in place.
   A canonical direct import can run immediately after that rename, so all
   code and pre-resume checks it depends on must be complete by that point.
6. If using the bootstrap's existing nonterminal release journal as a second
   guard, first save and classify its exact prior state and prove the terminal
   binding behavior. Both bootstraps read the effective state directory and
   reject an interrupted journal, but neither prevents direct-module routes.
   A prior terminal receipt may bind the old source/config and reject new
   startup if restored unchanged. Keep the journal untouched when using
   physical root-entry exclusion unless the release protocol requires a
   transition. A pending journal from another operation or an incompatible
   terminal binding blocks the cutover until reconciled through the owning
   protocol. Never clear an existing release journal as maintenance cleanup.
7. Recover from an external standard-library launcher. Reacquire the same
   locks, keep services held, and reconcile the physical inode/name and
   manifest against the record before any writes. An intermediate file may
   match base or target, but an unexpected third hash, recreated canonical
   directory or changed inode requires investigation. No shell EXIT trap
   should restore visibility automatically. Complete forward or restore only
   the exact 13 prior versions while the package stays parked, verify, then
   publish. If the package is already back after a crash, inspect and classify
   the visible set as committed before deciding whether to run a new guarded
   rollback. Restore only the prior service activation state after verified
   code visibility and normal read-only probes. Keep existing policy holds.

## Command shapes for an authorized rehearsal

Passive host checks, run from the checkout under the real host session:

```sh
stat -c '%d:%i %F %a %n' src src/job_search_helper
findmnt -T src/job_search_helper -o ID,TARGET,FSTYPE
systemctl --user list-units --all --type=service,timer,path,socket
systemctl --user list-unit-files --type=service,timer,path,socket
systemctl --user show -p ActiveState -p UnitFileState -p MainPID -p ControlGroup \
  -p FragmentPath -p DropInPaths \
  wrapper-development-host.service job-search-sync.service jetson-assistant-bridge.service
crontab -l
ps -eo pid,ppid,user,stat,comm,args
lslocks
lsof +D "$PWD/src/job_search_helper"
env -u PYTHONPATH .venv/bin/python -B -c \
  'import importlib.util as u; s=u.find_spec("job_search_helper"); print(s.origin if s else None)'
```

The process/descriptor checks are supplemental. Python typically closes source
files after import, so an empty `lsof` result proves little alone. Inspect
service cgroups and known supervisor and interactive sessions as well. Review
command lines and paths locally because they can include private details. Run
the import probe under each effective launcher cwd, interpreter and environment
without invoking application commands. An alternate spec or namespace package
during the hold is an unresolved route.

Core rename primitive for the installer, with absolute trusted paths, under
the installer lock and after journaling the intent. Repeat with source and
destination exchanged for the final package publication:

```python
import ctypes
import os
from pathlib import Path

def rename_no_replace(source: Path, target: Path) -> None:
    old = source.lstat()
    assert source.parent.stat().st_dev == target.parent.stat().st_dev == old.st_dev
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p,
                       ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(source), None, str(target))
    for directory in dict.fromkeys((source.parent, target.parent)):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    new = target.lstat()
    if os.path.lexists(source) or (old.st_dev, old.st_ino) != (new.st_dev, new.st_ino):
        raise RuntimeError("Rename postcondition failed")
```

In implementation, use explicit errors in place of the illustrative assertion,
validate physical directories and mount IDs (bind mounts can share a device
number), fsync the holding-directory creation, and propagate all rename and
fsync failures into held recovery. No fall back to copy/delete or to a
destination-overwriting rename.

## Required proof before release

Rehearse the exact installer and rollback on a version-matched disposable
copy with synthetic writers and no live credentials. Kill the installer after
persistent hold, after package rename, midway through package/root writes,
before package republish and just after republish before completion is
recorded. Repeat after rollback writes. At each point try the old and new
launchers and bootstrap, the editable console command, direct CLI/sync/
pipeline/review paths, a fallback checkout, and a delayed/forked process.
Verify service activation is denied when expected, scoped source is either
fully old or fully new whenever reachable, and no synthetic writes get
through during partial installation. Test concurrent source edit/recreated
path rejection and restart recovery. Afterwards independently check hashes,
modes, preserved policy holds, the release journal contract, and normal
read-only launch behavior. The preflight bootstrap test covers one journal
and lock failure mode. It does not cover this installation or its rollback.
