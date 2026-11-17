# Partial-company integration handoff — 17 November 2026

## Read this first

The best first repair is the shared Rippling listing parser: **13 partial companies** report the same exception, and the exact exception was reproduced against current public Forterra and DroneUp page data. Next address historical fixed job-count checks and HTML/API transport mismatches. These are concrete implementation problems, although clearing the first error does not establish complete inventory coverage.

This is an audit and implementation plan. No fixes described here were installed by this audit, no company was marked complete, no Sheet values were changed, and no scraper was started or stopped. The earlier Bosch Rexroth wrapper is an exception: it was already installed before this audit and needs run-level verification, not a duplicate implementation.

**Scope:** all 334 companies whose final cycle stage is `partial`. These are company inventory outcomes, not 334 individual job records. The separate blocked, failed, and unsupported companies are outside this list. Every partial has a record below containing its exact failure, source, disposition, and next step. Detailed code analysis and live probes are distinguished from initial triage; this document does not claim 334 complete live integration tests.

Runtime: `/home/chris/job-search-helper_old`. All code paths below are relative to that runtime unless stated otherwise. Requested handoff directory: `/home/chris/job-search-helper_old/temp/partial-integration-audit-20261117/`.

## Snapshot and evidence

The read-only local database snapshot at **2026-11-17 15:35:10 UTC / 10:35:10 EST** captured cycle `CYC-DE2DC903A35A`, started at 13:13:55 UTC and finished at 15:25:01 UTC. Its status is `Complete with exceptions`.

| Stage | Companies |
|---|---:|
| Complete | 402 |
| Partial — this audit | 334 |
| Blocked | 35 |
| Unsupported | 20 |
| Failed | 5 |
| Total | 796 |

The final cycle has no queued/fetching stage. This is **not evidence that Google Sheets publication has drained**; outbox delivery is a separate question and was not audited here. The displayed complete counter stays at 402 because a finished attempt can end partial. The generic browser fallback preserves found descriptions but explicitly does not establish a full inventory; neither zero pending URLs nor a successful detail pass is enough to promote its coverage to complete. See `README-AUTOMATED.md` and `docs/shared-ats-integrations.md`.

Evidence files alongside this report:

- `snapshot.json`: all 334 exact cycle reasons, company/source metadata, previous-cycle status, pending URL counts, and runtime Python source hashes. Company configuration is the local Companies cache, not a new live Sheet read. `last_inventory_count` may be historical and is not the current cycle's successful fetch count.
- `public-source-probes.json`: 173 distinct public source GET checks, including all 162 C1/C2/C3 records (shared exact URLs were deduplicated) and targeted adapter investigations. Records carry UTC timestamps, status, final URL, redirect chain, SHA-256 of the response, extracted candidate links, and relevant schema evidence. No full downloaded job bodies are included. These are bounded page checks, not full-board validations.
- `candidate-endpoint-probes.json`: five follow-up requests to candidate native endpoints. A successful response proves reachability/schema only; it does not prove all pages and full descriptions.
- `code-findings.json`: exact code lines/hashes, offline source-repair outputs, and reproductions for Caterpillar and Garrett Motion.
- `triage.json`: machine-readable per-company assignments and next actions, generated from the snapshot and reviewed overrides.
- `bosch-validation-summary.json`: compact receipt of the earlier same-day Rexroth validation, copied from the existing workspace artifact. It is not a fresh validation performed by this audit.
- `capture_snapshot.py`, `probe_sources.py`, `probe_candidates.py`, `capture_code_findings.py`, `build_handoff.py`, and `handoff-notes.md`: reproducible audit inputs. Re-run into a new dated directory to preserve this evidence.

The reason groups below are an **initial heuristic** based on the first direct-fetch failure, before browser fallback text. They are mutually exclusive for counting, but technical causes overlap. They are not estimates of guaranteed integrations. For example, Ansys TLS failure falls in A3 under this simple classifier, and Leidos's B1 record also reports a 2,000-result ceiling. Use each exact reason and the reviewed disposition, not just the group name.

