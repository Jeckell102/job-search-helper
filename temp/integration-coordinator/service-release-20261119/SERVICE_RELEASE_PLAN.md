# Stopped MuleLab watcher release plan

These files are preparation only. Nothing here has been installed, enabled, or
started. The existing watcher remains inactive/disabled until a separate,
explicit host change is approved.

## Materials

- `job-search-sync-watch-retained.conf.template` is a per-user systemd drop-in template.
  It resets the inherited `ExecStart` then defines exactly one `sync watch`
  process. It loads an owner-only environment file and contains no key value.
- `retained-watch.env.template` names the public-key configuration and bounded
  request interval. It deliberately does not enable retained intake: that is a
  durable local dispatcher control and defaults off.
- `30-release-expiry.conf.template` is a separate, bounded replacement plan
  for a stale expiry `ExecCondition`. Its first blank assignment clears the old
  condition; the replacement must receive a reviewed future RFC3339 deadline.

## Safe host procedure after approval

1. Inspect the current merged unit and stale expiry condition.
   Capture the exact user-unit identity and paths, inactive/disabled result,
   merged-unit text digest, and
   `intake-status` JSON. Validate that capture with `verify_preinstall_gates.py`
   against the explicit sandbox root and verifier time; it uses the same
   byte-and-metadata binding as the installer, rather than a shape-only check;
   it must show both durable controls false before and after copy.
2. Copy templates to the stated host locations, substitute only project/user
   paths and a reviewed future deadline, and set the env file to mode 0600.
3. Run the offline verifier and `systemd-analyze verify`; inspect `systemctl cat`
   to confirm one watcher `ExecStart` and one fresh expiry condition.
4. Keep the unit stopped/disabled. Verify `intake-status` reports both durable
   gates false. Missing or malformed key configuration must yield only a
   retained-intake hold, never normal intake activation.
5. Only after a separate approval: reload daemon, enable/start, then inspect
   status and logs for no key/token output.

## Rollback

Before any approved copy, the offline harness persists the receipt defined by
`rollback-receipt.schema.json`. It first records PREPARED expected bytes hash,
owner UID, and mode for all three targets plus exact expiry preimage bytes;
then it records WRITING before, and COMMITTED after, every atomic replacement.
It refuses the installation before receipt creation when expiry's captured UID
is not the executing user's UID: this per-user harness does not have, and does
not attempt, an `fchown` restoration capability.
After interruption it removes only receipt-owned creates whose bytes/UID/mode
still match, and restores expiry only when its current content is either the
verified old preimage or the receipt-owned new content. Any drift is a hard
stop. The receipt and every capture path are confined to the supplied sandbox
root. Do not delete dispatcher journals, requests, locks, or retained receipts.
