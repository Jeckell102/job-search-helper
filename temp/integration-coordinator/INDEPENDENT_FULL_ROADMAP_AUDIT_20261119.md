# Independent full-roadmap completion audit — 2026-11-19

## Verdict

**INCOMPLETE — do not claim six-milestone completion, F1–F8 closure, or final
independent acceptance.**  This is a fresh read-only audit.  It did not start a
scrape, connect to Google or Jetson, change a lock, open a writable database,
or modify protected source/data.

The decisive remaining gap is live acceptance, not source installation.  The
post-install addendum below supersedes the initial snapshot's stale
not-installed/hash-drift observations: the protected code/tests/coordinator
files now match the reviewed overlay.  That establishes a version-bound
installed source checkpoint; it does not prove a normal automatic workflow,
Google publication, managed FIRST PASS, or the final demonstration.

## Evidence levels used here

| Level | Meaning in this audit |
| --- | --- |
| Source-only | Isolated code/tests passed; no protected target or runtime state was used. |
| Installed | A rollback-backed installer receipt/test record says files were copied to the protected tree at that time. |
| Deployed | A maintained service/host was started with the claimed version. |
| Live | A guarded real workflow action produced current durable operational evidence. |
| Final independent acceptance | All roadmap gates, frozen cases and end-to-end demonstrations are independently verified on the actual deployed version. |

An earlier level never substitutes for a later one.

## Fresh read-only state

* Protected Git `HEAD` is `c9db537` and its working tree is extensively dirty.
* The earlier snapshot at `8b962e4` was superseded by reviewed overlay
  `6ab14d17d5064b706a4795efea43006465c87e8f`.  The user-approved patch
  `18e49304bc02b21c1f0009a2786c160f5816923b255fd95d33efe45c8c552832`
  is recorded as installed, with a reported protected focused matrix of
  127/127.
* Fresh independent file comparison after that installation checked all 516
  overlay-tracked `src/job_search_helper/*.py`, `tests/*.py`, and
  `dev/wrapper-coder/tools/*.py` files against the protected tree:
  `MISMATCH_COUNT=0`.  Older per-file hash lists remain historical evidence,
  but the current protected/overlay identity is re-established.
* No Job Search Helper worker was found by the local process-name check.  The
  persisted scraper/writer/controller locks name absent PIDs `207238`,
  `717646`, and `283795`; they were retained.  This is not permission to remove
  or bypass them.  The sandbox cannot connect to the per-user systemd bus, so
  current host/tunnel service health is **not independently re-proven** here.
* The current normal runner itself says, at `src/job_search_helper/runner.py`
  line 44, that no Sheets watcher runs after the command exits.  Although
  `company_events.py` contains an outbox bridge, this audit found no current
  live receipt proving that an ordinary Company addition automatically starts
  the bounded scrape and managed FIRST PASS path.  Treat automatic
  add-Company-to-FIRST-PASS as unproven, not enabled.
* Read-only SQLite inspection shows 48 cycles: 19 `In Progress`, 28 `Complete
  with exceptions`, and one `Complete`.  `CYC-B639C6D864EC` is still `In
  Progress` and non-superseded, with 45 saved inventories (five blocked) and
  six saved sync plans, all nonzero cursor.  Across the stores there are 3,186
  inventories, 2,410 sync plans, 2,578 blocked inventories and 2,313 nonzero
  cursors.  This is retained work, not a drained/end-to-end completion state.

## Milestone matrix

