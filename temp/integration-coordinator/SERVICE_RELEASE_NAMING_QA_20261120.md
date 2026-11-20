# Independent QA — service release staging-name reconciliation

**Verdict: ACCEPT for the offline package only.** This does not authorize a
host install, service start/enable, intake activation, Google contact, or live
scraping.

## Scope and result

The package now uses exactly one managed expiry artifact from preparation
through rollback:

- template: `expiry.conf.template`
- generated/staged file: `expiry.conf`
- install and rollback target:
  `/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf`

The obsolete `30-release-expiry.conf.template` is removed. Both the generated
artifact verifier and the installer require the exact stage set
`{20-retained.conf, expiry.conf, retained-watch.env}`. An extra
`unmanaged.conf` is rejected with `stage_files_invalid` before a receipt is
created or any target changes.

## Independent evidence

Independent QA reproduced the former surplus-file path and confirmed the fixed
installer fails closed with no receipt, unchanged expiry bytes, and no unit or
environment target. The following offline checks passed:

- `git diff --check`
- release-template verification
- positive and negative generated-package tests
- receipt/recovery/fault-injection harness tests
- Python compilation

No host, service, Google, database, gate, request, cycle, or live state was
changed.

Reviewed SHA-256 values:

- `expiry.conf.template`:
  `f52517ea3e5fc708da4f617c46e2f2b9e83b9ab335d7c2914b3f49f2b5e78077`
- `offline_release_harness.py`:
  `a8fb503f572712ccb47ed701a623662ceb58f276f68b1f4d863bdcea528b2b35`
- `test_offline_release_harness.py`:
  `939c173a02a0978dfab7938ddfa5defdfb3e3dd5cb7363e945dbb05d92ebab68`
- `test_release_package.py`:
  `bc2ff2bd0cbf8e94d2c76a24a386a931e9139a7369b22fd5a3bff798a52349a3`
- `verify_generated_release.py`:
  `57822f0a8d918188d8dd6a6645c37250e4746073e1aa13872a202eb0d679a78e`

## Remaining gate

The corrected package is still only an offline accepted release package. A
fresh, explicitly authorized host preflight and separately guarded install are
required before any host file is changed. The service and both intake gates
must remain stopped/disabled until that later gate is satisfied.
