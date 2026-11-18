# Controlled AI integration repair roadmap — GDLS and Samtec pilot

Status: TECHNICAL ACCEPTANCE COMPLETE — Samtec passed two fresh live inventory checks, guarded installation and final independent installed QA. Final report GitHub delivery is being prepared; goal closure awaits its delivery receipt. All queue controls OFF and no active work; GDLS remains externally blocked.

Goal: demonstrate that Jetson produces an integration repair which passes the actual scraper's complete inventory and full-description checks. Coordinator unit tests alone do not satisfy this goal.

## Operating boundaries

- MuleLab owns Python coordination, source retrieval, development files, tests, receipts and reporting.
- Jetson has exactly one inference lane. ChatGPT can use independent engineering/review lanes.
- Samtec, COMP-0739, is now the only active pilot company. General Dynamics Land Systems, COMP-0097, remains blocked and paused. The remaining queue stays off.
- Preserve failed task WRAP-8be410e6f4 and its budgets, receipts and unchanged checkout. A retry must be an explicitly linked successor.
- Do not install a generated wrapper until independent code review and actual scraper validation pass. Record all changes and back them up to GitHub.

## Verified starting evidence

The prior pilot stopped in inspect, PAUSED_BLOCKED, after four completed inference calls and 32,025 accounted tokens. It made no edits. Its offline baseline passed 2/2 tests. The subsequent normal-dispatch live check returned PARTIAL, zero jobs, HTTP 308; therefore no complete inventory or stable reread was established.

Python collected nine automatic actions, including the full assigned adapter and original tests. Its source gate accepted company text at https://www.gdls.com/careers/ and did not retrieve the separately mapped GD inventory URL. The model repeatedly requested cached test receipt 166; the final checkpoint recorded three stalled turns. This supports an evidence-selection/instruction problem, not a successfully generated wrapper which later failed.

The saved live response's redirect adds a trailing slash to `/careers/job-search/` while retaining the state query. Current adapter allowlisting accepts only the path without that slash. Actual post-redirect schema and employer scoping still require current investigation; a redirect-only fix is not presumed sufficient.

Reconstructing the final packet from saved receipts confirms an additional concrete failure: the 12,000-character recency budget included tests (1,664 characters), landing (2,200), two mapping excerpts (2,200 each), dispatcher (2,200), and adapter tail (1,536). Adapter head and middle were absent, including source/path-validation and fetch logic. Cached-test focus displaced useful repair context. Evidence packets must prioritize relevant roles and exact failing functions rather than recency alone.

Sources: `/home/chris/job-search-helper_old/temp/pilot-gdls-20261118/PILOT_RESULT.md`; failed task checkpoint, receipts and inference receipts; `live-validation-2/live-validation.json` (first DNS-incomplete harness attempt is not wrapper evidence).

## Sequential gates

| Gate | State | Required evidence |
| --- | --- | --- |
| Diagnose four-call stall | DONE | Saved task receipts and current workflow reviewed; missing mapped inventory evidence identified. |
| Gather current official, mapped listing and detail evidence | IN PROGRESS | Redirect chain, company scope, current inventory schema, representative complete detail and pagination contract. |
| Repair Python evidence packet and bounded stall recovery | DONE | Staged and installed manifest-bound independent acceptance passed; source-role evidence and bounded recovery changes installed. |
| Fix bounded status reporting | DONE | Included in reviewed repaired coordinator release. |
| Independent regression review | DONE | Full suite 309/309 passed in 26.699 seconds; independent staged and installed acceptance PASS. |
| Deploy coordinator paused | DONE | Protected no-migration rollout reached INSTALLED_PAUSED; archive `dev/wrapper-coder/repairs/gdls-workflow-rollout-20261118`. |
| Run explicit GDLS successor | BLOCKED | WRAP-48b4556016 stopped before inference: current official ttcportals inventory returns HTTP 403/Cloudflare in raw and rendered retrieval. Zero AI calls; no completed repair. Predecessor WRAP-8be410e6f4 remains unchanged. |
| Independent live scraper validation | PENDING | Normal dispatch, default transports, employer-scoped complete listing, unique stable IDs/URLs, complete descriptions, pagination and repeated inventory reconciliation. |
| Install verified wrapper and back up | PENDING | Scope-reviewed installation, installed-byte verification, test receipts, GitHub parity and current temp Markdown. |
| Final QA and close goal | PENDING | Independent final PASS; otherwise new failure report and bounded repair cycle. |

