# Second single-company integration pilot

Updated: 2026-11-18

## Goal

Prove a second unfinished integration through the persistent MuleLab coordinator and the Jetson's single inference lane. Require focused offline tests, normal `fetch_inventory()` dispatch, complete employer-scoped live inventory, full descriptions, stable unique identifiers and URLs, and a stable reread. Keep every other imported assignment held.

## Pilot

- Company: COMP-0348 VideoRay
- Task: WRAP-5bbb2a9156
- Configured source: https://videoray.com/about-us/careers/
- Repaired source: https://avav.wd1.myworkdayjobs.com/en-US/AVAV?q=VideoRay
- Adapter: VideoRay local careers plus explicitly attributed AVAV Workday roles

## Selection reason

VideoRay has a bounded company-specific adapter and a normal-dispatch test. Its unresolved evidence was live access to the AVAV parent board, explicit VideoRay employer/legal-entity attribution, and deduplication between the local page and Workday. This exercises more of the coordinator than another single-feed transport allowlist.

## Acceptance contract

1. The isolated baseline and all focused VideoRay and shared Workday tests pass or produce a bounded repair target.
2. The Jetson uses one inference lane for evidence-guided inspection and planning.
3. MuleLab retains repository reads, guarded edits, tests, receipts, live validation, and durable task state.
4. Normal `fetch_inventory()` dispatch routes COMP-0348 to the VideoRay adapter.
5. Both local and attributed Workday sources are reconciled; any unscoped parent role fails closed.
6. Every returned job has a stable unique ID and URL plus a full description.
7. A second full read returns stable membership.
8. No other backlog company is activated.

## Progress

- Persistent goal created.
- Global queue confirmed paused.
- Activated only WRAP-5bbb2a9156; 103 other paused imports remain held.
- Historical blocker: the direct cycle could not prove the repaired source and parent-board inventory; browser fallback saved no descriptions.
- First activation stopped safely at `PAUSED_FILES_CHANGED` before baseline, model inference, or edits. The isolated files themselves matched the frozen queue base.
- Root cause: first activation of an imported task fingerprinted the shared compatibility checkout before creating the task's isolated checkout. The worker then correctly detected that the two manifests differed.
- Repaired first activation to create and fingerprint the isolated task checkout directly. Added a regression test proving `pilot-start` creates that checkout and stores its exact manifest. The targeted coordinator and workflow suite passes 44 tests.
- Isolated baseline passed all requested VideoRay and shared Workday tests. MuleLab collected 24 source, test, protocol, and public-page requirements before the first Jetson call.
- The Jetson confirmed the repaired VideoRay mapping, local-plus-AVAV adapter route, and passing baseline. It made no unsupported edit and paused after three no-progress checkpoints.
- Operator live normal-dispatch validation then reproduced the unresolved production failure: status `unsupported`, zero jobs, reason `Only pinned official HTTPS API endpoints are allowed.`
- Root cause: normal dispatch supplies `HTTPTransport` for the AVAV Workday API but leaves the optional HTML transport empty. `fetch_videoray()` currently falls back to that API-only transport for `https://videoray.com/about-us/careers/`, so the local page is rejected before the parent board can be reconciled.
- Required repair is bounded to `src/job_search_helper/videoray.py` and `tests/test_videoray.py`: default the local side to `CareersTransport` while retaining `HTTPTransport` for Workday, then add a normal-dispatch regression test with distinct fake transports.
- The Jetson accepted one guarded edit but imported `CareersTransport` from the wrong module and did not change the fallback. The no-progress and pause gates prevented the mistake from reaching verification. Receipt 139 preserves this attempt.
- MuleLab corrected the design at normal dispatch: direct adapter callers retain their injectable combined transport, while default `fetch_inventory()` creates a `CareersTransport` for local HTML and an `HTTPTransport` for AVAV Workday. The new regression test proves the two transports remain separate.
- Post-edit tests initially exposed the adapter-level fallback mistake with three failures. After moving the split to dispatch, the five-file focused suite passed twice.
- First repaired live run reached both sources but remained partial because AVAV omits employer/legal-entity metadata. Live inspection found three complete parent roles whose descriptions explicitly say `VideoRay Segment` or `UXS / VideoRay products`.
- Added a narrow description-attribution fallback for only `videoray segment` or `videoray products`. The existing negative fixture with an incidental `Design VideoRay electronics` mention remains rejected.
- Final focused suite passed 71 tests in the installed main checkout.
- Successful live runs returned the same four-job cohort: three AVAV Workday roles and one local VideoRay role. IDs and URLs are unique and stable; full descriptions are 7,065, 7,251, 7,422, and 4,776 characters.
- One intentionally rapid immediate reread hit Workday human verification and failed closed with only the local role. After a short cooldown the pinned API returned JSON again, and the full reread matched exactly. The installed main checkout also returned the same complete cohort.
- Rollback copies were saved under `dev/wrapper-coder/repairs/videoray-main-20261118/` before the narrow main merge.
- Durable live-validation receipt: 164. WRAP-5bbb2a9156 now reports `LIVE_VALIDATED`.
- The pilot slot is clear and the global queue remains paused. Queue summary: two validated pilots and 103 paused imported assignments.

## Current next action

Pilot acceptance contract satisfied. Preserve the coordinator first-activation fix, VideoRay patch, receipts, and this log in GitHub. Do not release another company without explicit authorization.
