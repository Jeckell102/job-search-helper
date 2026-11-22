# Sprint 7 readiness and evidence checklist

Updated 2026-11-22. Preparation for final acceptance. The index records
scope and version limits from earlier reports, along with the current
intake and public availability observation. Historical findings and
acceptance criteria remain in their original records.

## Coordinator reset and current execution plan

November 22, 11:22 Eastern. Finish the remaining Sprint 6 evidence before
requesting final Sprint 7 sign-off. Start from the existing evidence index
and tag each of the seven demonstrations as carried forward, changed, or
still missing live proof. Match unchanged proofs to the final installed
version. Recheck only a changed boundary, actual failure, or required live
case, and reuse the same live receipt where it proves more than one check.
Ask independent QA to review that evidence once. After acceptance, verify
that the expected controls remain off, document what is supported and held,
and fetch and check the final private backup. A failed check gets one narrow
repair and recheck of the affected boundary. The original gates remain.

The Allen source migration and exact ordinary sync are now independently
accepted. The run retained all 19 full descriptions and delivered five
filtered job rows plus the Allen row. The paired coordinator outcome used
no repair. [Allen independent result](S6_ALLEN_DEPLOYED_ORDINARY_INDEPENDENT_20261122.md).
Amphenol's current listing-only check passed, Forterra remains held, and the
required repair/sequence evidence is still open. The permanent scan-status
fix is staged for the next justified deployment. No repeat probe or
standalone maintenance window is planned for it now.
[Current evidence and holds](S6_CURRENT_ELIGIBILITY_AND_STATUS_FIX_20261122.md).

## Current evidence index

The linked reports preserve the full version pins, receipt identities and
independent verdicts. SHA-256 prefixes identify the indexed reports during
review. The final backup will record full file digests.

| Gate | Proof to carry forward | Evidence and SHA-256 prefix | Final check or limit |
|---|---|---|---|
| M1 / F6 / demo 1 | Bounded deployed Samtec company-only filter, storage, workbook receipt and terminal recovery | [F6_F7_SAMTEC_LIVE_INDEPENDENT_QA_20261120.md](F6_F7_SAMTEC_LIVE_INDEPENDENT_QA_20261120.md) `4d90a8fd54f7` | Carry forward the accepted version. Demo 1 still needs the ordinary Company-addition proof below. |
| M2 / F1 / F7 / demo 1 | Deployed selected Freeform addition and Allen source migration with exact ordinary publication. Allen release REL-d37d7d64a0fd3788e02e699f, cycle CYC-93DE6012E332, 19 complete descriptions, five filtered rows and the Company row. | [S4_FREEFORM_PILOT_FROZEN_EVIDENCE_INDEPENDENT_20261120.md](S4_FREEFORM_PILOT_FROZEN_EVIDENCE_INDEPENDENT_20261120.md) `5be3f22a2983`<br>[S6_ALLEN_DEPLOYED_ORDINARY_INDEPENDENT_20261122.md](S6_ALLEN_DEPLOYED_ORDINARY_INDEPENDENT_20261122.md) `78c2be089275` | Join final-version ordinary start, required timing and restart/duplicate evidence. Allen was a source migration. |
| M3 / demo 4 | Deployed GA-ASI employer-scope hold, actual Amphenol provider backoff and controlled sequence rehearsal | [S6_GAASI_DEPLOYED_INDEPENDENT_20261122.md](S6_GAASI_DEPLOYED_INDEPENDENT_20261122.md) `c57a386db09c`<br>[S5_AMPHENOL_PUBLIC_429_HOLD_20261121.md](S5_AMPHENOL_PUBLIC_429_HOLD_20261121.md) `7227ea6039a9`<br>[S6_SEQUENTIAL_PROVIDER_HOLD_REHEARSAL_20261121.md](S6_SEQUENTIAL_PROVIDER_HOLD_REHEARSAL_20261121.md) `13394070ed34` | Match each evidence type to the exact exception and final progression. GA-ASI exited before provider dispatch. |
| M4–M5 / F2 / F5 / F6 / demos 2–3 | One accepted live Amphenol choice/build/retry chain, release REL-f509ed362bf8781ea8840adc, retry RTRY-8d1210858e4e26f325312a89, 39 saved descriptions and 24 acknowledged records | [S5_AMPHENOL_DEPLOYED_PILOT_ACCEPT_20261122.md](S5_AMPHENOL_DEPLOYED_PILOT_ACCEPT_20261122.md) `f6bab20d2ad4`<br>[S7_CONTROLLED_REPAIR_CHAIN_20261122.md](S7_CONTROLLED_REPAIR_CHAIN_20261122.md) `bf4ca5c1e15f` | Carry the bounded live repair and controlled regression. Join final compatible source and the required unsupported hold. Current repair selection and final sequential completion remain open. |
| F3–F4 / demo 5 | Independent deployed installation and paired interrupted-inference evidence | [F3_DEPLOYED_INDEPENDENT_QA_20261120.md](F3_DEPLOYED_INDEPENDENT_QA_20261120.md) `d2125c982d44`<br>[F4_PAIRED_DEPLOYED_QA_20261120.md](F4_PAIRED_DEPLOYED_QA_20261120.md) `c1fc58293885` | Compare installed source and controls. Repeat only a changed boundary or required missing cut. |
| F8 / demos 5–6 | Reliability baseline plus source-change and pause holds at install and retry admission in a private copy of the installed release | [S6_COORDINATOR_RELIABILITY_BASELINE_20261121.md](S6_COORDINATOR_RELIABILITY_BASELINE_20261121.md) `5382cc08cb72`<br>[S7_QUEUED_COMPANY_SCOPE_RECHECK_20261122.md](S7_QUEUED_COMPANY_SCOPE_RECHECK_20261122.md) `4bae6e7e39e0` | Join final controls and the version-bound evidence. Reuse the exact cuts when their source and execution boundary match. |
| M6 / demo 7 | Current held and clean cases, with a separate first-page Draper availability result | [S6_CURRENT_ELIGIBILITY_AND_STATUS_FIX_20261122.md](S6_CURRENT_ELIGIBILITY_AND_STATUS_FIX_20261122.md) `28da4866c864`<br>[S6_DRAPER_CURRENT_LISTING_AVAILABILITY_20261122.json](S6_DRAPER_CURRENT_LISTING_AVAILABILITY_20261122.json) `d128f3a72ff1`<br>[S6_DRAPER_NEXT_CASE_DECISION_20261122.md](S6_DRAPER_NEXT_CASE_DECISION_20261122.md) `abf56584dc96` | Zero of three named fresh completions. Forterra held, PDW untriggered, Allen clean, no new qualifying Amphenol defect. Draper requires separate qualification and scope review. |