<!-- CATEGORY_TABLE -->

## First implementation work orders

### W01 — Repair the shared Rippling query-key schema (first priority)

Companies: Forterra COMP-0066; goTenna COMP-0110; Performance Drone Works COMP-0178; DroneUp COMP-0188; Bonsai Robotics COMP-0237; Advanced Navigation COMP-0260; ADLINK COMP-0288; Foundation COMP-0320; Blue Robotics COMP-0349; Kraken Robotics COMP-0350; Cyngn COMP-0483; Overland AI COMP-0495; Mytra COMP-0539.

**Confirmed:** `src/job_search_helper/shared_boards.py:414-415` selects `queryKey[-1]`, then calls `.get`. Current Forterra and DroneUp state is shaped like `["board", slug, "job-posts", true, {searchQuery, departments, workplaceType, country, state, city, page, pageSize}, "en-US"]`. The last item is a string. Both replays raise `AttributeError: 'str' object has no attribute 'get'` at line 415. See probe keys `rippling-forterra` and `rippling-droneup`, including traceback and actual query keys.

**Implement:** recognize explicitly validated old/new query-key layouts; identify the unique filter object with the required pagination/scope fields; validate board identity, locale and optional flag semantics. Reject ambiguous or malformed layouts as partial with a useful diagnostic. Keep total/page/pageSize checks, distinct-ID and duplicate-location handling, detail validation, and final membership reconciliation. Do not blindly choose any dictionary or suppress the exception.

**Tests/validation:** extend `tests/test_shared_boards.py`, `tests/test_shared_board_helpers.py`, and Rippling fixtures with a trailing locale, old key shape, missing/ambiguous filter object, actual filters, wrong board, duplicate locations, and multi-page inventory. The two live checks reproduced only page-one failure; run full normal-dispatch validation for those two boards, then one >20-job board and all 13 affected companies. An existing primary error can mask a later description failure.

### W02 — Replace historical fixed inventory sizes with completeness evidence

These count requirements are in production code, not just fixtures:

| Company | Code | Historical requirement | Current evidence |
|---|---|---|---|
| Black River COMP-0166 | `black_river.py:67` | exactly 14 links | cycle found 15; public page HTTP 200 |
| Freefly COMP-0171 | `freefly.py:54` | exactly 15 postings | cycle found 14; public page HTTP 200 |
| Aitech COMP-0428 | `aitech.py:49` | exactly 17 links | cycle found 15; public page HTTP 200 |
| JR Automation COMP-0250 | `jr_automation.py:158` | total exactly 64 | cycle rejects inventory size; filtered page HTTP 200; current total not extracted in this audit |
| KUKA COMP-0246 | `kuka.py:32` | exactly 115 feed items | cycle rejects count or foreign scope; current feed not independently fetched here |
| Hughes COMP-0118 | `hughes.py:24` | exactly 14 jobs / 2 pages | live public API HTTP 200, `totalCount=6`, six rows |
| ASTi COMP-0336 | `asti.py:48` | exactly 2 roles | latent count restriction behind current transport error; current role count not verified |

**Implement:** replace stale historical numbers with validated live totals, complete listing containers or an explicitly documented unpaginated feed, complete traversal, unique stable IDs, full detail coverage, and a final reread. Keep job-family/legal-entity scope guards independent of count. Use bounded reconciliation for listings that genuinely change during a scan. Changing 14 to 15 merely moves the defect to the next job opening. Simply deleting a count check without replacement completeness evidence is also insufficient.

For Hughes, make page count dynamic and validate every page/total/reread; do not still fetch page 2 unconditionally after allowing total 6. For JR, preserve the exact JR Automation brand filter and all-page reconciliation. For KUKA, retain `KUKA_FACET` validation; the recorded combined error does not prove count alone is the current cause. For ASTi, review title-derived posting IDs and duplicate title handling before broadening beyond two roles.

