# Independent QA — stopped watcher service-release package — final UID repair

**Verdict: ACCEPT for the offline, guarded protected-source installation
package only.** This is not authorization to install it on the host, start or
enable a service, change intake gates, or contact Google.

## Fresh evidence (2026-11-19)

The narrow ownership repair closes the prior rejection. In
`service-release-20261119/offline_release_harness.py`:

* `verify_preflight()` constructs the complete expiry preimage
  `(sha256, uid, mode)`, rejects a UID that is not the installer UID with
  `expiry_owner_not_installer`, then checks the live expiry target against that
  complete preimage. It happens before `install()` constructs or writes its
  receipt and before any managed target is changed.
* The harness deliberately has no safe `fchown` path. Refusing an expiry file
  it could not restore is the correct fail-closed behavior, rather than
  silently changing ownership.
* Rollback's final `_matches(expiry, old_meta)` remains a complete
  hash/UID/mode check. A restore whose owner changes after the old bytes are
  restored raises `rollback_restore_failed`; it cannot be marked rolled back.
* Receipt ownership is durable before each target write (`PREPARED`, then
  per-target `WRITING`, then `COMMITTED`), and rollback still refuses foreign
  drift rather than deleting it.

The focused tests prove both requested cases:

1. A foreign `expiry_uid` is refused with `expiry_owner_not_installer`; the
   receipt does not exist, old expiry bytes remain, and neither create target
   exists.
2. A simulated owner change after expiry restoration makes rollback raise
   `rollback_restore_failed`. This directly exercises the retained final UID
   comparison.

## Independent offline run

Run from the package directory with
`/home/chris/job-search-helper_old/.venv/bin/python`:

* `-m py_compile *.py` — passed.
* `test_release_package.py` — `positive and negative release-package checks passed`.
* `test_offline_release_harness.py` — `offline receipt ownership, recovery, drift refusal, and shared preflight checks passed`.
* `verify_release_templates.py` — `release templates are offline, single-watcher, and default-off`.

Reviewed final artifacts:

* `offline_release_harness.py` SHA-256
  `f4266717e32f75e4e276100a5cc0d348029fca274e8cd365bf9a081a0ab2c61c`
* `test_offline_release_harness.py` SHA-256
  `6e0cb36f1ca58a2400bda417e1f5c163be4703771c1d28d37fd8901beac76629`

## Remaining deployment gate

Before any real installation, an explicitly authorized, read-only host
preflight must freshly establish the exact per-user service identity,
inactive-and-disabled state, both intake gates off, current merged-unit digest,
replace-target preimage (including owner), future expiry, and owner-only
environment permissions. Installation and a separate stopped/disabled
post-install validation remain out of scope for this offline acceptance.