## Acceptance cautions

An official landing page proves identity, not inventory coverage. Fixtures prove behavior for supplied inputs, not a current public schema. An explicit empty inventory requires reviewed live empty-state evidence. No status may imply all applicable jobs were downloaded until normal-dispatch live reconciliation succeeds.

Roadmap owner: ChatGPT roadmap lane. Runtime changes and deployment remain with the coordinating engineering lane. This file records evidence-backed progress, not model private reasoning.

## Current engineering checkpoint

The source-only rollout controller adaptation independently passed its scoped review (`ROLLOUT_PATCH_REVIEW.md`). Only removal of legacy migration inputs and conversion of the one-time migration to a read-only no-op changed; the protected deployment engine is byte-identical. Temporary-database checks confirmed two no-op calls preserve logical and raw bytes and reject an incorrect reviewed digest.

The coordinating engineer reports manifest-bound staged and installed independent PASS, with the full 309-test suite passing in 26.699 seconds. The no-migration release is installed via the protected rollout and backed up to GitHub at commit `1a6126c`. The explicit retry task WRAP-48b4556016 was started for COMP-0097 only and subsequently blocked as documented below. Historical WRAP-8be410e6f4 remains unchanged. These engineering milestones do not certify a working company integration: live inventory, descriptions, pagination and stable reread remain mandatory pending gates.

## Latest blocker and bounded alternatives

The subsequent GDLS attempt reached a real source-access blocker at the official ttcportals board; raw and rendered retrieval returned HTTP 403/Cloudflare, before any inference. The engineering lane is improving diagnostic observations in the phase-two stage. A request to use a different untouched company for the acceptance pilot is awaiting the user's answer; no candidate below has been started.

Minimal public reads on MuleLab and read-only current task-state checks identified these candidates:

| Priority | Candidate and current untouched task | Known unfinished work | Fresh public observation |
| --- | --- | --- | --- |
| 1 | Samtec COMP-0739, WRAP-f53051d6c8: PAUSED, zero calls, baseline | Shared Jobvite parser rejects the current listing container; `tests/test_shared_boards.py` exists. | HTTP 200 at `https://jobs.jobvite.com/samtec/jobs`, 26,763 characters, four distinct job links. Smallest apparent repair scope. |
| 2 | Amphenol Aerospace COMP-0490, WRAP-08b337a765: PAUSED, zero calls, baseline | AcquireTM total/pagination repetition; `tests/test_acquiretm.py` exists. | HTTP 200 at its AcquireTM home page, 25 distinct public detail links. Pagination reconciliation makes this a larger test. |
| 3 | MilDef COMP-0429, WRAP-7c0362d6bd: PAUSED, zero calls, baseline | Teamtailor pagination/total disagreement; `tests/test_teamtailor.py` exists. | HTTP 200 at its careers jobs page, 21 distinct job links spanning country domains. Scope complexity is higher. |

These are selection leads, not completed inventory validation. No full scrape, inference, candidate activation or source-code change was performed by the roadmap lane. The coordinating engineer is now starting an explicit Samtec retry from held task WRAP-f53051d6c8; its successor ID will be recorded once reported.

## Controlled Samtec acceptance pilot

The phase-two coordinator has independent installed PASS. Root owns explicit retry/activation of Samtec only, with the ordinary queue off. This is a new proof attempt; prior coordinator test passes and the blocked GDLS task do not count as successful integration acceptance.

Frozen Samtec backlog identifies the exact failure: the current Jobvite listing has real employer-scoped detail links but lacks the literal `jv-job-list` container accepted by the shared parser. Existing `tests/test_shared_boards.py` exercises a Kymeta Jobvite fixture with that old marker, so those original tests alone cannot validate this repair.

