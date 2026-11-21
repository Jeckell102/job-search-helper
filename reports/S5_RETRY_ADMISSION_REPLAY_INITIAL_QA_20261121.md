# Scoped repair retry admission replay

**REJECT** candidate `97f3ce7acfc1c71737a1f1d0bbe43cf833f6ad09aef574b5387f426edce4eaca`. The source fixes duplicate queue-file creation after a normal admission. Its new recognition path still returns `REQUEST_ALREADY_ADMITTED` for stored checkpoints that lack the exact installed runtime, carry another owner, or omit most of the required intake measurement.

## Verified pins and results

- Baseline `repair_retry.py` SHA-256 `a15653e38d2026cc1f06a40fb194641256619995f0a0a736e847d41a0641b356`. The authored normal Jobs and State regression reproduced `REQUEST_WRITTEN` after a successful `requested_scan` consumption.
- Author test SHA-256 `e3714ced87185c572d84f416f20942c649f793ed26ccdcfe9fb2376d893228d8`. All seven tests passed on the candidate, including a cut before request consumption and incomplete, foreign, or duplicate matching State evidence.
- Eight independent parameter cases used the same real, disposable SQLite fixture and normal `requested_scan`. Four passed. A complete or superseded cycle retained one immutable retry. A foreign pending request was preserved byte for byte. A State database missing the cycles schema held without mutation, and the valid connection was read-only and closed.
- Four independent cases failed. Starting from one consumed retry, deleting `runtime_binding`, replacing its source manifest digest, or setting `retained_work_exception` should hold. The public app's existing `repair_retry_receipt_binding` rejected all three saved rows, while `RepairRetryBridge.deliver` accepted them. A fourth case left only `condition` and the matching `started_at` in `intake_start_measurement`. That truncated checkpoint was also accepted.

## Small correction

In `RepairRetryBridge._already_admitted`, retain exact persisted request ID, fingerprint, and retry binding checks. Reuse `exact_cycle_receipt.repair_retry_receipt_binding` for the same canonical Company scope, no competing owners, frozen source and COMPLETE installed release runtime required by publication. Verify the full ordinary idle or busy intake measurement using the existing calculation and the persisted anchor. Preserve complete and superseded exact rows and the existing pending-slot behavior.

The four red probes and four positive controls are in `test_independent.py`. Both test runs used the system Python 3.11 executable with bytecode and plugin autoload disabled and an audit hook rejecting sockets and child processes. Installed libraries supplied test dependencies. No repository or candidate edits, native app state, real provider, Google, Jetson, network, or deployment effects.