**Tests:** inventories both above and below the old size, explicit empty state, missing listing marker, duplicate/missing IDs, changed final membership, wrong employer, missing description, truncated page, and pagination across more than the old number of pages. Search existing tests by function name; several adapters have no same-named test file, so do not invent a path or assume coverage exists.

### W03 — Fix normal dispatch using the wrong transport

| Company | Confirmed code path | Repair |
|---|---|---|
| ASTi COMP-0336 | `ats.py:1023` supplies `discovery_transport or transport or HTTPTransport()` to a static HTML adapter; its own `CareersTransport()` default is bypassed | Use the validated HTML transport when no caller-supplied HTML transport exists; retain fixture injection |
| Mass Virtual COMP-0344 | same pattern at `ats.py:1037`; feed is rejected by `_safe_api_url` | Narrowly support its official Paylocity feed or use the adapter's validated public transport, then validate employer and full descriptions |
| Hughes COMP-0118 | `ats.py:1005` / `hughes.py` uses `HTTPTransport`; `jobs.echostar.com/api/jobs?tags4=Hughes&page=1` is not allowed | Add an exact scoped endpoint contract with query/page validation, plus W02 |
| VideoRay COMP-0348 | `videoray.py:147` falls back from missing HTML transport to the Workday API transport, then requests `videoray.com/about-us/careers/` | Keep separate HTML and Workday clients; preserve explicit VideoRay attribution and overlap handling |

**Live evidence:** ASTi page, Mass Virtual feed, and Hughes API all returned HTTP 200 to a bounded public GET. The production API URL guard independently rejected all three URLs with the exact recorded message. Mass Virtual feed currently has one job row; row completeness and end-to-end success remain unverified. VideoRay's code mismatch was inspected; its parent Workday and local full inventory were not freshly verified.

**Tests:** use the actual top-level `fetch_inventory` dispatch with mocked network boundaries and default client selection, not only adapter calls with permissive fake clients. Existing `tests/test_asti.py` and `tests/test_massvirtual.py` inject a fake directly and therefore miss this wiring failure. Retain tests for denied/unknown host, unsafe redirects, unsupported query changes, foreign employer, missing descriptions and unproven emptiness. Do not solve this by allowing arbitrary HTTPS API destinations.

### W04 — Reach the existing Lockheed integration

COMP-0074 current cached URL is `https://www.lockheedmartin.com/en-us/careers/`. The fresh official page links `https://lockheedmartin.eightfold.ai/careers`. `lockheed.py` already implements a scoped Eightfold inventory; `browser_scraper.py:635-638` dispatches to it only for the exact Eightfold URL. Offline `repair_source` with the current cached inputs returns the original Browser URL unchanged. The `company_sources.py` COMP-0074 repair entry does not recognize this current nonempty landing URL.

**Implement:** add the exact verified landing URL to accepted source aliases, preserving company ID/name checks; follow normal repair→browser dispatch through to the existing adapter. Validate existing Eightfold listing/detail/pagination and final reconciliation. Do not create another Lockheed scraper. Treat official page→tenant linkage as verified; complete current tenant operation is still untested here. Use `tests/test_eightfold_scan.py` and locate existing Lockheed tests by `fetch_lockheed` before adding dispatch regression coverage.

### W05 — Canonical redirect repairs with scope preserved

- **IERUS COMP-0449:** `https://hire.jobscore.com/jobs/ierustechnologiesinc/feed.atom` returns 301 to `https://careers.jobscore.com/jobs/ierustechnologiesinc/feed.atom`, which returns 200. `ierus.py` pins both source identity and detail host to the old host. Update the exact trusted canonical source, record/detail host guards and source aliases together; parse/reconcile the Atom feed and check whether it is truncated or paginated before calling it complete.
- **Scythe Robotics COMP-0506:** `https://app.dover.com/jobs/scytherobotics` redirects 301 to `https://jobs.dover.com/scytherobotics?src=app`, HTTP 200. `scythe_robotics.py` pins the old host/path. Inspect the new public page's actual inventory/empty-state contract; a 200 JS shell is not complete. Preserve tenant and stable posting identity.
- **GD Land Systems COMP-0097:** two HTTP 308 redirects lead from `/careers/job-search` to `/careers/search/`, preserving the encoded `state` query. Current endpoint HTTP 200. Inspect new Next.js search surface, re-prove the business-unit filter and all pages; don't assume a redirect alone fixes the old HTML parser. Use `gd_land_systems.py` and preserve checkpoint source compatibility deliberately.
- **MachineMetrics COMP-0278:** trailing-slash redirect resolves, and the official page embeds Greenhouse `machinemetrics`, but its public jobs API currently returns **404**. This is not a ready source substitution. Locate the current official inventory or explicitly preserve the unresolved state.