Required independent public reconciliation:

1. Use original configured Samtec `/search` inputs through normal scraper dispatch. The existing canonicalization to `/samtec/jobs` is now a known completeness defect: preserve the full search inventory instead of the featured subset.
2. Compare the exact distinct `/samtec/job/<id>` set across the full current search and all pages against returned IDs and URLs. QA observed 148 search jobs; reconcile the current count rather than hard-coding it. The four featured links are not complete inventory.
3. Verify the current complete listing container/feed and whether pagination exists. Any next-page indication must be accounted for; an absent old CSS class must not become unconditional completeness.
4. Retrieve each job's full detail. Check unique JobPosting data, matching title, matching canonical URL or identifier, full description and employer scope. Do not substitute listing snippets.
5. Preserve fail-closed handling of foreign tenants, malformed inventory, duplicate identities, incomplete details and unproved empty states. A marker-free zero is not success.
6. Reconcile final listing membership and a second independent normal-dispatch inventory read. Only then review installation and exact installed bytes, preserve receipts and back up to GitHub.

Pilot state: successor WRAP-0e5e4b6e59 reached implement but made no edits. Root explicitly paused it after five calls and 45,502 accounted tokens, before further budget consumption or false completion. All controls are OFF. The original held task and retry history remain preserved.

Critical new public QA finding: `/samtec/jobs` contains only four featured links, while `/samtec/search` exposes 148 jobs across pages. The prior four-link candidate observation was not complete inventory evidence. Acceptance MUST reconcile the complete search result and all pages, not the featured jobs page. Root paused the attempt before accepting or installing any wrapper.

Evidence-packet diagnosis: relevant guard/resolver excerpts were omitted, and packet text was truncated to 1,500 characters without clearly identifying the visible end. A phase-three workflow lane is repairing source-aware excerpt selection and focus visibility. This is not a wrapper repair or a passing integration test yet. Phase-two backup is pushed at `e5516bf`.

## Phase-three deployment and resumed pilot

The coordinating engineer reports phase-three installed PASS: 317 regression tests plus six independent checks, with exact task database preservation. Backup commit `c0bc6c3` is pushed. The same Samtec task WRAP-0e5e4b6e59 has resumed in the pilot slot; prior history and 45,502 accounted tokens remain intact. The broader queue stays OFF and Jetson remains one inference lane.

A normal-dispatch live baseline at `/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/baseline-1` still returns PARTIAL, zero jobs: current canonicalization selects the featured `/jobs` page and the listing guard fails. This confirms the starting wrapper remains broken; it is not a result for a generated repair. No AI-produced edit or successful live integration has yet been reported at this checkpoint.

## Latest checkpoint: phase-four staging

The earlier resumed task WRAP-0e5e4b6e59 ended at six calls, 53,850 accounted tokens and three stalled turns; its history remains preserved. A fresh phase-three attempt WRAP-756e8b251b reached a better guard diagnosis but stopped PAUSED_BLOCKED in inspect after three calls and 23,355 tokens, with no edits. Plain-text web evidence omitted DOM classes, and the three-turn session checkpoint led the model to select blocked rather than continue with available investigation tools.

Phase four is adding bounded DOM structure evidence, honest qualification when an excerpt lacks a marker, and a continuation checkpoint when useful tools remain. The three-turn session limit, cumulative budgets and existing safety controls remain in force. All controls are OFF while root awaits staged QA. These are coordinator improvements awaiting proof; neither attempt produced a completed wrapper or passed live integration acceptance.

## Current checkpoint: phase-four installed and pilot resumed

Phase-four installation passed 320 tests plus seven independent checks and preserved the exact database. GitHub backup `bc1a490` is pushed. Root resumed the same Samtec task WRAP-756e8b251b with its prior three calls, 23,355 accounted tokens and full history retained. Only the pilot slot is active; ordinary queue and campaign remain OFF, with one Jetson inference lane.

The previous blocked checkpoint remains historical evidence. No generated wrapper or successful live acceptance has yet been reported at this resumed checkpoint. GDLS remains separately blocked by HTTP 403 and has not been resumed.

