# Next Amphenol public qualification window

Recommendation: one separately recorded fresh normal-dispatch confirmation using the already accepted `confirm_recipe_candidate.py`, unchanged, against its exact frozen candidate. This is one whole scoped scrape, not one HTTP request. Do not precede it with an availability probe or immediately follow it with another scrape. Stop this new window after the one result, including a hold. This report performs no external call or native application/database/service action.

## Verified saved evidence

At review time 2026-11-21 18:14:43 UTC (13:14 Eastern), artifact hashes remained:

- `evidence.jsonl`: dfd69d46fd48deeeab7feb88d457ba01978d5ef5d4ae4548adc076df5d41638e. Window started 17:16:34.757306 UTC. Run1: complete39, two complete listing observations and39 observed descriptions, then run_verified. Run2: blocked after35 descriptions, one initial listing, no run_verified.
- `confirmation.jsonl`: 7fe4af029b0f6f40b7b97ea1ebc02ad812e9aa344965f4c38281aa364f3f8d01. Started17:32:43.798759 UTC. Run3: blocked after37 descriptions, one initial listing, then failed/normal dispatch not complete. No final listing or successful confirmation.
- Exact candidate still has256 measured Python/config members, vector7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea; adapter895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d and dispatcher111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e.
- Confirmation evaluator43ab6b9f3899b289992d95d9e79c6ff3c625fa7518cdb969bfda06fcc2a753a5; preparation78a95e901880291ac54c8d0739818dd1cacc64c1d56dde18eb47b78ba8c82ada.

All artifacts are under `/tmp/jsh-amphenol-current-validation.fehq8g9f`. The original failed logs and prior final-window HOLD must remain unchanged.

## Timing and readiness

The latest recorded start was about42 minutes before this review. Neither failed log records its precise final-request/completion timestamp, raw HTTP status, or Retry-After deadline. This review did not observe whether other callers have contacted the board. Consequently elapsed time since start is not proof of an expired provider limit, and the saved evidence cannot justify a guaranteed reset time or a new mandatory delay.

The coordinator should record the end of the prior activity and the actual quiet interval from its existing execution evidence, and exclude simultaneous Amphenol validation/retry calls. It can then open one explicitly bounded new window. Do not spend another provider request merely to measure readiness. If a server retry deadline is known independently, respect it. The unchanged adapter already bounds attempts per detail and ends on incomplete results; do not alter its pacing/retry count, bypass access controls, or add an automatic outer retry loop for this check.

Use a fresh output file/window record containing start/end UTC, exit code, evaluator hash, full candidate vector and both predecessor artifact hashes. The evaluator's internal run label is still3; the new outer window identity must disambiguate it from the preserved earlier run3. Reusing this accepted evaluator without editing avoids another source change. Record output even on nonzero exit.

## Required result and changing cohorts

The one scrape must return complete, exactly scoped Company/provider, all advertised pages with consistent totals and unique IDs, identical initial/final membership, one full observed employer-verified JSON-LD description per returned posting, and unchanged candidate source. It then must match the earlier complete cohort728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b and normalized detail digestdfc88fe9ea1383495535d8b1d8715f7e37f5df886f24fa4702dd17688d6cab71. Only final `separate_candidate_confirmation_passed` qualifies this comparison. A run_verified line alone does not.

A changed total, posting set, title, URL or normalized detail may be a legitimate employer update; it is not automatically an adapter defect. The roadmap requires current complete scope, stable identities/full descriptions and exact validated versions, not a permanent count39. Nevertheless the currently accepted confirmation binds those exact earlier observations. A complete changed cohort must therefore hold this comparison. Preserve the new complete run as a candidate new baseline, document the observed change, and prospectively review a separate complete confirmation for that same candidate/current cohort. Do not replace the expected hash after seeing the result, pool35/37 partials, ignore removed jobs, or count an initial/final mismatch as source drift successfully handled. The old window stays failed. A changed Company/source identity instead requires new scope review.

## What passing would and would not authorize

Before spending this check, compare the intended release candidate with the frozen evaluator source vector. If the source actually being proposed changed, evaluating the older tree cannot qualify it; freeze/review the actual version and establish its required repeated complete evidence. The accepted prior one-run comparison can be used only within its unchanged version/evidence contract.

A pass is public candidate evidence, not a release ticket. The existing release owner separately requires a canonical owner-pinned PASS/live_normal_dispatch receipt tied to the exact release manifest and validation digest. That manifest also binds the real operator failed_request_id, current Company/source revision, before/after files, complete source/configuration/dependency versions, with idle admission and post-install verification (`release_qualification.py:39-60`; `integration_release.py:193-225,307-338`). The public evaluator's256-member digest is not a substitute for all those production configuration/dependency identities.

The coordinator then still needs the guarded real release, fresh measured company-only retry, exact live workbook confirmation and independent terminal host QA. The accepted disposable worker/combined-host proof does not supply those observations. Broad processing and unqualified release remain off. Sprint5 requirements are in `sprint_roadmap.md:292-321`; freeze cases and retain failures under `AUTOMATION_ROADMAP.md:85-93`.

No new source design, qualification receipt or native action is proposed by this report. If the new one-shot is partial/blocked again, preserve an external provider hold and stop; continue useful independent work or checkpoint rather than repeating calls indefinitely.
