# Sprint 1 installer hold contract

Controller owns hold establishment, route coverage and release. Installer owns
the exact source transaction. Use canonical absolute paths. Run the verifier
and installer from outside the project being replaced.

- Provide a stable empty gate file with mode 0600 and a single link, outside
  the project and transaction directory. The installer takes an exclusive
  nonblocking flock for the whole invocation. All hold changes, including
  recovery and teardown, must serialize on the same inode. The route closures
  must remain in force after process death, with no reliance on the flock
  itself for restart protection.
- Provide the actual backend-resolved `integration-release-journal.json`
  used by the bootstraps. It must be a regular file with a single link and a
  JSON object containing `"schema":"integration-release-journal-v1"`,
  `"state":"FOUNDATION_MAINTENANCE"` and `"maintenance_id":"<hold-id>"`.
  Keep the same contents for all retries. Reconcile an existing release
  journal separately. The installer does not modify the marker.
- Provide a trusted absolute verifier executable outside the project and
  transaction directory. It accepts one JSON object on stdin and returns the
  exact object with boolean `"verified":true` added, with status zero on
  success. Request fields are `schema` (sprint-1-hold-check-v1), `project`,
  `state`, `gate`, `marker`, `maintenance_id`, `checkpoint`, and `nonce`.
  It must independently confirm the correct journal path and hold identity,
  durable closure of all inventoried launch and write routes, quiescence of
  consumers and source writers, and the transaction ownership. Exit nonzero
  if any check fails. It must not acquire the installer gate. The installer
  checks at entry, before starting the durable journal, before each source
  replacement opportunity, and around terminal verification. Timeout is 15
  seconds per verifier call.
- Provide an existing, dedicated mode-0700 state directory owned by the
  installer user, outside the project and on the same filesystem as both
  source directories. CLI syntax is `installer.py install|rollback|verify
  --project PATH --state PATH --gate PATH --marker PATH --hold-id ID
  --verifier PATH [--candidate PATH] [--parked-package]`. Candidate required
  on first install and always uses the canonical candidate layout. Use
  `--parked-package` for the atomic exchange guard. The ten target modules
  then live at the fixed `PROJECT/src/.f3-maintenance-package` path. The
  installer binds the parked and canonical guard inodes, along with the
  project root and src directory, across replay and verification. Verify
  the terminal transaction before republishing the canonical package.
  After the first journal commit, both directions replay from durable
  transaction payloads. The installed transition may be rolled back, and a
  started rollback can only proceed in that direction.
- A zero exit with terminal receipt is still within the maintenance hold.
  The controller independently checks the terminal transaction receipt and
  exact source identity and verifies expected launcher behavior before
  releasing. A missing/inconsistent receipt, mixed source, verification
  failure or interrupted state must leave the hold in place. Do not use the
  installer as an admission gate or as the route closure mechanism.
- Verify stale bytecode handling before republishing. The two pinned
  `sync_cli.py` versions are both 10,900 bytes. The scoped installer does
  not modify Python bytecode caches; require supported consumers to bypass
  stale caches or handle them separately under the maintenance hold.

Source pins include all 13 byte hashes and modes. Their aggregates
(`MODE SHA256 RELATIVE_PATH\n`, sorted by path) are
`7db9d0c151a5a0f3599b1d942d315604ab20284362d35c9a6ec32b17c98f5cd6` before
and `a8341ba3eeca99a2e52e02a1372143340e7fd3eb84b678bd80b4b7267e79a847` after.
The 13-file byte-only after aggregate is
`8671e3886e6828e47f4faeea7773b2fa306f617546715516ed3e92ac12c4f54e`.
It is a subset of the 20-file accepted source/test manifest. All 20 snapshot
files match the local accepted commit ac2d02c51237eb8ffe17355a9437d133c4a42d6b,
whose aggregate exactly matches the acceptance report.