## Current checkpoint: no-progress pause and bounded model diagnostics

Samtec WRAP-756e8b251b is PAUSED_NO_PROGRESS in inspect: 11 calls, 86,168 accounted tokens, no edits. All controls are OFF. Operator guidance was added with an audit at `/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/operator-guidance-1`; only workflow guidance changed and task budgets/history remained intact. The model continued repeating an incorrect summary.

A separate focused wrapper diagnostic probe consumed 1,751 input and 176 output tokens and produced an incorrect blocked plan; no tools executed. These diagnostic tokens are separate from the task counters and must not be omitted from overall diagnostic reporting or represented as task progress.

The engineer is testing the already available qwen-pro 4B thinking model through the same single-server queue. Its first requested 2,000-output-token diagnostic was rejected by the context check before inference. A 1,000-output-token diagnostic is running at this checkpoint; result pending. No Jetson files changed. The model is a suspected contributing factor, not a proven diagnosis. Installed version four remains backed up at `bc1a490`; no wrapper or live integration acceptance has been achieved.

## Current checkpoint: atomic code-proposal diagnostic

Root resumed one bounded native-Jetson diagnostic for an atomic code proposal. The request exists at `/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/atomic-route-probe-1/request.json`; no response artifact was present when checked by the roadmap lane. Main queue controls remain OFF, and no task budget was reset. This diagnostic has not produced a verified edit, and live integration acceptance remains unmet. Its result and token accounting will be recorded when available.

### Atomic diagnostic result

`atomic-route-probe-1/response.json` now records one proposed `code_edit`, 1,246 input tokens, 381 output tokens and 34.98 seconds. It explicitly records `diagnostic_only: true` and `tools_executed: false`. The proposal is not installed or accepted. Independent roadmap-lane code inspection found it checks `host == "samtec"` even though the host is `jobs.jobvite.com`, incorrectly moves detail-identity assignment into that unreachable tenant condition, and can reference `parts[0]` without the prior empty-parts guard. These concrete defects show this proposal cannot be used as a working repair. Root was notified; live integration acceptance remains unmet.

### Subsequent atomic proposal review

Root reports proposal one failed five of twelve independent checks. Proposal two repaired validation/detail handling but repeated the hostname-versus-tenant bug despite feedback; it consumed 1,732 input and 339 output tokens in 23.77 seconds. Neither proposal was applied. A fresh one-statement third probe is running with the task narrowed to selecting a path based on the tenant slug; no implementation was supplied. Its cost and outcome are pending and will be recorded separately.

Known atomic diagnostic costs so far: proposal one 1,246 input + 381 output = 1,627 tokens; proposal two 1,732 input + 339 output = 2,071 tokens; subtotal 3,698 tokens, excluding the pending third probe and earlier non-atomic diagnostics. These are separate diagnostic calls, not a reset or addition to the paused task counters. The practical current obstacle is demonstrated proposal reliability, not a claim that more budget alone would fix the task.

### Third atomic result and next bounded comparison

Proposal three also failed: it changed the route unconditionally to `/search` for all employers rather than using the requested tenant condition. Cost: 593 input + 162 output = 755 tokens, 11.72 seconds. Source remains untouched. The three atomic calls total 4,453 tokens: 1,627 + 2,071 + 755; this total excludes earlier separate diagnostics and does not alter the paused task accounting.

Current direction is a controlled reasoning-enabled comparison in the same native model mode. The repair lane is inspecting a safe reversible method that retains the serial inference gate and memory limits. No such deployment has yet happened. This is a bounded reliability investigation, not evidence that a wrapper is working.

## Controlled optional reasoning comparison deployed

The latest public diagnostics and independent QA were pushed to GitHub branch `backup/wrapper-pilot-20261118` at commit `c5d6fc5`.

Root reports a reviewed source and deployment-QA change limited to Jetson runtime `wrapper_inference.py`: optional boolean `think`, default false. The same model, 12k context, 3,072 output limit and single inference lane remain unchanged. Runtime backup and deployment receipts are in `/home/chris/job-search-helper_old/temp/pilot-reasoning-mode-20261118`. This new runtime change is pending its own GitHub backup at this checkpoint.