| Gate | Status | Evidence and what it proves | Smallest remaining acceptance action |
| --- | --- | --- | --- |
| M1 — company-only storage | **INCOMPLETE** | The roadmap requires a real scoped Samtec run, durable storage, repeated-run safety, F6/F7 operational receipts. The protected source is now byte-identical to the reviewed overlay and 127 focused protected checks are reported, but no live one-company storage/sync/lost-ack/timing receipt exists. `FINAL_ACCEPTANCE_READINESS_20261119.md` says broad interrupted cycles remain and a company-only run is unsafe pending exact recovery review. | Perform one owner-authorized, guarded one-company path with local and confirmed sync/lost-ack evidence and idle/busy timing. |
| M2 — durable new-company detection | **INCOMPLETE** | F1 is still OPEN in `QA_FINDINGS_LEDGER.md`; it explicitly lacks external-change reconciliation, bootstrap/watermark catch-up, and guarded idle/busy production proof. Current code identity does not establish the complete live admission path. | Run a guarded add/change while idle and busy, including duplicate/reordered delivery and restart evidence. |
| M3 — failure classification/repair task | **INCOMPLETE** | The roadmap requires realistic classified failures. No current live case/receipt demonstrates classification, deduplication, partial-inventory safety, or the engineering-hold route. | Run controlled failure/temporary/hold cases with durable receipts and independent review. |
| M4 — bounded integration development | **INCOMPLETE** | F4 synthetic interruption is separately bounded (see F4 below), but `FINAL_ACCEPTANCE_READINESS_20261119.md` records an empty automatic repair-profile registry and no qualified automatic repair promotion. F5's named cases lack fresh public preflight. | Freeze and preflight the support matrix; demonstrate one bounded evidence-to-tested-candidate run and an honest unsupported hold, preserving the F4 control boundary. |
| M5 — release and company retry | **INCOMPLETE** | `M5_PRODUCTION_RECONCILIATION_REPORT.md` is an accepted **source-only** reconciliation and expressly lists live release-to-retry/confirmed Sheets/FIRST PASS as remaining. The current protected source now matches the overlay, but no live sequence exists. | Execute one authorized release-to-fresh-company retry through confirmed storage/Sheets/FIRST PASS with restart/rollback evidence. |
| M6 — reliability/sequential activation | **INCOMPLETE** | F8 has historical source/install/service evidence. Current protected code identity is re-established, but the current service bus was inaccessible read-only and no final three-company sequential demo exists. The retained in-progress cycle remains. | Re-establish current service proof (one owner, restart, planned stop, disk hold/retention), then complete the frozen multi-company/restart/pause/rollback demonstration. |
| End-to-end/final acceptance | **MISSING** | `AUTOMATION_ROADMAP.md` requires all six gates, F1–F8 verified closure, three distinct unfinished companies plus shared-adapter regression, actual event-to-storage, and final independent approval. `FINAL_ACCEPTANCE_READINESS_20261119.md` lists empty profiles, unresolved cycles/publisher conflict and frozen-case preflight steps. | Complete each row above on one frozen deployed version; then commission a separate final QA run using actual receipts and current hashes. |

## F1–F8 matrix

