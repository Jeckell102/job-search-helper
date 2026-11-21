# One-file MuleLab host forward repair: release-route finding

## Verdict

**Do not use the current full maintenance-successor controller for this repair.**
The smallest defensible route is a new, exact, host-only successor transaction
for `dev/wrapper-coder/tools/host_server.py`, patterned on the earlier F2/F8
protected host install.  It needs neither a full checkout exchange nor a root
observer *if* the host is demonstrably idle and a new one-file manifest,
rollback receipt, and independent readback are produced.  It cannot reuse the
old F2/F8 installer/receipt as authorization: that installer was pinned to an
older five-file package.

## Evidence

- `F2_F8_LEDGER_PROTECTED_INSTALL_20261119.md` records the narrow precedent:
  actual target `.../dev/wrapper-coder/tools`, an exact installer, retained
  `repairs/deployment.lock`, idle-host preflight, backup/atomic replacement,
  installed-byte hash verification, and an `INSTALLED_HASH_VERIFIED` receipt
  for only the declared files.  Its 98 tests did not dispatch work or access
  Google.
- `F8_SUPERVISION_CANDIDATE.md` establishes the host lifecycle boundary:
  `scheduler.lock` remains the sole task owner and `supervision.lock` permits
  one maintenance owner.  A planned stop must settle rather than create a
  second scheduler.
- The live pilot failure is a stale frozen queue-base/workspace issue, not a
  reason to alter the old task or global queue-base.  The independent failure
  review requires both to remain immutable and calls for a recipe-specific
  current typed source capture before any later choice dispatch
  (`S5_AMPHENOL_LIVE_BUILD_FAILURE_INDEPENDENT_QA_20261121.md`).
- `host_server.py` was in the nine-path `-03` source scope.  The current
  generic maintenance-successor admission is also unusable as a shortcut: it
  rejects an actual `RELEASED/INSTALLED` predecessor unless it is relabeled
  `ROLLED_BACK`, which the maintenance recheck correctly forbids
  (`S5_NATIVE_ROUTE_AND_SOURCE_MAINTENANCE_RECHECK_20261121.md`).

## Minimal guarded transaction

1. Build a **new one-file host-forward manifest** before touching the host. It
   must pin the current `host_server.py` preimage (the `-03` after-image),
   approved one-file after-image, mode/owner, focused source tests, the `-03`
   terminal receipt digest, and a before snapshot of jobs/state/app files.
   It must reject any mismatch; no global queue-base, old task workspace,
   application source, launcher, bootstrap, job data, or requests are in
   scope.
2. Acquire the retained coordinator `repairs/deployment.lock`; take the
   existing supervision ownership, request a planned host stop, and wait for
   an explicit idle state.  Refuse to proceed if scheduler/action/inference or
   writer work is active.  Do not kill a running action and do not start a
   second scheduler.
3. Backup and atomically replace **only** `host_server.py`; fsync and reread
   its after hash, mode and owner.  Reread the other eight `-03` paths and the
   jobs/state snapshot to prove them unchanged.
4. Write a new immutable `HOST_FORWARD_INSTALLED` receipt.  It must name the
   `-03` receipt as predecessor, record both file hashes and the unchanged
   paths/data snapshot, and retain a rollback location.  It must never edit or
   relabel the `-03` receipt.
5. Restart the host with all campaign/retry/release/autopilot controls still
   off.  Measure the executable/version hash, single-lock ownership, default
   controls, and unchanged jobs/state.  Permit at most a read-only/deterministic
   check of the terminal pilot evidence; no scrape, queue dispatch, inference,
   Sheets, or release.  If any check fails, atomically restore the backup and
   emit `HOST_FORWARD_ROLLED_BACK`.
6. Obtain independent QA of the transaction/receipt and the focused stale
   queue workspace regression before allowing a new operator-selected normal
   run.

## Receipt history rule

After a successful host-forward transaction, the `-03` receipt remains true
historical evidence of its installed nine-file image, but is no longer proof of
the current `host_server.py` image.  The new receipt is the current successor
for that file and explicitly bridges to `-03`.  On a verified rollback, record
the rollback receipt and make the restored `-03` image current by readback;
never rewrite either historical receipt.

## Specific remaining gap

There is no identified current generic installer/receipt schema that both
accepts the actual `RELEASED/INSTALLED` `-03` predecessor and records this
one-file successor relationship.  F2/F8 is strong execution precedent, not a
reusable authorization artifact; the current maintenance controller has the
opposite predecessor-target restriction.  The required addition is therefore
small but real: a separately reviewed one-file host-forward manifest/installer
and rollback receipt bridge.  Until that exists, a direct overwrite is not
authorized.  This is not a reason to widen the repair into a checkout exchange
or to touch the terminal task/queue workspace.