The original atomic request is now running with thinking enabled, with evidence destination `/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/atomic-route-thinking-1`. Its result and accounting are pending. No wrapper code has been edited; queue controls remain OFF. This comparison tests whether optional reasoning improves the same bounded task and does not establish integration acceptance.

## First accepted atomic AI edit — isolated candidate only

The second reasoning-enabled route proposal passed 26/26 independent checks. Root applied its exact generated edit through guarded `code_edit` only in `/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/assisted-candidate-1/repo`. Original task and production source remain unchanged. The candidate passes all 16 existing adapter tests; this is offline evidence, not full live acceptance.

Independent public listing evidence in `public-pagination-evidence-1` verified three search pages with 50 + 50 + 48 = 148 unique job identities. This establishes a current public comparison set, not proof that the candidate scraper downloaded them.

Reasoning comparison one consumed 2,243 tokens and was rejected. Comparison two consumed 2,817 tokens and passed route review. Together with the earlier three non-thinking atomic calls (4,453 tokens), atomic-route diagnostics total 9,513 tokens. These remain separate from original task counters. The reviewed optional reasoning runtime is backed up at confirmed GitHub commit `99f7bc4`.

An AI transport proposal is now running under `atomic-transport-thinking-1`; it has not been applied. Remaining gates include independently reviewed transport and pagination behavior, all live descriptions, exact inventory reconciliation, stable reread and deliberate installation. The goal remains active and incomplete.

## Configuration-first pilot: first model selection accepted

The actual Jetson response in `recipe-selection-1` selected exactly four supported candidates: `full_search`, `job_list`, `next_link`, and `displayed_range`. It completed on the first attempt with stop status, 740 input + 561 output = 1,301 tokens, in 39.27 seconds. The host parsed the selection and saved `work/accepted-recipe-selection.json` with provenance.

A worker is implementing the trusted deterministic recipe. Independent QA has 29 normal-dispatch/HTML checks and a 305-case transport matrix ready; these are prepared checks, not claimed passing results for a compiled candidate. No compiled candidate or live run exists yet at this checkpoint.

All three earlier transport code proposals were rejected, consuming 2,672 + 3,027 + 2,848 = 8,547 tokens separately from the 9,513 atomic-route tokens and 1,301 configuration-selection tokens. The isolated route-only candidate remains unchanged by rejected proposals. These diagnostic categories total 19,361 tokens, excluding earlier non-atomic diagnostics and paused-task budgets.

The accepted model contribution is configuration selection. Python authors the deterministic integration code; human engineering and independent review remain explicit. Full current inventory, descriptions, pagination and stable reread still must pass before installation or any claim of a working integration.

## Recipe live attempt one — failure preserved

The coordinating engineer reports `live-recipe-1` discovered 148 unique listings and received HTTP 200 detail responses, but accepted zero jobs because actual public details are HTML without the JSON-LD expected by the existing extractor. This is a failed integration test, not successful full job download. The QA failure report is saved; the failed receipts must remain available for regression and provenance.

New sequential gates: (1) implement a bounded version-two detail recipe using observed public HTML and exact posting identity; (2) independently replay saved failure bodies and adversarial cases, preserving full-description and identity checks; (3) root obtains and records any required Jetson configuration choice; (4) build an isolated candidate with explicit AI-configuration/Python-code provenance; (5) run fresh normal-dispatch live validation for every current listing/detail and stable reread; (6) independently review before installation and backup.

Version-two implementation and independent QA are underway; root owns Jetson configuration work. The roadmap lane performs no inference or runtime changes. The broader queue remains OFF, and the persistent goal remains incomplete. Successful listing discovery and HTTP 200 responses do not establish accepted full descriptions.

## Version-two candidate accepted for fresh live testing

Jetson selected the correct eight supported version-two configuration IDs in one completed call: 1,052 input + 1,782 output = 2,834 tokens, 126.94 seconds. The saved response hash begins `36bdec7f`. The model supplied configuration; Python supplied the integration implementation.

