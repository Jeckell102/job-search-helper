# Two-tool coordinator update: shortest reviewed installation route

Coordinator readback after this assessment confirmed that the -03
`restoration_terminal()` rechecks its original `host_server.py` bytes.
The legitimate -04 update has already changed that file. Reuse the
same underlying lock and host checks under a fresh guard against the
verified -04 receipt and present two-file before-images. Retain -03
terminal and restored exchange as historical provenance. Calling -03's
terminal method unchanged cannot admit this update.

## Finding

The existing multi-path controller is **not suitable unchanged**.  Its
operator manifest is exactly nine paths (including `job-search-scraper`, the
launcher, bootstrap and application modules), and its parser rejects any other
or smaller source set.  The consolidated schemas are broader still.  Reusing
that controller would falsely make an application release out of a two-tool
update.

The closest approved mechanism is the completed one-file host forward:

* updater: `/tmp/jsh-amphenol-host-forward-maintenance/deploy_host_forward.py`
* native wiring/reference: `/tmp/jsh-amphenol-host-forward-maintenance/run_native_host_forward.py`
* predecessor controller and installed terminal: `/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03/controller.py`
* verified -04 predecessor receipt:
  `/home/chris/.local/state/job-search-helper-maintenance/s5-amphenol-host-source-20261121-04/host-forward-receipt.json`

It already holds `dev/wrapper-coder/repairs/deployment.lock`, enters the
installed predecessor controller's `restoration_terminal()`, checks default-off
controls and zero open inference from the coordinator database read-only,
checks the preserved source scope, atomically replaces bytes with a private
backup, restarts only `wrapper-development-host.service`, and emits a successor
or rollback receipt.  It explicitly leaves the -03 receipt historical.

## Minimal route

Adapt that updater once, narrowly, to a named two-tool manifest containing only
`dev/wrapper-coder/tools/coordinator_store.py` and
`dev/wrapper-coder/tools/host_server.py`, each with exact before/after hashes,
modes and private before-image backups.  Keep the same -04 receipt as the
predecessor and the same controller terminal/exchange proof.  Stop the wrapper
host, replace both files as one bounded transaction, restart it, and read back
the host listener plus its imported tool identities.  Publish a new two-tool
successor receipt; rollback restores both before-images and the old host.

No scraper, Sheets/Google, Jetson, source-package, launcher or `job-search-sync`
change is needed.  `job-search-sync.service` is already disabled/inactive in
the -03 controller record; it must be read-only verified as such, not started
or changed.

## Observer and blockers

There is no need for an application-release observer or a Jetson observer for
this tool-only window.  The existing controller's external host check remains
needed: it establishes the exclusive maintenance hold, verifies sync remains
inactive, the wrapper process/listener is the expected one, and no alternate
source consumer is active before replacement.  The updater's post-restart
probe must additionally prove the newly loaded Store and host hashes, rather
than treating a listening socket as import proof.

Hard blocker: there is no existing approved manifest schema that accepts
exactly these two paths, and the one-file updater is hash-constant for the old
host-only change.  A small predecessor-preserving two-file adaptation plus its
focused rollback/readback test is therefore required before any native action.
