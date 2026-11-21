# AcquireTM deadline and release decision

Read-only source decision, 2026-11-21. No provider, native service, application database, or workbook access; no application changes. This report does not qualify a release.

## Decision

Current M3 does **not** schedule from a provider deadline embedded in `Inventory.reason`. A transport patch can stop the current fetch and preserve a readable deadline, but that is not durable deadline-aware scheduling. The present honest bounded behavior is a blocked/manual hold; do not relabel it automatic backoff or turn a provider restriction into repair work.

The accepted fresh Jetson build remains exact evidence for its existing generated adapter. A subsequent host-authored transport change is separate work. The current fresh release reader cannot accept a changed adapter by merely restamping the manifest. Preserve the original task/receipt/build/patch unchanged; separately review the exact transport delta and qualify the actual composed full source tree under a new manifest/release identity. A deliberately reviewed composition seam is required if this combined result is to use the automatic fresh-reader path; neither current source nor this report supplies that seam. The existing fresh path can continue unchanged only with its exact original adapter and a successful later qualification.

## Frozen reason and M3 classification

- `src/job_search_helper/acquiretm.py:196-236`: detail transport currently caps Retry-After sleep at 8 seconds and retries; exhausted 429 produces blocked status and generic reason, with no machine deadline or typed outcome_failure.
- `engine.py:86-94`: inventory_payload includes status, reason, jobs and source information in the existing F6 durable contract. It deliberately excludes M3 outcome_failure.
- `local_pipeline.py:659-664`: durable inbox save precedes a separate typed envelope handoff; a crash between them leaves unknown classification. Do not retrofit deadline fields into old frozen F6 receipts.
- `ats.py:142-164`: closed typed failure envelope; prose does not participate, and no deadline field is admitted.
- `scrape_outcome_producer.py:209-224`: ordinary classification never reads reason and accepts only allowlisted access_denied/temporary_transport envelopes. Missing evidence remains unknown.
- `ordinary_event_settlement.py:212-229`: event outcome similarly derives failure only from the typed envelope; blocked result naming at line 169 is not independent rate-limit proof.
- `outcomes.py:62-84`: access/authentication holds, typed temporary failures become TEMPORARY, and unknown capability remains held. Existing AcquireTM prose alone does not become a qualified code repair or a typed rate-limit retry.

## Present scheduling limit

- `local_pipeline.py:255-263`: blocked/failed/unsupported Company is Blocked / Manual Review, Automatic Retry? No, and explicit retry only.
- `temporary_retry.py:35-59,80-108`: ordinary TEMPORARY delivery permits one company request; the closed request has enqueued_at but no not_before/provider deadline. A repeated TEMPORARY attempt hits the one-retry cap.
- `temporary_retry.py:23,321-323`: selected retry waits exactly 300 seconds after scheduled_at, unrelated to a provider Retry-After.
- `company_intake_dispatcher.py:436-445`: dispatch checks current Company/source and claims, not a provider deadline. Manual/explicit request remains capable of retrying earlier; blocked posture is not an enforced global provider cooldown.

This is an M3 operational limitation. Sprint 5's separate first-429 qualification evaluator and an owner-observed no-contact time protect that evaluation window only; they do not install a scheduler policy or demonstrate restart-safe operational cooldown. A 429 hold is not successful complete coverage.

## Release provenance consequence

- Installed `dev/wrapper-coder/tools/acquiretm_membership_recipe.py:12-13,89-95,142-153` pins canonical a95953af... and deterministically compiles the existing membership recipe.
- Accepted staged `amphenol_candidate_release.py:86-119` reconstructs the exact generated source/patch/build receipt and compares actual retained artifacts and manifest before/after bytes.
- That reader `:122-160` also requires one changed path, acquiretm.py, exact completed task/request/choice, full source/config digest and independent qualification owner. A transport edit in acquiretm.py fails generated-byte equality; adding another changed file fails the current one-path admission. Installing a separate source prerequisite first also changes the before tree and may invalidate the compiler's canonical baseline if acquiretm.py changes.
- Installed `integration_release.py:71-72,234-249` hashes all application Python/JSON and binds files, before/after source, dependencies, configuration and validation into release ID. The existing release ID/qualification cannot be reused for the revised tree.

Minimum evidence for any deliberately composed successor: exact unchanged fresh build receipt and its original generated bytes; separately reviewed bounded transport patch with author attribution; exact old/new full application vectors and new release ID; unchanged complete coverage and fresh-cohort qualification against the actual revised runtime; owner/installer/retry bound to that new manifest. Do not silently credit the transport edit to the Jetson or use evaluator-only monkeypatching as normal transport acceptance. No scheduler expansion is needed merely to retain the honest blocked/manual hold.