Author checks passed seven tests and replayed 148 saved full descriptions. The copied candidate source hash begins `2c08149`; an offline sandbox run passed 45/45 tests. Final staged independent QA passed 66 checks (44 independent checks including replay of 148 real descriptions, 16 existing checks and six schema checks). These overlapping suites must not be added together as a unique-test total.

Candidate two was refreshed against the current main three-file baseline before fresh live attempt two, which is running in execution session 54742. The version-two snapshot is committed at `4dd8a15`; push session 91998 was still running at this checkpoint, so remote backup completion is not yet asserted.

Outstanding gates: complete fresh live retrieval and stable inventory reread; independent saved-public-body and identity/full-description audit; review and deliberately install only the verified candidate; verify installed bytes and behavior; finish and remotely verify final GitHub/report backups; reconcile the roadmap and close the persistent goal only after acceptance. No wrapper is installed. Broader queue remains OFF.

## Fresh live attempt two passed; final audit and installation pending

Fresh live attempt two exited successfully with `PASS_LIVE_INTEGRITY_AND_PUBLIC_RECONCILIATION`. Both fresh passes returned 148 jobs, with stable identity/URL sets and all 148 full descriptions matching the public evidence on each pass. Public listing reconciliation covered three pages with 50 + 50 + 48 jobs. This is candidate live acceptance evidence, not yet installed-production verification.

Independent final audit is in progress. GitHub push for snapshot `4dd8a15` is confirmed. The reviewed version-two recipe is saved under the MuleLab temporary `reviewed-recipe-v2` directory. Installation, installed-byte verification and final delivery backup remain pending; final roadmap closure awaits the installation receipt and independent audit result.

The successful mechanism is Jetson-selected configuration plus a reviewed deterministic Python recipe. It does not establish free-form autonomous model coding. Broader queue remains OFF; GDLS remains separately blocked.

## Guarded Samtec installation verified offline

Guarded installation exited successfully with `PASS_INSTALLED_OFFLINE_VERIFICATION`. Receipt: `/home/chris/job-search-helper_old/temp/pilot-samtec-20261118/install-20261118T230452Z-e8a2c9bb/receipt.json`. The receipt binds candidate SHA256 `2c08149e746b98f970d6ed98f2944dde3c51db0e3cb4b2f69c728b7a3c706847`, records installation true and rollback false, and records all four test commands exiting zero. Installed offline checks total 60.

The exact candidate snapshot previously passed fresh live reconciliation with 148 jobs and matching full descriptions on both passes. Installation is not represented as a separate third live scrape. Independent final installed audit is running; root is preparing final GitHub backup. Queue remains OFF and GDLS remains externally HTTP-403 blocked. No claim is made that arbitrary integrations can now be autonomously coded.

## Final independent installed QA PASS

Final independent installed QA reports PASS in the version-two `FINAL_INSTALLED_QA` artifacts: all 185 installed source hashes match the live-tested snapshot, all 60 installed tests passed, rollback backup is proved, all scheduling controls are OFF and there is no active work. The successful live snapshot contains 148 jobs on both fresh passes with stable identities/URLs and all full descriptions reconciled against public evidence.

Technical acceptance for this bounded Samtec pilot is complete. Root is preparing the final GitHub report commit; earlier candidate snapshot `4dd8a15` was already confirmed pushed. The final delivery receipt will record the new commit after remote verification. No additional technical repair or live test is pending unless delivery reveals a mismatch.

Final scope: Jetson selected evidence-backed configuration; reviewed Python recipes generated the integration code on MuleLab. The accepted integration is installed for the scraper. General scheduling remains OFF, and GDLS remains explicitly blocked by public HTTP 403. This result does not certify autonomous free-form coding or every remaining integration.


Final delivery: installed source, successful live evidence and final independent QA were pushed to GitHub commit `a072b85` on `backup/wrapper-pilot-20261118`. Samtec bounded pilot is complete; broader queue remains OFF and GDLS remains blocked.
