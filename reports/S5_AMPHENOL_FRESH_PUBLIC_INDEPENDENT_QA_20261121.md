# Independent public qualification — Amphenol fresh candidate

Verdict: **HOLD — provider rate limit; not qualified for release**

One public evaluator invocation was made after local preparation verification.
The initial launch request was aborted before dispatch by the execution gateway;
the subsequently recorded invocation is the sole provider-contacting run. No
retry was made.

## Immutable preparation binding

- Task: `WRAP-11dc97a3dd`
- Operator request SHA-256:
  `f8c53183ae54bb8b66f79f92edc68d1e0a9d136ed8d2e21a07d7ff497fde7feb`
- Capture preparation: `CAPTURE_PREPARATION.json`
- Capture preparation SHA-256:
  `dbf3196f8ff5e2467ae00a1b7ec0c7cf4afcfd66996f5ee70cf697fba40ac7ea`
- Evaluator SHA-256:
  `a6b23ca6c41f7552e1990870870a022da846a1c6e844bcaf8d146b3a50e98e32`
- Candidate source vector: 256 files, SHA-256
  `7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea`
- Candidate wrapper SHA-256:
  `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`
- Candidate delta was restricted to the accepted wrapper candidate; preparation
  checks passed before public contact.

## Single-run terminal evidence

- Start UTC: `2026-11-21T21:47:52Z`
- Terminal observed UTC: `2026-11-21T21:48:54.201935Z`
- First terminal hold: detail response HTTP `429`
- Provider Retry-After: `3600` seconds
- Do-not-contact-before: `2026-11-21T22:48:54.201935Z`
- Observed complete listing total before the hold: `39`
- Successful detail HTTP 200 observations before the first 429: `32`
- No `separate_candidate_confirmation_passed` event was emitted.
- No source installation, release, Sheets action, backup action, or runtime
  service action was performed.

The evaluator's rate-limit branch returns exit code `1`; the evaluator process
is no longer present. The launch wrapper did not persist its own post-command
exit capture, so `QA_EXIT_CODE.txt` records the evaluator's explicit terminal
branch rather than claiming a separately captured shell status.

## Private log custody

- `QA_START_UTC.txt`: start marker.
- `QA_END_UTC.txt`: terminal event time from the evaluator's JSON record.
- `QA_STDOUT.log`: structured evaluator events, retained privately.
- `QA_STDERR.log`: empty.
- `QA_EXIT_CODE.txt`: evaluator terminal branch (`1`).

This evidence is a hold only. A later public qualification would need separate
authorization after the provider cooldown; it is not authorized by this run.
