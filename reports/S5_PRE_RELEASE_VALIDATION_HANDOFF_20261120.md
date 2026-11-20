# Milestone 5 candidate validation handoff

**Independent QA accepted the exact isolated Forterra and PDW fixture candidate.** The repaired fixture validator passed 109 scoped tests. Standalone replay returned `FIXTURE_PASS` for Forterra and PDW, accepted an explicit Forterra zero in a dedicated specimen, and returned `HOLD` when the last Forterra page was removed. The candidate contains the already-produced, working Forterra mapping from the coordinator’s frozen normal-dispatch snapshot. This result covers that exact fixture candidate. A later generated repair build needs its own pin and validation.

## Exact baseline and candidate

- Isolated tree `/tmp/jsh-m5-pre-release-validation.OHy7TsMZ`. Candidate provider package matches `/tmp/jsh-s5-ordinary-sealed-evidence-red.PBkhfctW/frozen-source` byte for byte and also matched the coordinator’s dispatch-binding QA source. Production Git HEAD observed read-only at `c9db537d76dcb4dc22ace5d6342adc35c1085688`, with working changes. Coordinator Git HEAD observed at `0b9698a58cca10507d967efd4ce866d45842e0c0`.
- Exact execution vector under the isolated fixture environment. Source `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad`, configuration `fafe5191319d13d4c329a6a9e1913460f07b24ad46dbd398c43a0ad430afa1d8`, dependency policy `d633e308a88f1056ea979f2024a9a0b92c76f3fb6c0030130a79abeb21156d5d`. The existing independent admission bootstrap measures the vector and is separately pinned at `c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f`. The replay executes verified Python bytes from a private measured snapshot with the standard library only. The receipt also records the interpreter fingerprint, original and execution vectors, tool hashes, exact Company/capture scope, and per-response hashes.

## Owned files

| Path in isolated tree | SHA-256 |
| --- | --- |
| `dev/pre_release_validation/rippling_capture.py` | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| `dev/pre_release_validation/validate_candidate.py` | `47c734bc718dfbed60e2d15044e72f061715e2a05b7f47fa3f1f3f2089c44dc0` |
| `tests/test_pre_release_candidate_validation.py` | `5e3883a738f037c25c97b30596871d5b487fa2ddf8248c3ba0e5ec2453d5020c` |

## Verification

```bash
cd /tmp/jsh-m5-pre-release-validation.OHy7TsMZ
sha256sum -c checkpoints/INTEGRATED_SHA256SUMS
sha256sum -c checkpoints/SAMPLE_SHA256SUMS
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o 'pythonpath=src .' -q tests/test_pre_release_candidate_validation.py \
  tests/test_shared_boards.py tests/test_rippling_locations.py \
  tests/test_source_routing_recovery.py tests/test_inventory_source_validation.py \
  tests/test_integration_release.py tests/test_release_admission_bootstrap.py \
  tests/test_release_controller.py
/home/chris/job-search-helper_old/.venv/bin/python -I -S -B \
  dev/pre_release_validation/validate_candidate.py --candidate-root "$PWD" \
  --measurement-tool release_admission_bootstrap.py --pin checkpoints/replay-sample/pin.json \
  --capture checkpoints/replay-sample/capture.json
```

Scoped suite exit 0, **109 passed** including 26 dedicated. The extended suite exited 1 with 117 passes and the same two failures reproduced on the unchanged baseline in `test_fresh_scan_request.py` because legacy fixtures supply a memory repository to the newer SQLite-only Company-event admission path. Early extended run also lacked the checkout root on Python’s import path. The command above includes it. [Scoped test log](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/final-scoped-tests.log) · [Baseline failures](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/unchanged-baseline-broader.log) · [Extended comparison](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/extended-final.log)

| Standalone replay | Exit | Evidence |
| --- | --- | --- |
| Forterra inventory and PDW control | 0 | 62 Forterra jobs across `20/20/20/2` on each of two reads, 1 PDW job, exact scoped IDs/URLs/titles/full visible descriptions from the independent oracle. |
| Explicit zero and PDW control | 0 | Two authorized, unfiltered Forterra replies each explicitly report zero. PDW returned 1 fixture job. |
| Missing last page | 1 | Forterra held for missing scoped response. PDW remained independently observable. |

[Inventory receipt](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/replay-sample/receipt.json) · [Zero receipt](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/zero-sample/receipt.json) · [Hold receipt](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/hold-sample/receipt.json) · [All sample hashes](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/SAMPLE_SHA256SUMS)

## Independent QA

Initial verdict HOLD. The reviewer reproduced substituted or omitted employer scope, a version check bypass through a temporary source replacement, inert zero and description markup, and superseded iframe authority. The repaired candidate requires both independently pinned scopes, executes only manifest-verified retained Python bytes, and excludes inert markup and `srcdoc` override. Independent QA verified all file hashes, passed its combined 62-test rerun, reran and closed the earlier defects, and passed three deterministic source-race probes. A disposable release activation refused the exact fixture receipt digest and created no completed release receipt. The final report is pinned at `cc3e2245f1beda43cedb67bc679869e2c2d69e2d18ebf30ab075c06cc2afa213`. [Initial QA](/tmp/jsh-m5-validation-independent.pKaySTku/INITIAL_QA.md) · [Final independent QA](/tmp/jsh-m5-validation-independent.pKaySTku/FINAL_QA.md)

## Evidence limits and coordinator handoff

- This is an offline qualification specimen for named Rippling boards, using a synthetic Forterra paging shape and a distinct synthetic PDW control. The standalone tool calls the ordinary `ats.fetch_inventory` dispatch with one Company at a time. The integration test independently starts and resumes real Engine company-only cycles and isolates their stores. No current public counts, live descriptions, storage or Sheets publication, generated repair, runtime fact adoption, rollout, or retry was exercised.
- The independent proof holds on malformed, missing, foreign, filtered, or unstable evidence. The fixture subset holds duplicate UUIDs in these two boards and requires a visible role body. Alternate provider and location-duplicate contracts need their own reviewed evidence. The scoped zero receipt comes from the separate independent oracle and normal dispatch reread. It does not create a runtime zero fact.
- The validator is for reviewed local candidates and fixture evidence. Its Python and workbook/network barriers are not a containment claim for untrusted executable code. Private snapshot and verified module bytes close the tested replacement window. The exact working copy must be controlled while capturing dependent file and configuration measurements.
- For integration, carry the three owned files and the sample/reproduction artifacts as needed. A separately authorized lane must independently capture current employer and provider evidence for the final repair candidate and review it through normal-dispatch live qualification. Bind that exact candidate, Company revision and validated public receipt to the existing release manifest. The existing release installer accepts `PASS`; this fixture tool emits `FIXTURE_PASS` and will not authorize an install. The release owner still owns exact JSON companion mapping policy, release admission, and retry durability. No shared-file change was required for this lane.

[Assignments](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/ASSIGNMENTS.md) · [Baseline](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/BASELINE.md) · [Checkpoints](/tmp/jsh-m5-pre-release-validation.OHy7TsMZ/checkpoints/INTEGRATED.md)
