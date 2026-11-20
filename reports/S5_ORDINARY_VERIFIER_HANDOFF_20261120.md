# Sprint 5 bounded ordinary Rippling verifier handoff

**Independent QA accepted the exact offline verifier and its private receipt channel.** The pinned example binds the existing synthetic ordinary stale-response observation to the separately preserved Forterra and PDW public captures, then independently verifies the full exact inventories. It returned a private `VERIFIED_MISMATCH` evidence receipt after 114 metered reads. A 113-read limit returned `BUDGET_EXHAUSTED`. The receipt is labeled `offline_saved_captures` and has no application admission effect.

## Interface and ownership

The proposed private snapshot, execution pin, statuses and one-attempt restart rules are documented in [PENDING_CONTRACT.md](/tmp/jsh-s5-ordinary-verifier.povmDDEm/checkpoints/PENDING_CONTRACT.md). The snapshot freezes exact cycle and request, the target Company and source revision, the accepted Company-row projection including name, physical store/workbook identity digest, installed mapping/capability/configuration and qualification matrix digests, runtime binding digest, observation generation, and the provider lane's exact `rippling-tenant-mismatch-v1` payload. The independently supplied pending and job SHA-256 values are not read from the snapshot. The job pins the exact saved configured-response bytes, candidate replay pin, absolute deadline and request limit.

The job file is `ordinary-rippling-verification-job-v1` with `pending_sha256`, `candidate_replay_pin_sha256`, `mismatch_response_sha256`, `deadline_unix_ms`, and `request_limit`. The CLI takes `--slot`, `--evidence`, `--candidate`, `--reviewed-tools`, `--pending-sha256`, and `--job-sha256` under `python -I -S -B`. The slot contains `pending.json` and `job.json`. The separate private evidence directory contains `replay-pin.json`, `public-capture.json`, and `configured-response.html`. The CLI prints the result and private receipt digest. Exit 0 means the offline mismatch decision verified. Exit 1 covers every nonverifying disposition, with the explicit reason in the result.

The private supervisor opens no application stores and acquires only its own verifier mutex. It rejects inherited scraper-admission markers before reserving an attempt. The isolated worker receives one pipe descriptor for the exact reservation, with app descriptors closed, standard input redirected to `/dev/null`, and the child environment clear. It runs the previously accepted pinned authority validator offline, independently checks page-zero tenant metadata from the configured-response body, meters the authority/alias and dispatch reads, and keeps the raw captures on the host. The budget is bounded at 120 seconds and 128 reads. The supervisor enforces a hard child timeout, with a second monotonic deadline and interruption trap in the child.

A private reservation is committed before the child starts. An exact prior receipt is returned byte-equivalently under `REUSED`, including after expiry, with no additional replay. An interrupted reservation resolves to `HOLD`, or `TIMEOUT` at expiry, without spending a second allowance. A concurrent private invocation returns `BUSY`. A changed snapshot, replay pin, configured response, candidate vector, or physical slot is a nonverifying result. The verifier requires owned private paths and files. The future finisher must trust only its own designated private channel, re-read the current State identity and permissions, then perform its separate application admission. The checksum detects corruption inside the trusted channel. It does not authenticate records planted by a process already controlling that same private identity.

| Terminal disposition | Demonstrated case |
| --- | --- |
| `VERIFIED_MISMATCH` | Exact synthetic stale-response identity plus the saved independently reviewed employer/candidate/control evidence. Forterra 65 and PDW 33. |
| `HOLD` | Typed claimed tenant fails independent raw page identity, or a reserved attempt is interrupted within its deadline. |
| `BUDGET_EXHAUSTED` | 113 reads cannot complete the final public reread. |
| `TIMEOUT` | Expired job, interrupted reservation past cutoff, or active worker past the deadline. |
| `CHANGED_INPUT` | Pending generation, source/runtime/Company, receipt-bound response bytes, or physical private slot changes. No positive evidence is emitted. |

The scope is only this separate source overlay. It creates a reservation, mutex, and receipt in the explicitly supplied private temp slot. It has no Company-event, State, Jobs, mapping-fact, qualification, release, repair-task, or outcome write path. The coordinator and the other lanes retain those boundaries. This work does not exercise production, Jetson, Sheets, or GitHub.

## Pins and reproduction

Isolated tree `/tmp/jsh-s5-ordinary-verifier.povmDDEm`.

| Input | SHA-256 |
| --- | --- |
| `dev/ordinary_rippling_verifier.py` | `2925328cfae39a390cbac072a0834d10a580b0174555c1ef00fa9e418f7564c6` |
| `tests/test_ordinary_rippling_verifier.py` | `31611ebe3df5b933f2ab220af7f74447bf520b9f1b122a9a2bb22cf51dce3241` |
| Proposed pending contract | `5cc349244020b20cb3167d732e1e0c1f334cdddda6df521a9cad54d327491feb` |
| Exact replay candidate package | `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad` |
| Private public replay capture SHA | `75feafd84ced0cbeb8ce855eedbcb02ce8fe3582faeb034c10a924d34e992480` |

```bash
cd /tmp/jsh-s5-ordinary-verifier.povmDDEm
sha256sum -c checkpoints/QA_SHA256SUMS
sha256sum -c checkpoints/RECEIPT_SHA256SUMS
qa_tmp=$(mktemp -d /tmp/jsh-s5-ordinary-verifier-tests.XXXXXXXX)
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o pythonpath=dev --basetemp "$qa_tmp/pytest" -q --tb=short tests/test_ordinary_rippling_verifier.py
```

The focused run exited 0 with 19 tests passed. A combined run on the same pin exited 0 with 139 tests passed, including the previous public authority, synthetic and provider fixtures. [Combined test log](/tmp/jsh-s5-ordinary-verifier.povmDDEm/checkpoints/verifier-authority-regression-exact.log) These tests require the previously approved private offline host captures and do not fetch fresh evidence. The hash-only sample receipts can be inspected without the corpus. [Code and test pins](/tmp/jsh-s5-ordinary-verifier.povmDDEm/checkpoints/QA_SHA256SUMS) · [Sample receipt hashes](/tmp/jsh-s5-ordinary-verifier.povmDDEm/checkpoints/RECEIPT_SHA256SUMS) · [Focused test log](/tmp/jsh-s5-ordinary-verifier.povmDDEm/checkpoints/verifier-tests-exact.log)

## Independent QA and next seam

Independent QA verified the final source and manifest, reran all 19 maintained tests, and passed 27 independent checks. Real processes proved worker termination at cutoff, exact receipt reuse without a second replay, interruption before and after cutoff, rejection of mid-attempt generation and physical slot replacements, and isolation of caller standard input. The independent report SHA-256 is `d5aef1c13d237c01aa9794a40ac7d45df2a06a6aef7708768da7bac029ccdf7a`. [Final independent QA](/tmp/jsh-m5-validation-independent.pKaySTku/ordinary-verifier-qa.tcZEfQZy/ORDINARY_VERIFIER_FINAL_QA.md)

The integration owner needs to supply the exact pending snapshot from the assigned State marker and launch the private verifier only after relinquishing application leases. The separate local finisher still must verify current physical store, exact Company/source/runtime and publication precedence before any custody or outcome decision. The saved example deliberately pairs a synthetic mismatch with the historical reviewed public specimen, so this is offline prototype evidence only.