## Prepare now, without waiting for live completion

- [x] Index M1–M6, F1–F8 and all seven demonstrations. Keep original failure reports. Use the current disposition and the direct reports above.
- [ ] Match the accepted pins to the final installed change set. Recheck the affected proof and the explicitly required missing cases.
- [x] Update the current instructions in [the operator runbook](INTEGRATION_AUTOMATION_OPERATOR_RUNBOOK.md). Use the current-window selection rather than an archived observer command.
- [ ] Freeze the final backup allowlist after acceptance. Include approved source, tests, adopted plans, and QA/runbook reports. Keep credentials, stores, locks, raw workbook/job content and private backups local.

## Evidence that still depends on completed Sprint6 / final runtime

| Gate | Smallest decisive final evidence |
|---|---|
| M2 / F1 / F7 ordinary discovery | Actual selected source revision/event -> bridge receipt -> exact request -> scoped run -> terminal local/live publication, plus final-version duplicate/restart evidence. Allen proves the recorded migration, publication and paired delivery. Preserve accepted next-manual-run timing direction; a source migration is not a new-Company addition, and a deliberately retained historical wait is not an idle/busy timing measurement. |
| M3 classification and continued progress | Keep GA's real scope-hold receipt visible while a genuinely later eligible case finishes. Separately link real/controlled tests for explicit zero, temporary backoff/provider denial, unknown capability, storage-only failure and source/pause drift. GA did no provider request, so cannot alone claim those other categories. |
| M4/M5 / F2/F5/F6 | Independent final reconciliation of exact owned failure, model/build result, effective qualified change, installer/fresh-worker measurement, separate retry identity, local/remote confirmation and coordinator terminal identity. The accepted bounded Amphenol chain advances these rows; preserve its recovery limitations. Required unaffected source tests may be reused. Do not mislabel a clean Allen sync or repeated no-op install a qualified repair. |
| M6 named sequence | Three genuinely completed, currently qualified distinct company structures under the frozen sequence, fresh context and cumulative accounting, plus applicable shared-adapter regression. Current holds and the prior Sprint5 pilot give zero replacement credit. Any scope change needs its documented independent review; it cannot erase missing criteria. |
| F3/F4/F8 final combination | Final deployed source/bootstrap/config/dependency projection; one-owner/current controls; unchanged one-inference semantics; targeted changed restart/duplicate/source-drift/pause/rollback/retention joins. Reuse accepted disk-pressure and interruption proofs where unchanged; do not fill disk, kill a live worker, or create a second inference just for volume. |
| Independent deployed final QA | One version-bound final report joining actual source, enabled controls, selected receipts and known limitations. If it fails, preserve a new report, repair the exact issue and rerun affected plus required final gates without relaxing criteria. |
| Verified final backup | After the accepted final source/docs/report are frozen, fetch the exact private remote commit and byte-compare the allowlisted files. Record repository, branch, commit and matched file manifest. |

