# Forterra next ordered disposition

2026-11-22. Read-only source/report review only. No production store, provider, Sheets, service, Jetson, execution of application commands, or source modification. Root owns the actual GA-ASI hold and the recorded current Company measurements.

**Decision: after GA-ASI has its real owned hold, record Forterra as HELD_NO_CURRENT_QUALIFYING_DEFECT and move to Allen eligibility preparation. Do not manufacture a repair, launch inference, or run a broad scan.** This is an eligibility disposition, not a provider result, repair completion, installed release, or Sprint 6 completion credit.

## Smallest evidence and existing readers

Root's current local measurement says COMP-0066 is eligible/unclaimed, revision 017ff3ba… and resolves to Rippling / https://ats.rippling.com/forterra/jobs, with no saved current qualifying defect. This lane did not re-read the database and does not assert that the provider currently works. Canonical mapping alone cannot prove healthy listings/details; it does establish that the historical query-key defect must not be assumed current.

The installed narrow reader is `company_events.current_company_repair_snapshot(repository, company_id)` (company_events.py:83), followed by `company_sources.repair_source` (company_sources.py:1502). The existing read-only `SQLiteRepository.scrape_outcomes(company_id='COMP-0066', limit=...)` (sqlite_repository.py:1117) can inspect saved outcomes without scheduling. Its result is bounded and oldest-first, so a full absence claim must account for pagination/count or use an exact read-only current-revision selection, not simply the default first 100. None of these APIs writes a named hold.

`./job-search-scraper storage intake-observe` is installed and independently accepted, but sync_cli.py:23-40 only calls CompanyEventBridge.observe_pending. Empty intake is not proof of no qualifying defect and it cannot store the requested Forterra disposition. `record_sealed_source_configuration_outcome` (sqlite_repository.py:940) requires real owned cycle/sealed mapping evidence. Do not use it for a no-fetch eligibility decision.

One concrete source limitation must remain separate: installed source_configuration_manifest.json pins company_sources.py to e8e0163d21328be42f96216c10cae9cfd80aa6a4b848815ece79f83c492680b7, while the physically read registry is 8c7cbbb998be771dd8387b010af34afb32f88071baa71f3f459ad6b436ab7f80. The resolver's comparison at source_configuration_snapshot.py:281-282 therefore refuses a qualified snapshot even if all earlier checks pass. This is stale qualification metadata, not evidence that the canonical Forterra provider configuration is defective. Do not silently refresh it as qualification or promote a historical fixture.

The staged `ordinary_live_issuance_enrollment.snapshot_live_issuance_binding` and `ordinary_verification_finisher` are not installed at the production module paths. The accepted Forterra nine-case composition proves component behavior with a synthetic approved upstream issuer; it did not prove a deployed issuer or real PDW regression. Rebuilding that issuer is unnecessary merely to record a missing-defect hold.

## What can advance

The frozen amendment explicitly says “Keep a missing defect in hold.” Its PDW row requires the regression after any qualified Forterra change; the original matrix likewise makes PDW conditional on a capability/configuration release. With no Forterra change, record PDW as NOT_TRIGGERED_NO_FORTERRA_CHANGE, not passed. Then Allen is the next eligible named case; preserving the Forterra exception does not require another provider call, user input, or a cosmetic Company edit.

Allen's next action is its already identified exact existing-row migration eligibility check/preparation, preserving complete current local row and manual fields. Root has already measured the real stale Greenhouse row; reuse that evidence while valid. The installed Ashby source correction is evidence, not a new wrapper/retry completion. A truthful source correction and existing ordinary-event origin may support a selected clean intake, but the separate frozen model-choice/release/retry criteria still need their own valid evidence. Do not retrospectively count the Sprint 5 Amphenol pilot in this ordered sequence.

A coordinator-owned durable sequence note linking (1) the actual GA-ASI hold receipt, (2) exact Forterra revision/source pins and exhaustive current-defect readback, and (3) the explicit no-defect/PDW-not-triggered disposition is enough to decide the next ordered case. It is not an application receipt. There is no deployed command that atomically records this no-cycle Forterra application hold. If acceptance specifically requires an application-owned receipt, that is a small missing admission/disposition capability, not authority to invent an outcome through generic `record_scrape_outcome` or repurpose the GA-ASI uncertain-employer failure. Keep that gap explicit rather than adding an issuer framework.

Forterra remains an uncompleted completion candidate. The original ACCEPTANCE_MATRIX.md:22 permits changed/inaccessible/unsupported cases to stay explicit exceptions; replacement requires a documented scope change plus independent QA. Moving to the already named Allen case is not replacing Forterra, and does not solve the final three-completion requirement.

## Evidence pins and references

- S6_SEQUENTIAL_MATRIX_AMENDMENT_20261121.md SHA256 8fb7a2eac63432c65c2bf4ed232cd182876ef80d8318b628fb77b219f12f0706; rows 1,2,2a,3 and zero-credit rule.
- Original ACCEPTANCE_MATRIX.md:11,14,22; current scope and conditional regression.
- source_configuration_snapshot.py SHA256 fa85b8df5921d38d79124fbf518fe01fb656fadf0fdb2e40645b3a0fb2ab7ba5.
- source_configuration_manifest.json SHA256 d3a2cac80f3bf5f056bfc94045c298cae0263c563fd5abce849754278152f09e.
- company_events.py SHA256 0c82c1091b413622f0fc4a727225efcd3792598e527d0731e78d3d427b5d265b.
- sync_cli.py SHA256 5af96a0d8abe8496d52824c197e0245207df7ce6e949027f2c392a6bf2d13de2.
- S5_FORTERRA_ORDINARY_COMPOSITION_INDEPENDENT_QA_20261121.md; accepted nine-case component/issuer boundary.
- /tmp/jsh-s6-forterra-allen-handoff.gvgczviv/NEXT_BOUNDED_GATE.md; prior current-evidence preflight and migration limitations, extended rather than replaced here.

Source paths above are under /home/chris/job-search-helper_old/src/job_search_helper/. Coordinator reports are under /tmp/job-search-helper-integration-automation/temp/integration-coordinator/. No display/transport failure occurred; oversized tool output was truncated and relevant source chunks were reread.
