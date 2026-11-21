# Independent public qualification retry — 2026-11-21

## Verdict: HOLD — provider rate limit

This was the single user-authorized post-cooldown retry.  It used the approved
production interpreter and the unchanged evaluator/candidate paths.  No second
attempt, installation, approval, service action, Sheets action, or Jetson action
was performed.

## Immutable inputs

- Retry preparation: `CAPTURE_PREPARATION.json`, SHA-256
  `7a59adb41005f4e5ea61821436203b54a30de3c1d90512ccf0c9e8a252ea13ac`
- Evaluator: `confirm_recipe_candidate.py`, SHA-256
  `a6b23ca6c41f7552e1990870870a022da846a1c6e844bcaf8d146b3a50e98e32`
- Candidate vector (256 entries): SHA-256
  `7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea`
  (verified before launch).
- Preparation candidate binding digest: SHA-256
  `6b5b7cae42683920e39a27bdaa1a7ddae04a7f19e27afcaae475fbb37b731152`.

## Execution and result

- Start: `2026-11-21T23:20:47Z`
- Terminal observation: `2026-11-21T23:21:54.230019Z`
- Terminal evaluator stage: `held_provider_rate_limit`
- Provider status: `429`
- Parsed Retry-After: `3600` seconds
- Earliest permitted next contact: `2026-11-22T00:21:54.230019Z`
- Evaluator terminal exit branch: `1` (rate-limit hold)

The stdout evidence contains 38 structured records; stderr is empty.  This
report deliberately contains only hashes and bounded status fields, not raw
provider payloads.

## Evidence files

- `QA_START_UTC.txt`: SHA-256 `a4d710e80df5f327d2286c84decff585b154c552f30c8b1781caa6acf7e8212e`
- `QA_STDOUT.log`: SHA-256 `1d33814c36798fe34942fb8b85e48849b5f94e5c997e39d09b7e08673a26a5c7`
- `QA_STDERR.log`: SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

No live qualification acceptance or release is established by this held attempt.