Do not blanket-enable redirects in every transport. Validate the exact official target and path/query semantics, with bounded redirect tests and foreign-host rejection.

### W06 — Native-board routes found on current official pages

These offer promising reuse of existing provider adapters. Links are official-page evidence; full inventory acceptance remains required.

| Company | Verified linkage / follow-up | Next implementation step |
|---|---|---|
| Serve Robotics COMP-0542 | official careers embeds `jobs.ashbyhq.com/serverobotics/embed?version=2`; public posting API HTTP 200 with **23 rows** | Add exact company/source repair to the Ashby route; validate full descriptions, IDs, visibility and reread through normal dispatch |
| Ubiquiti COMP-0749 | `careers.ui.com` links Greenhouse tenant `ubiquiti`; public jobs API HTTP 200 with **168 rows** | Reuse Greenhouse; verify counts/content, official tenant identity and all required details |
| RightHand Robotics COMP-0710 | official site embeds `righthand-robotics.breezy.hr`; `/json` returns HTTP 200 list | Reuse Breezy; detail coverage and final list reread remain necessary |
| Aerotech COMP-0789 | official careers page links `aerotech.applytojob.com/apply/`, HTTP 200 | Reuse JazzHR, validate complete listing marker/pagination/details |
| Zebra COMP-0538 | official page links `zebra.wd501.myworkdayjobs.com/Zebra_careers` | Reuse Workday; retain actual intended scope; do not copy login or job-family links as a full board |
| Booz Allen COMP-0623 | official redirect to `www.boozallen.com/careers.html` links `bah.wd1.myworkdayjobs.com/BAH_Jobs` | Exact source repair and normal Workday verification |
| CrowdStrike COMP-0663 | official page links `crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers` | Reuse Workday; choose validated full scope, not highlighted family filters |
| Bentley COMP-0667 | official page links `bentleysystems.wd5.myworkdayjobs.com/bentley` | Reuse Workday; avoid example `q=AI`/`q=ProjectWise` searches |
| Fortinet COMP-0660 | official page links `edel.fa.us2.oraclecloud.com/.../sites/CX_2001` | Reuse Oracle site resolver, validate tenant/site and all requisitions |
| onsemi COMP-0731 | official page links `hctz.fa.us2.oraclecloud.com/.../sites/CX_1001` | Reuse Oracle with explicit site and complete inventory validation |
| Texas Instruments COMP-0727 | official `careers.ti.com` serves Oracle page/resources for `edbz.fa.us2.oraclecloud.com`, site CX | Verify custom-host canonical mapping before adding it; asset hosts alone are insufficient scope proof |
| Garrett Motion COMP-0638 | official page links `ehth.fa.em2.oraclecloud.com/.../sites/CX_2001` | Existing `is_oracle_host` rejects **em2** (offline reproduction false); add narrowly validated regional host support and audit every Oracle resolver/transport host guard |
| Power Integrations COMP-0791 | official page embeds `jobs.jobvite.com/power-integrations/?nl=1&fr=true` | Canonicalize known embedding parameters to a validated full board; reuse Jobvite, coordinate with Samtec parser work |
| SMC COMP-0568 | official custom page references Dayforce tenant `smcnorthamerica/CANDIDATEPORTAL`; link observed is a privacy page, plus a custom same-site search API link | Verify actual official job-board route and public listing contract first; do not mistake privacy linkage for complete board evidence |

