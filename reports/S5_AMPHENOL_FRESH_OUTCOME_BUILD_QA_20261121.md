# Independent QA — Amphenol fresh outcome and private build

Status: **ACCEPT — M4 outcome and private build custody**

Status: **HOLD — live validation, installation, and release**

Scope: read-only verification after the single authorized request. No provider,
inference, task, candidate, service, or source action was performed by QA.

## Bound request and settled source outcome

- Operator request: `operator-amphenol-20261121-05`
- Exact request SHA-256: `f8c53183ae54bb8b66f79f92edc68d1e0a9d136ed8d2e21a07d7ff497fde7feb`
- Company/source revision: `COMP-0490` / `b7a94094c57cb879e25db5aef9de565437f8ec5a855ad7b1275958e944f6a501`
- Settled cycle/outcome: `CYC-7EA6397B40D6` / `OUT-1dc536eeadea2d283052b05d`
- Classification/action: `QUALIFIED_INTEGRATION_REPAIR` / `upsert_qualified_repair`
- Frozen observation logical SHA-256: `faa27709e000774ee2974869e5405725ce8d1f24758a9bdeb015cf2e92b75136`
- Frozen inventory SHA-256: `75c743369c376870605eab8df65a50729c9544ff5ea2ce1238aa4412c4ff6ded`

## Exact delivery and new owner

The sender record and coordinator receiver agree on the same new outcome.

- Sender record SHA-256: `698dcd962b9f91294878bdae2fe87cf25b3d941e2112ee5eeffaad14eb506e29`
- Sender/receiver receipt ID: `ODR-3563471177baaa96ae7b964a`
- Sender/receiver receipt SHA-256: `1167c2ad6df3851b5c3546d24dfc669771e1f83e313b4542dc43b5e35580404b`
- Receiver disposition: `HELD_FOR_REPAIR_TRIAGE`
- Fresh successor repair key: `ce5a6e7477bc4a791d4395cd4f55b75ee2e0bcaf5960715d277506544f1bcba2`
- New owner: `WRAP-11dc97a3dd`, state `PROMOTED_PAUSED`

## Private build acceptance

The installed trusted `_read_completed_build` reader accepted the owner/task,
its single inference receipt, and the W1 choice binding.

- Task: `WRAP-11dc97a3dd`
- State: `REVIEW_COMPLETE_LIVE_NOT_VALIDATED`
- Inference: exactly one completed receipt, `d73599ddd718448bb9fa1297af268a08`
- Selected result: `W1` / `listing_membership_change` / `phase_done`
- Candidate directory:
  `/home/chris/job-search-helper_old/dev/wrapper-coder/tasks/WRAP-11dc97a3dd/recipe-candidate`
- Candidate source: `src/job_search_helper/acquiretm.py`
- Candidate source SHA-256: `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`
- Candidate patch SHA-256: `ce042dffa0addfdbb04e14e450d6e5ae3979d2c881bd1ff9bf9c8173ce749abc`
- Candidate build receipt SHA-256: `aa12f5a86dbd13094f1473c79b1ca14840e1821bb3bbb2194dd9fee1e01578a5`
- Installed source SHA-256 remained `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61`.

## Safety and predecessor proof

- Open inference at observation: `0`.
- No duplicate fresh inference receipt was present; the fresh task had one call.
- Retired/predecessor task `WRAP-6a3a372032` remained `PAUSED_ERROR`, with
  one session and one call.
- Canonical predecessor task-state SHA-256 remained
  `a6be4e6c48b6133dffb53f40fc8459650e9c84a5d177d3962570b0289f7405df`.

## Hold boundary

This evidence accepts the bounded M4 source outcome, receipt handoff, and
private task-owned build only. The candidate has not been live validated,
installed, or released. Those gates remain closed pending their separate
authorization and acceptance evidence.
