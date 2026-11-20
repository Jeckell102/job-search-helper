# Sprint 3 maintenance entry

This is a disposable adaptation of the Sprint 1 controller. No production
bundle or host-specific attester is supplied here. The fixture attester and
fake service manager live only in the tests.

## Bundle and entry point

Prepare one mode-0700 durable bundle outside both the application checkout
and its runtime state, on the **same mount ID** as the checkout. Copy
`controller.py`, `installer.py`, `gate.py`, executable `verify_hold`, and the
independently reviewed executable MuleLab attester as `host-check`. Add
`candidate/`, `plan.json` and `manifest.json`. The candidate reproduces the
canonical root and `src/job_search_helper/` layout and carries the pinned
after file at every scoped path. Stage only approved source.

The only operator entry is below. Use the same bundle and verb to resume an
interrupted action. An approved rollback uses the same entry with
`rollback`; it does not require the original candidate directory after the
first durable transaction is written.

```sh
/usr/bin/python3.11 -I -B /absolute/private/s3-bundle/controller.py install
/usr/bin/python3.11 -I -B /absolute/private/s3-bundle/controller.py rollback
```

Preserve the bundle, controller receipt, transaction, and parked sentinel on
failure. A new Sprint 3 window uses `src/.s3-maintenance-package` and the unit
drop-in `zzzz-job-search-sprint3-maintenance.conf`. Leave the separate Sprint 1
bundle and its existing parked sentinel alone. Do not invoke the installer
or verifier as operator commands.

### Plan and manifest

`plan.json` has exactly these fields:

| Field | Required value |
| --- | --- |
| `project` | Canonical absolute checkout directory |
| `hold_id` | Fresh unique ASCII maintenance ID |
| `unit_directory` | Canonical absolute persistent user-unit directory |
| `systemctl` | Canonical absolute systemctl executable |
| `pycache_prefixes` | Array of all audited effective absolute custom cache prefixes |
| `manifest_sha256` | Lowercase SHA-256 of the exact approved `manifest.json` bytes |

The manifest is an object with exactly `schema` and `paths`. Schema is
`sprint-3-source-manifest-v1`. Map every exact relative target to an object
with `before`, `after`, and `owner`. The first two contain exactly
`{"mode":"0664","sha256":"<lowercase 64-hex SHA-256>"}`, except that an
approved addition has explicit JSON `null` for `before`. `owner` is
`[uid,gid]` for both sides where present. Modes have four octal digits.
Encode the whole object with Python
`json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"`,
then hash those UTF-8 bytes. Scope accepts only the root helper/scraper,
root bootstrap, or flat package Python modules other than `__init__.py`.
Configuration, tests, data, symlinks and nested paths are outside this
transaction. The manifest digest in the plan must come from the independent
review of the frozen source, never a runtime measurement accepted on its own.

## Stable attestation exchange

The controller invokes executable `host-check` from `/` with a five-second
timeout and one JSON object on stdin. The exact fields are:

| Field | Value |
| --- | --- |
| `schema` | `sprint-3-host-check-v1` |
| `nonce` | Fresh 32-character lowercase hex |
| `checkpoint` | `preflight`, `held:<name>`, `pre-publish`, `published`, or `admitted` |
| `project` | Absolute checkout |
| `package` | Exact package directory for the phase |
| `marker` | Effective state's `integration-release-journal.json` |
| `backend` | Effective backend. Verify `sqlite` for MuleLab |
| `target` | `INSTALLED` or `ROLLED_BACK` |
| `maintenance_id` | Plan's `hold_id` |
| `locks` | Absolute lock paths in order, starting with checkout `.integration-install.lock` |
| `pycache_prefixes` | The audited canonical cache-prefix array from the plan |
| `source_manifest_sha256` | The independently approved manifest file pin |

For SQLite the remaining locks are `scraper.lock`, `writer.lock`, then
`review-writeback.lock` next to the marker. The subprocess also inherits
`JSH_F3_HOST_PHASE` with the part of `checkpoint` before its first colon,
retained for compatibility with the Sprint 1 hook. Use the exact request to
bind the decision. Stdout must be the exact same object with just
`"verified":true` added. Refusal means nonzero exit. Do not echo logs or
protected data to stdout. The executable and the bundle inputs are bound in
the controller receipt and must persist across replay.

`package` is canonical at `preflight`, parked at `held:*` and
`pre-publish`, and canonical at `published` and `admitted`. The package
is guarded by the existing empty extension at `pre-publish` and
`published`. At `admitted` the extension is gone, but the release marker
and unit holds still apply. The separate `verify_hold` executable is the
installer-to-controller verifier. Its schema is `sprint-3-hold-check-v1`
with exactly `project,state,gate,marker,maintenance_id,source_manifest_sha256,
checkpoint,nonce` plus `schema`. It authenticates the controller/installer
process relationship and lock ownership, then delegates to the site
attester via the controller.

## Independent checks before authorizing use

- Pin the accepted exact final source paths, after bytes and modes, and
  the independently checked production before state and owners. Record
  protected state and non-scope input witnesses. Confirm the planned mount
  IDs, normal lock inodes, all interpreter/cache settings, and no historical
  release or other maintenance conflict.
- Establish a real maintenance window for producers, direct launches,
  source writers and both checkouts' same-workbook writers. Verify the
  loaded wrapper/sync unit conditions, empty affected cgroups, current
  task and inference safety, and owner-controlled shutdown of alternate
  writer routes. Preserve sync disabled, its expiry override, and the
  original wrapper activation state. A process-list snapshot alone is
  insufficient.
- Require no active or indeterminate operator journal, retained start,
  unpublished local work, or remote claim before replacing runtime-bound
  source. Repeat that examination on standalone rollback. This source
  controller never migrates, settles, or removes job data or authority
  records. A rollback after pilot activity needs the owning protocol's
  separate review.
- Bind the site's held and canonical probes to the appropriate package,
  target and exact manifest. Keep network, production provider, workbook,
  and app writer calls out of deployment probes. Review the guard's
  canonical-import closure and held fallback routes. Independently verify
  all scoped bytes, ownership, expected absences, non-scope witnesses,
  controls and unit state after completion, including separately checking
  the wrapper's startup catch-up effects on the protected databases.
- Run exact final application QA and a frozen-candidate maintenance
  rehearsal before real use. Do not treat the small disposable fixture as
  evidence of host quiescence, source acceptance or authority for a pilot.

## Disposable tests

```sh
cd /tmp/jsh-s3-maint
/usr/bin/python3.11 -B -m unittest -v test_maintenance
```

Fixtures use real kernel locks and atomic renames, independent verifier
subprocesses, fake units, and synthetic source/state only. The transaction
requires file and directory fsync and replays process death at explicit
boundaries. The suite does not simulate power loss or run actual systemd.