SuccessFactors-backed candidates with current provider markers include Festo COMP-0560, Danfoss COMP-0570, ATS Corp COMP-0573, Crown COMP-0588, Tennant COMP-0594, Krones COMP-0604, Teradyne COMP-0620, CommScope COMP-0658, Supermicro COMP-0740, congatec COMP-0742, and Endress+Hauser COMP-0765. Reuse `successfactors.py` / Jobs2Web where the actual canonical listing fits; inspect the correct employer, locale, subsidiary and country scopes. Asset markers alone do not establish a valid adapter route.

Phenom markers on Zimmer Biomet COMP-0554, Trane COMP-0564, Oshkosh/JLG COMP-0621/0622, Arrow COMP-0779, Thermo Fisher COMP-0780 and Danaher COMP-0781 justify examining `phenom.py`. Several URLs are job categories or regional filters: preserve that configured intent until a verified scope change is authorized. Do not silently replace JLG or Danaher with an entire parent-company inventory.

### W07 — Caterpillar requires a correctness repair, not just a URL change

COMP-0238 is configured at `https://www.caterpillar.com/en/careers.html`, while `caterpillar.py:70-74` accepts only `careers.caterpillar.com`. The source mismatch is confirmed. The fresh official page includes a Caterpillar Workday login link, which is a candidate for further official route discovery, not proof of full board scope.

**Additional confirmed offline defect:** `_parse_xml` examines a node's child tag names, then searches recursively for the first job's fields. For synthetic `<jobs><job id=one>…</job><job id=two>…</job></jobs>` it emits **one** record. See exact XML and output in `code-findings.json`. Existing `tests/test_caterpillar.py` uses duplicate IDs and therefore does not reveal loss of a second distinct job.

The HTML fallback can emit empty descriptions, and `fetch_caterpillar` currently returns complete for any nonempty parsed list without independently proving total, all pages, US country scope or final membership. Keep this route fail-closed while fixing it. Prefer a current official native inventory if verified; otherwise correct record iteration, explicit scope, description retrieval, pagination and final reconciliation. Add two-distinct-record, missing-description, non-US, truncated/paginated and changing-listing tests before allowing complete.

### W08 — Other existing provider repairs worth a targeted pass

- **Samtec COMP-0739:** Jobvite source returned 200 and real `/samtec/job/...` links. `shared_boards.py:536-538` requires literal `jv-job-list`. Capture new complete-list markup or public feed and update structural validation, preserving explicit-empty detection and pagination. Do not treat any visible link subset as the full board.
- **Arm COMP-0724:** TalentBrew reported 452 total, retained 15, then failed to identify page 2. Current root returns 200. Inspect `shared_extended.py` page/next-link parser and canonical URLs; test all-page enumeration, repeated-page detection and final count. Apply provider improvement to Applied Materials COMP-0793 only after verifying its separate TalentBrew tenant and listing semantics.
- **Dematic COMP-0248:** configured `/KION_SCS?Country=...` is neither a supported path nor unfiltered source under `dematic.py`. Source repair currently leaves it unchanged. Determine intended country subset, validate filter IDs, and support that exact scope or an explicitly accepted replacement; do not drop all country filters just to pass the guard.
- **Lattice COMP-0736:** discovered Workday URL contains old browser parameters (`bga`, `hashed`, dimensions, timezone offsets, etc.). Distinguish harmless old embed metadata from actual filters using verified current board state. Pin the exact canonical board only when same scope is established; keep unknown filters fail-closed.
- **Gray Solutions COMP-0398:** recorded guard explicitly requires Gray AES successor `searchPositionType=37044`. Verify that legal/employer mapping and exact public iCIMS filter; never import the whole Gray family to satisfy a company row.
- **Amentum COMP-0005, HII COMP-0080, Komatsu COMP-0240:** inspect actual published total/range/page membership contract against their existing adapters. Missing totals and repeated IDs can be either changed markup or a real incomplete fetch; retain partial on ambiguity.
- **GDIT COMP-0011, MITRE COMP-0025, Textron COMP-0088, Honeywell Aerospace COMP-0436, Amphenol COMP-0490:** recorded listing drift/count disagreement calls for bounded reconciliation and stable final membership, not relaxed counts. MITRE already reports exhausted reconciliation; first determine whether the source is continually changing.
- **Field AI COMP-0217, u-blox COMP-0257, Emerson COMP-0555, BELL COMP-0631, Embraer COMP-0634:** individual malformed/missing descriptions or underfilled inventory. Re-fetch exact recorded IDs; distinguish closed posting from schema variation. Preserve full-description validation. BELL's 41 unique vs 105 advertised also requires Taleo page coverage, not just one description fix.
- **Genasys COMP-0300, Hallam-ICS COMP-0397, MilDef COMP-0429, COMROD COMP-0488:** respectively provider identity, SaaShr link parsing, Teamtailor pagination, and newly out-of-scope role link. Capture actual changed response first; preserve identity and completeness invariants.
- **ECS Solutions COMP-0405, Savox COMP-0494:** no verified jobs/explicit empty inventory. Add an explicit provider empty-state contract only if supported by current source evidence; absence of parsed links is insufficient.
- **Vanderlande COMP-0529:** discovery and configured ATS disagree; verify the current board then repair ATS+URL together. Check the separate Bastian row for parent/subsidiary overlap.

