# Independent bounded candidate capture review

Verdict: **ACCEPT_BOUNDED_CANDIDATE_CAPTURE**. This accepts the observed Amphenol Aerospace candidate public-read evaluation only. It does **not** authorize deployment, production writes, synchronization, broad backlog processing, or automatic release.

The release owner executed the previously frozen evaluator once, making two sequential fresh normal-dispatch scans. This reviewer made no additional employer/model calls and independently inspected the resulting capture and current source pins.

## Exact evidence

- Candidate root: `/tmp/jsh-s5-amphenol-recipe-live-candidate`.
- Capture: `/tmp/jsh-s5-amphenol-candidate-live.hrygHxP7/evidence.jsonl`, SHA-256 `4a112649009f43322722be73cee16b52a53224d96b8142b65f7d8c0d53f2bc85`.
- Evaluator: `/tmp/jsh-amphenol-independent-qa-20261121/evaluate_recipe_candidate.py`, unchanged SHA-256 `692cf7db590f53524bfa1fc08d298c7f1bb842b682596eef799a851e85ed42ad`.
- Adapter: `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`.
- Dispatcher: `111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e`.
- Full 243-file source/config manifest: `48f80b004f69fe4015f711e7f235176ffb69742162010091e017d21143dd1cae`, matching initial, terminal, and independent current recomputation.
- Started `2026-11-21T05:57:21.429751+00:00`; passed `2026-11-21T05:59:48.694761+00:00`.

## Independently checked result

The capture contains exactly the expected event sequence: start; first initial/final inventories; first complete return and verification; second initial/final inventories; second complete return and verification; terminal passed event. Both normal dispatcher results are `complete`, use exact source `https://amphenol-aerospace.acquiretm.com/home.aspx`, ATS `AcquireTM`, company `COMP-0490` / `Amphenol Aerospace`, and contain 39 jobs with 39 observed detail responses.

Every one of the four listing inventories has advertised total 39, a 25-ID first page, and a disjoint 14-ID second page. Their union equals the returned 39-ID listing exactly. All four complete entry mappings are identical. Recomputed listing digest: `ff45144db9475e3978bd06cf64ec00669f43eaa03da13088849230494e2c6877`.

Every captured detail has the same exact ID and URL as the complete listing, exact HTTPS employer hostname and `/job_details_clean.aspx?ID=...` shape, and employer label `amphenol aerospace`. All 39 description lengths are between 3,493 and 6,386 normalized characters. Every description's length and SHA-256 is identical between the two runs. The independently recomputed ID/URL/title cohort digest is `728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b` in both runs.

The evaluator inspects each actual JSON-LD response before posting extraction, then requires the returned description to equal the entire normalized JSON-LD description, with exact detail identity and scoped employer. The capture stores lengths/hashes rather than raw description bodies. Thus this review verifies the frozen executable equality check and its successful execution evidence, not an independent prose reading of every raw description. No body truncation or changed description is evidenced.

The evaluator only wraps existing parser/inventory/detail functions to observe them; it invokes the actual `ats.fetch_inventory` route with fixed scoped inputs. It pins the complete source manifest before imports and checks source stability after each run. The adapter performs its ordinary full detail retrieval and final listing reread. No database, receipt publication, sync, release, old-cycle mutation, or queue API appears in the evaluator; terminal evidence explicitly records `installation=not_performed`, `storage_sync=not_performed`, and `backup=not_verified`.

## Remaining gates

Any guarded installation requires the release owner's separate exact diff, rollback, affected tests, source pin, and deployed-system acceptance gates. This private candidate result is neither deployed-system QA nor acceptance of general free-form wrapper generation. The frozen recipe source and actual JavaScript readiness proof remain separate evidence in `RECIPE_SOURCE_ACCEPT_20261121.md` and `check_recipe_offline.py`.
