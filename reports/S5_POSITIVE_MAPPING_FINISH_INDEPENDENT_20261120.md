# S5 positive ordinary finish: independent acceptance

Date: 2026-11-20. Reviewer: `/root/architecture_publication_review`.
Candidate: `/tmp/jsh-s5-positive-mapping-finish.hPxOkAlS`.
Design: `/tmp/jsh-s5-positive-finish-review.md`.

**ACCEPT for the staged positive-finisher source contract and disposable integration.** No blocking finding remains in this reviewed slice. This is not deployment, real-verdict issuance, live evidence, pilot completion or automatic release acceptance. No real issuer is provisioned in the reviewed scope.

Root retained sole ownership of candidate source and tests. This reviewer read source, ran disposable tests, and wrote only the independent `/tmp` probe and reports. No production application state, real jobs, Google calls, network, services, native locks or GitHub were operated by this review.

## What was verified

- `ordinary_live_mapping_verdict.py:43-72` requires a closed canonical verdict, exact approved bytes, live mode and positive application authority, matching dispatch/publication/verifier input/raw response manifest/reviewed tools, and digest-shaped evidence. The owner root is pinned to the held descriptor and expected physical identity (`:31-41,75-93`); inherited private file reads reject unsafe permissions, links and replacements. The positive finisher accepts the private authority type rather than a caller result dictionary (`ordinary_verification_finisher.py:85-103`).
- The runtime fact's durable binding includes the exact dispatch, archived publication hash and approved verdict hash. Enrollment requires that binding and the original qualification matrix (`runtime_mapping_facts.py:189-238`). Existing public runtime-fact and legacy Engine sealing entries cannot mint enrolled positive evidence without it.
- `runtime_mapping_facts.py:313-366` commits the verification binding, deterministic fact and exact State CAS seal in one transaction. `engine.py:498-559` builds a detached checkpoint without saving; the legacy helper (`:485-496`) still saves and updates the caller's in-memory fields only after success. This avoids nested `State.save_cycle` committing the new transaction early and preserves the existing legacy fact-only crash/retry behavior.
- The positive and no-repair cases share the existing lexical permit with an explicit repair tag. Its two branches remain disjoint (`ordinary_verification_finisher.py:35-65`): the old branch still rejects qualified repairs and repair categories; the positive branch requires the exact qualified mapping classification. At the actual Jobs insertion it checks the current Company and held qualification, exact State/Inbox/fact rows, and the still-approved receipt. Generic and public sealed writes remain reserved out.
- Existing immutable Jobs outcomes win before positive preparation and again within the Jobs transaction (`ordinary_verification_finisher.py:153-174`). The final terminal checkpoint is still separate. The tests prove atomic State rollback, reuse after State commit, rollback of Jobs insertion, and terminal-only reconciliation after Jobs commit even when the receipt has subsequently been withdrawn.
- The normal no-owner call remains pending for a current typed mismatch; paused source disposition remains `STALE_OR_PAUSED` without requiring a positive receipt or creating a fact. Offline mode, false authority, changed input/publication/capture/tools and an altered approved receipt do not produce positive evidence or an outcome.

## Independent execution

Interpreter: `/home/chris/job-search-helper_old/.venv/bin/python` (used solely as an interpreter for disposable source tests). Working directory: the candidate above. `PYTHONPATH=src:tests`, `PYTHONDONTWRITEBYTECODE=1`, pytest cache disabled.

Maintained focused and compatibility suite: **130 passed in 35.18s**.

```text
env PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1 /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_s5_live_mapping_finisher.py tests/test_runtime_mapping_facts.py tests/test_runtime_sealed_checkpoint.py tests/test_s5_ordinary_outcome_owner.py tests/test_s5_ordinary_publication_proof.py tests/test_s5_ordinary_publication_continuation.py tests/test_s5_ordinary_review_gate.py tests/test_s5_ordinary_verifier_handoff.py
```

Separate reviewer probes: **8 passed in 4.05s**.

```text
env PYTHONPATH=src:tests PYTHONDONTWRITEBYTECODE=1 /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q -p no:cacheprovider /tmp/test_jsh_s5_positive_finish_independent.py
```

These probes prove: changed approved bytes cannot create evidence; a caller verdict dictionary has no authority; changing the exact State, publication, fact row or selected Company's claim immediately before the real insertion prevents an outcome; a competing State checkpoint causes the fact/seal transaction to roll back without overwriting the competing progress; and failure after insertion but before Jobs commit rolls the outcome back, resets the lexical permit, continues to deny both public writers, and permits one exact subsequent retry. One initial reviewer probe accidentally selected an unrelated Company; it was corrected to the exact Company ID and all eight probes passed. No candidate change was made in response.

Total independent accepted execution: **138 passing cases**. Root's separate broader counts are not represented as this reviewer's execution.

## Exact pins

The candidate hashes were measured before and after the independent runs and remained unchanged.

| File, relative to candidate | SHA-256 |
| --- | --- |
| `src/job_search_helper/ordinary_live_mapping_verdict.py` | `cedb19aac2bac9944f222ebf7ac1e7ae8a2b89250be93496ffdbdf21f8fcff89` |
| `src/job_search_helper/ordinary_verification_finisher.py` | `7e99ce2d9c12475ffe8644171eb600ca59f537a8507e6eccdcdf28ff1838a5eb` |
| `src/job_search_helper/runtime_mapping_facts.py` | `1cd72ca24cc810cf1f94260392a0516a08498c29cede8a46f0807a763b950ebe` |
| `src/job_search_helper/engine.py` | `d2ea77e2a5d420bccf0e2d3fd728d5e4bd4b9bdf9fafc82e6622f8a2f42bd709` |
| `src/job_search_helper/ordinary_verification_outcome_owner.py` (unchanged) | `89c87d7838dba2342a1ccb3f4562ce10da8dec5ac8a9f881cbdb8926e6cc2ae5` |
| `tests/test_s5_live_mapping_finisher.py` | `3dccdd7376b86b3cce176b4b65f4491ef1243ea5b598ba7b8977973c3fafd50a` |
| `/tmp/test_jsh_s5_positive_finish_independent.py` | `ce648dea652f4d0a8bfa0dafc9b60ec7937b2af8cb403e25c3a1ad6b2ac9898d` |

## Limits and next gate

The reader proves the identity, custody and exact binding of an **already approved** verdict. It does not establish the semantic truth of a self-authored live-mode receipt. `live_capture_sha256`, `candidate_validation_sha256` and the three machine-evidence digests are assertions from that approved issuer; this reader does not separately execute the capture or candidate validator. The independent fixture deliberately fabricates those inputs for source testing and is not fresh live evidence.

Activation therefore still requires independently provisioned owner/approval/tools pins, a reviewed real issuer that issues those pins only after genuine current capture and candidate/regression validation, and the existing guarded release/pilot acceptance. Offline/public collection must not be relabeled to satisfy that gate. There is no autonomous issuer, live pilot, installed-system QA or broad release proof in this report.

State and Jobs remain separate commits by design. Their tested replay boundaries, not cross-database atomicity, justify the source acceptance. No acceptance criterion was relaxed.