### W09 — Bosch Rexroth is already implemented; validate adoption

COMP-0571 remains partial in this completed cycle because its recorded attempt fetched 5,047 Bosch Group postings and failed validation on 15. The current runtime already contains `bosch_rexroth.py` and the exact company dispatcher at `ats.py:751-754`. Earlier same-day isolated live validation returned complete with **70 US Bosch Rexroth Corporation postings**, after rechecking 355 US Bosch listing cards, in 36.78 seconds. That receipt is summarized alongside this file; it does not update this cycle or prove Sheet publication.

Do not rebuild or revert this adapter. Verify the installed source hash matches the receipt, then validate it through the next authorized fresh process/normal run. A running Python process can retain already imported code. Preserve scoped source identity, SmartRecruiters posting IDs, and manual decisions. The broad Bosch parent inventory must not become the Rexroth inventory. Existing GitHub package: branch `integration/bosch-rexroth-20261117`, commit `ff382f890d36f069d4248ada44320a6219be8e00`, directory `integration-updates/bosch-rexroth-20261117` in `Jeckell102/job-search-helper`.

## Cases that cannot yet be promised as full integrations

**Access/response investigations (117 initial-group records):** 48 Workday, 56 other access/HTTP failures, 13 network/service failures. These are the recorded first-error groupings, not 117 proven site blocks. Workday often fails after several pages/details, and Leidos additionally hits a 2,000-result ceiling. Gather exact failed URL, status, content type, bounded response classification, page/offset and current concurrency. `_challenge` in `ats.py` already avoids treating normal successful JSON containing a keyword as a challenge; do not assume every recorded challenge is a simple false positive. Check per-host pacing/bounded retries and public source correctness. Genuine login/CAPTCHA/access-denied cases stay unresolved; no bypass is part of this plan. Existing native support does not mean a new wrapper will fix access.

**Employer scope/multiple boards (15 initial-group records, plus overlapping cases):** parent-company boards are not automatically company inventories. DroneSense→Versaterm, Dedrone→Axon, AMERGINT→CACI, CAE USA, Fox Robotics→Symbotic, JLG→Oshkosh, Hitachi Energy→Hitachi, Airbus US Space & Defense→Airbus and Accenture Federal→Accenture require explicit attributable scope. Prove legal entity/brand/business-unit facet or an official complete set of boards. Keep true US/subsidiary constraints. Keyword search and a location match are not always employer attribution. Geek+ and Astroscale already report subset/stale board ambiguity; do not silently widen to all regional companies.