## Seven demonstrations: current verification disposition

1. Working source added: carry Freeform selected live evidence; ordinary lifecycle additions/restart gaps stay explicit.
2. Qualified broken source -> one repair -> release/retry/storage: carry bounded Amphenol; reconcile final maintained join and separate unsupported hold. No clean-sync substitution.
3. Controlled known regression through same chain: carry the independent controlled replay and the same-byte cure evidence. Verify the applicable final deployed scope and shared-adapter evidence. [S7_CONTROLLED_REPAIR_CHAIN_20261122.md](S7_CONTROLLED_REPAIR_CHAIN_20261122.md).
4. Provider outage/access hold: keep genuine Amphenol429/controlled application evidence; GA adds employer-scope hold only. Later actual progress must be joined.
5. Interrupted coordinator, no duplicate effects: reuse single-inference and receipt proofs; execute only missing/changed final cuts.
6. Changed/paused queued Company cannot install/write: carry the exact-version disposable preinstall and retry holds. Verify source pins and execution boundary at final deployed QA. [S7_QUEUED_COMPANY_SCOPE_RECHECK_20261122.md](S7_QUEUED_COMPANY_SCOPE_RECHECK_20261122.md).
7. Sequential companies/context/accounting: still open; accepted holds, public captures and a single bounded repair are not three fresh completions.

## One easy-to-audit evidence chain per live case

Keep one compact row linking Company ID + source revision -> event/operator request + exact request digest -> cycle/attempt -> installed release/full runtime pin -> inventory/plan digests -> local receipt -> remote acknowledgement/readback fingerprints -> sender/receiver outcome receipt -> independent verdict -> native restoration -> backup commit. For GA, explicitly mark cycle/inventory/publication NOT_APPLICABLE and link its immutable held request archive. For Allen, use the linked terminal independent report and its exact plan and outcome receipt. For Amphenol, link the preserved original/successor plan archives and accepted same-attempt recovery; do not invent a second run.

Final acceptance requires all six original milestone gates, verified F1–F8 closures, seven actual-path demonstrations, deployed independent acceptance, usable operator documentation and fetched scoped backup. Keep broad backlog and unqualified automatic releases disabled until their own gates pass. Current Sprint7 is preparation only; this report adds no completion percentage or release authority.

Sources: AUTOMATION_ROADMAP.md (complete contract and six gates), ACCEPTANCE_MATRIX.md and QA_FINDINGS_LEDGER.md in /home/chris/job-search-helper_old/temp/integration-automation-roadmap-20261118; current COORDINATOR_STATUS.md through November22 10:55, sprint_roadmap.md Sprint7, S7_EFFECTIVE_ACCEPTANCE_20261121.md, INTEGRATION_AUTOMATION_OPERATOR_RUNBOOK.md, S6_GAASI_DEPLOYED_INDEPENDENT_20261122.md, S6_ORDERED_FIRST_HOLD_AND_FORTERRA_ELIGIBILITY_20261122.json as referenced by the card, S6_FORTERRA_ORDERED_ELIGIBILITY_20261122.md and S5_AMPHENOL_DEPLOYED_PILOT_ACCEPT_20261122.md under /tmp/job-search-helper-integration-automation/temp/integration-coordinator/. No display/transport failure occurred.
