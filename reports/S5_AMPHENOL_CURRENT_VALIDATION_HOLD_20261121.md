# Amphenol current-source public validation evidence

HOLD current two-run qualification. The first complete run is valid positive evidence; the second run is a genuine incomplete provider hold. No current two-run acceptance or release approval is established.

Reviewed artifacts only: `/tmp/jsh-amphenol-current-validation.fehq8g9f`. This review made zero provider calls and changed no candidate, original evidence, production state, service or task.

## Exact observed scope

The eight JSONL records start with normal dispatch for Company COMP-0490, Amphenol Aerospace, AcquireTM, and exact board `https://amphenol-aerospace.acquiretm.com/home.aspx`.

Run 1 records complete initial and final listings: 25 + 14 distinct IDs, advertised total 39 on both pages, no repeated IDs, and identical entries/membership digest `ff45144db9475e3978bd06cf64ec00669f43eaa03da13088849230494e2c6877`. Its dispatch is complete with 39 jobs and 39 observed detail records. The evaluator subsequently emits run_verified for 39 unique IDs/URLs, all employer `amphenol aerospace`, with full-description lengths of at least 3493 characters. Every detail URL matches the exact board, `/job_details_clean.aspx`, and sole ID parameter. The recomputed ID/URL/title cohort digest is `728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b`.

The evaluator source requires each detail's unique JSON-LD JobPosting, matching ID/URL/title, exact accepted employer and full normalized description equality to the normal adapter output before emitting run_verified. Saved logs retain description hashes/lengths rather than raw bodies; this review validated their scope/count and evaluator checks, not independent refetches or reconstruction of raw descriptions.

Run 2 records the same complete initial 39-ID listing, then dispatch returns blocked with 35 jobs/detail observations, one listing pass, and reason `AcquireTM detail request remained rate-limited or unavailable.` There is no second final listing, no second run_verified, and no candidate_live_checks_passed. The final record is RuntimeError `normal dispatch is not complete`. The 35 records must not be used as complete inventory or combined with run 1 to manufacture a successful second run. The adapter maps this blocked reason to its exhausted detail rate-limit branch, but no raw HTTP response/status is retained in this log, so this report does not assert a separately measured HTTP status or retry deadline.

## Source and evaluator evidence

I independently recomputed all 256 frozen source/config members: every `src/**/*.py` plus `pyproject.toml`, `title-blacklist.txt` and `title-review-list.txt`. Manifest digest is exactly `7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea`. This is the evaluator's complete declared vector; it does not include wrapper tooling or tests, and this review did not reread live production to assert present-day equality.

- Candidate adapter: `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`
- Dispatcher: `111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e`
- Evaluator: `ae24c91b884e8ebb5169f6350cd328f749e0f4dc4a3314f3e4234cbd9530d459`
- Original JSONL evidence: `dfd69d46fd48deeeab7feb88d457ba01978d5ef5d4ae4548adc076df5d41638e`
- PREPARED.json: `05e56bd1ea156939881e668c08cdf30dfb9d45ae93afef412721b0dea32cd7ea`

Exact comparison against `/tmp/jsh-m1-scope-backup/tools/sprint5-acquiretm-reviewed-recipe/validation/evaluate_recipe_candidate.py` shows only three restamps: candidate root, source manifest digest, and task label. All normal-dispatch, identity, advertised-total, disjoint-page, full-description, final-listing, unchanged-source and two-run-equality criteria remain unchanged. The evaluator checks the source again after each successful run; the currently recomputed vector also remains exact after the failed second run.

## Next qualified gate

Keep current qualification held and preserve this failed attempt. The two authorized reads have been consumed; do not silently retry or bypass the provider hold. After a separately authorized bounded validation window consistent with the provider's available cooldown guidance, use the same measured source and unchanged criteria, with full details and final reread on each successful run. Do not remove description retrieval, pool partial detail records, or lower the count/completeness criteria. Any pacing-only evaluator amendment must be explicit and reviewed before another observation, not retrospectively used to relabel this result.

The qualification gate remains two complete current-source normal-dispatch observations with stable exact Company/board identity, complete disjoint pagination/full descriptions, unchanged source, and verified final membership; changing live membership requires the existing bounded reconciliation policy. Even after that gate, source release, local storage, exact Sheets publication and terminal host receipt acceptance remain distinct. No installation, storage or synchronization occurred in this evidence run.

Sanitized independently derived result: `/tmp/jsh-amphenol-validation-qa.dKWkleht/RESULT.json`.