**No proven public inventory (4 explicit initial-group records):** Perennial Autonomy COMP-0167, SkySafe COMP-0169, Blues COMP-0281 and Glenair COMP-0489. Current cycle evidence indicates homepage/contact, LinkedIn-only, or interest form rather than a complete public jobs list. These need a new official public source before a full scraper can be justified. The four were not newly probed in this audit. XOCEAN COMP-0354 and some other discovery-group companies may ultimately belong here too; a missing ATS link alone does not prove absence of jobs.

**Discovery still unresolved:** many C2 sources return a reachable page without a native board. The per-company register includes final URL and candidate links/markers where observed. An HTML page, a provider logo/script, a talent-community link or one job detail is only a lead. Examples of false positives in automated extraction include ModalAI's blog article about greenhouse farming and Timken's greenhouse-gas reference: neither establishes the Greenhouse ATS. Ignore raw marker-only guesses until linked public inventory is verified.

## Acceptance contract for the implementation agent

1. Re-read current repository instructions and current runtime files. Compare `snapshot.json` source hashes before editing. The installed runtime has newer modules than GitHub main; do not overwrite it with the older main checkout or apply a broad archive. Work in an isolated copy/branch and keep the user's existing modifications.
2. Confirm the exact company ID, name, configured source and intended geography/business-unit scope. Add source repairs only for exact known aliases. Use current official employer→board evidence, not an inferred slug or search result. In particular, preserve manual source/filter choices unless replacement scope is demonstrably equivalent or authorized.
3. Implement one shared fix/work order at a time. Use the real normal dispatcher and production transport contracts in tests. Retain meaningful diagnostics with page/posting ID and preserve saved valid jobs on partial failures.
4. `complete` requires a verified complete enumeration (including pagination/total/explicit-empty contract), unique canonical stable IDs, full public descriptions for every in-scope active posting, and a final stable membership check or bounded reconciliation. Listing size can change legitimately. Every unresolved detail, ambiguous scope, truncation or challenge remains partial/blocked/unsupported as appropriate.
5. Validate fixtures and then the actual public source through normal dispatch without Sheet/database publication. Document date, source, scope, listing total, unique IDs, fetched full descriptions, rejected/missing records, pages and reread results. A fixture-only pass or one HTTP 200 is not production completion. Test representative boards when changing a shared provider, then the affected cohort.
6. Keep original source/job identity stable where possible. If changing scope/ATS identity, explicitly review existing stored jobs, checkpoint keys and closure eligibility; do not convert prior parent-board records into employer-scoped jobs by relabeling them. Do not auto-close jobs from incomplete inventories. Protect manual selections, notes and existing Opportunities.
7. Before installing or resuming, inspect current process/locks in the actual host environment. Sandbox PID visibility alone is not reliable proof the scraper stopped. Never remove writer/scraper locks to force a second process. Recheck current cycle state and exact CLI semantics; this audited cycle already ended with exceptions, so do not blindly assume a resume will retry it.
8. Verify separately: adapter live success, run adoption/company completion, durable local inventory, and Google Sheets outbox delivery. Record each. Do not manually promote company stages or `Last Checked` to make the counter move.
9. Commit relevant code/tests/docs and save to the user's GitHub, preserving existing changes. This audit is documentation only; the future agent needs authorization for any additional operational changes outside that task's scope.

Suggested start order: W01 shared Rippling → W03 transport wiring with Hughes W02 → remaining W02 count contracts → W04 Lockheed routing → W06 Serve/Ubiquiti → W05 redirects → W08 provider-specific repairs → discovery/scoping/access investigations. Address W07 before enabling Caterpillar completeness.

## Full company register

The register is generated from the immutable snapshot plus reviewed implementation notes. `Initial group` is the automated reason bucket; `Disposition` is the reviewed work assignment. `Candidate code` is a navigation aid (name/ID text matching plus explicit corrections), not proof that runtime dispatch reached every listed module. Read the exact reason first. Source-probe candidate links are discovery leads, never automatic replacement URLs.

<!-- COMPANY_REGISTER -->
