# GDLS controlled AI integration repair roadmap

Status: ACTIVE — diagnosis complete; staged workflow repair/testing and independent evidence investigation in progress. No runtime deployment yet.

Goal: demonstrate that Jetson produces an integration repair which passes the actual scraper's complete inventory and full-description checks. Coordinator unit tests alone do not satisfy this goal.

## Operating boundaries

- MuleLab owns Python coordination, source retrieval, development files, tests, receipts and reporting.
- Jetson has exactly one inference lane. ChatGPT can use independent engineering/review lanes.
- General Dynamics Land Systems, COMP-0097, is the only pilot company. The remaining queue stays off.
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
| Repair Python evidence packet and bounded stall recovery | IN PROGRESS | Assigned source roles preserved; meaningful evidence prioritized; duplicate reads cannot consume endless calls; one bounded correction then useful stop. |
| Fix bounded status reporting | PENDING | Large task reports remain readable without JSON truncation. |
| Independent regression review | PENDING | Redirect/evidence/packet/stall/status regressions and existing coordinator checks; original acceptance tests preserved. |
| Deploy coordinator paused | PENDING | Reviewed exact bytes, backup, health and paused controls; one Jetson slot. |
| Run explicit GDLS successor | PENDING | History-linked task; real Jetson-produced nonempty repair and tests; no other company starts. |
| Independent live scraper validation | PENDING | Normal dispatch, default transports, employer-scoped complete listing, unique stable IDs/URLs, complete descriptions, pagination and repeated inventory reconciliation. |
| Install verified wrapper and back up | PENDING | Scope-reviewed installation, installed-byte verification, test receipts, GitHub parity and current temp Markdown. |
| Final QA and close goal | PENDING | Independent final PASS; otherwise new failure report and bounded repair cycle. |

## Acceptance cautions

An official landing page proves identity, not inventory coverage. Fixtures prove behavior for supplied inputs, not a current public schema. An explicit empty inventory requires reviewed live empty-state evidence. No status may imply all applicable jobs were downloaded until normal-dispatch live reconciliation succeeds.

Roadmap owner: ChatGPT roadmap lane. Runtime changes and deployment remain with the coordinating engineering lane. This file records evidence-backed progress, not model private reasoning.

## Current engineering checkpoint

The source-only rollout controller adaptation independently passed its scoped review (`ROLLOUT_PATCH_REVIEW.md`). Only removal of legacy migration inputs and conversion of the one-time migration to a read-only no-op changed; the protected deployment engine is byte-identical. Temporary-database checks confirmed two no-op calls preserve logical and raw bytes and reject an incorrect reviewed digest. Full manifest-bound staged acceptance and actual paused deployment are still pending.