| Finding | Status | Exact evidence | Smallest remaining acceptance action |
| --- | --- | --- | --- |
| F1 — Company revisions/event delivery | **INCOMPLETE** | `QA_FINDINGS_LEDGER.md` marks F1 OPEN despite 108 offline checks, specifically requiring external-Sheet reconciliation, bootstrap/catch-up and guarded production proof. | Current-build reconciliation/watermark and idle/busy live admission proof. |
| F2 — retry identity/stale precedence | **INCOMPLETE** | `F2_COMBINED_PROTECTED_INSTALL_20261119.md` records 120 tests and an installed receipt; the post-install comparison now binds current protected source to the reviewed overlay. Its report itself says full lifecycle and real sequence remain open. | Prove one guarded retry lifecycle and stale-result precedence. |
| F3 — start/release atomic admission | **INCOMPLETE** | `F2_F3_PROTECTED_INSTALL_20261119.md` records 65 protected checks and current source identity is re-established, but no current concurrent start/activation/rollback proof is available. | Run the version-bound race proof before a guarded release. |
| F4 — unknown inference reconciliation | **PROVEN (bounded F4 sub-gate)** | `F4_LIVE_PROOF_VERIFICATION.md` records the authenticated synthetic HTTP interruption: `UNCERTAIN` then terminal `FAILED`, no replay, no RUNNING/UNCERTAIN records, with post-run local/Jetson health check. It expressly does **not** complete M1–M6/final acceptance. | Preserve/recheck the validated inference-control service/hash before any dependent live repair; do not count this as general-loop qualification. |
| F5 — support matrix/qualified capability | **INCOMPLETE** | `QA_FINDINGS_LEDGER.md` is only CONTRACT_RECORDED. `FINAL_ACCEPTANCE_READINESS_20261119.md` says the automatic profile registry is empty and named cases need fresh public preflight. | Freshly preflight/freeze named cases and qualify a bounded supported family plus an independent-QA evidence-to-candidate demonstration. |
| F6 — local/save-to-sync receipt | **INCOMPLETE** | Ledger records implementation acceptance and the installed source now matches the reviewed overlay, but it still requires real confirmed synchronization and a lost-ack operational receipt. | Capture one guarded confirmed sync plus no-refetch lost-ack recovery on actual durable records. |
| F7 — scoped scheduling/recovery | **INCOMPLETE** | Ledger records focused offline acceptance and current source identity is re-established, but it requires guarded live idle/busy timing and lock/recovery receipts; 19 unfinished cycles remain. | Record one safe idle/busy request with queue-age/blocker/recovery evidence. |
| F8 — supervision/retention | **INCOMPLETE** | `F8_SUPERVISION_CANDIDATE.md` and `PROTECTED_INTEGRATION_REPORT_20261119.md` document source, installed and historical service proof; current code identity is re-established, but fresh service status could not be read through the sandbox user bus. | Re-run current host/supervision checks, including retention/no-cleanup and graceful-stop evidence. |

## Explicit separation of claims

* **Source-only:** M1–M5 reconciliation reports, retained work/overlay tests,
  and most F2/F3/F6/F7 evidence are valuable but do not activate a workflow.
* **Installed historical evidence:** the protected integration and F2/F3/F8
  installer reports show guarded installations.  The post-install comparison
  now also binds the current protected code/tests/tools to reviewed overlay
  `6ab14d1`; it does not establish a current service run.
* **Live current evidence:** only read-only evidence is current in this audit:
  no matching worker process, retained lock records, and significant unfinished
  saved work.  No final company/release/Sheets proof was attempted or inferred.
* **Final independent acceptance:** **MISSING.**  No report demonstrates all
  frozen cases and all end-to-end acceptance steps on one verified deployed
  version.

## Reproducibility record

This audit used read-only `git status`/hashes for the protected tree and
overlay, process inspection, lock-file reads, and SQLite URI connections with
`mode=ro`.  The authoritative roadmap/ledger inspected were:

* `/home/chris/job-search-helper_old/temp/integration-automation-roadmap-20261118/AUTOMATION_ROADMAP.md`
* `/home/chris/job-search-helper_old/temp/integration-automation-roadmap-20261118/QA_FINDINGS_LEDGER.md`
* `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/COORDINATOR_STATUS.md`
* `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/FINAL_ACCEPTANCE_READINESS_20261119.md`

## Timestamped post-install addendum — 2026-11-19

The user approved and the coordinator applied patch
`18e49304bc02b21c1f0009a2786c160f5816923b255fd95d33efe45c8c552832`.
The updated reviewed overlay is
`6ab14d17d5064b706a4795efea43006465c87e8f`, and its handoff now reads
**APPROVED AND INSTALLED; PROJECT NOT COMPLETE**.  I independently compared
516 tracked source, test, and coordinator Python files to the protected tree
and obtained `MISMATCH_COUNT=0`.  The reported focused protected matrix is
127/127.  Retained modules are therefore installed source, but their
orchestration entry points are referenced only by retained tests; they do not
prove production normal add-Company wiring.

This corrects the earlier stale installation/hash statements only.  It does
not change any live-gate conclusion: no scrape, Google action, managed FIRST
PASS, service restart, lock change, or Jetson action occurred in this install;
the normal automatic add-Company path and all real end-to-end acceptance
evidence remain open.
