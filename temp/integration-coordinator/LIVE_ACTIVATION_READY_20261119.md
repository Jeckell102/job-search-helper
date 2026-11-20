# Live activation readiness — explicit user approval required

## Ready evidence

- Protected source is installed with rollback copies and strict tests passing.
- Existing Samtec operator request is preserved exactly and remains queued.
- Independent signer review accepted the live historical evidence package for
  cycle `CYC-B639C6D864EC` (In Progress, 800 members).
- Signed manifest digest:
  `ff9fc9003a9689c2b724a8013daaf8455c16917a5924df86664a933a9469a8e8`.
- Live recheck matched all cycle, membership, identity, inventory, job, and
  workbook evidence digests. A fresh preview differs only in its expected
  `created_at` and derived `manifest_digest` fields.
- Authorization expires `2026-11-22T12:00:00+00:00`, is `local_only`, and has
  both `settlement_authorized=false` and `publication_authorized=false`.
- Signed artifacts remain outside GitHub under
  `/tmp/job-search-helper-signing-20261119`; the private key is mode 0600 and
  has never been printed or passed to the application.
- Both intake gates remain disabled. The watcher service remains inactive,
  disabled, and expired.

## Blocker

The host safety approval layer rejected activation because an exception tied to
an unfinished 800-company historical cycle needs a fresh, explicit user
confirmation after the exact blast radius is disclosed. The rejected attempt
made no state change. Do not retry indirectly or via a workaround.

Required user confirmation:

`I explicitly approve activating the signed local-only exception for cycle CYC-B639C6D864EC so it may process disjoint one-company requests. I understand it is tied to an unfinished 800-company cycle; it may not settle, alter, replay, or publish that historical cycle.`
