# Sprint 3 source installation rehearsal

## Scope and results

The disposable transaction installed and rolled back the 19-file staged
source delta using the current production source bytes as its before state.
Thirteen files changed and six were added. The package's original inode,
all unaffected files and their inodes, the Sprint 1 parking sentinel,
fixture state, and simulated wrapper/sync settings stayed intact. Rollback
restored the original file inventory, including absence of all six additions.
The reviewed source endpoint manifest is at
`/tmp/jsh-s3-live-capsule-stage.jKfIWs0e/capsule/manifest.json`, hash
`d656cbc969868952382c3db16e8f2e9e4e94eefef94d8ae7dd332f2c41168ef9`.
The capsule is staged only. Its plan points to the real checkout and must
not be executed in a disposable test.

The separate deployment worker verified eight transaction fixtures, including
installer death after a file addition, death after an added-file rollback
unlink, interrupted package exchanges, and interruption around import
admission. The host-specific attester passed three focused fixture checks
for request and receipt identity, pre-pilot lifecycle conflicts, and manifest
binding. These fixtures did not use systemd, Google, or the job provider.

A read-only check on the actual host found mount ID 30 for both the checkout
and the private maintenance storage. No scraper-related user timer or path
unit was listed. The prior owner confirmation covers the alternate checkout
and scheduled jobs, and reading the effective user crontab remained
unavailable in this tool environment. The scraper and writer locks were
unowned at the sampled checkpoint. The sync unit was inactive and disabled,
and the wrapper was active and enabled. Reverify all routes under the real
hold. A planning baseline hashes protected production state without recording
job data in the report. Its private path is
`/tmp/jsh-s3-host/planning-witness.json`, hash
`9ad7ec7f357bd3478767c9f1804ee46fe71e122dded36f20ccb541002f3cf4cc`.

## Open acceptance

Independent review must confirm the final staged application and exact
capsule. Recheck native host services, producers, package resolution and
approved source pins before the guarded installation. Record a protected
before witness immediately prior to any source mutation, then compare under
the hold and after restoring the wrapper. Source-only rollback stops at
the first durable pilot effect. Read independently verified source after
installation before producing live signer claims or invoking Samtec.

Production source, databases, services and the workbook have had no
deployment or pilot changes in this rehearsal.

The full read-only preflight attestation also ran on MuleLab. It verified
the live-before package pin, approved source endpoint manifest, package
resolution for both checkouts, effective user service environment, exact
request and receipt, dormant sync, and current wrapper controls. This was
observational and did not acquire or release any production hold.

The source, tests and reviewed rehearsal materials were verified at GitHub
commit `d46edc9d5be5b49a90e1d6d96878108b8ab348d3` on
`backup/integration-automation-m1-operator-20261120`.
