# Required wrapper development and test protocol — version 1

Follow these steps for each company. Work on one bounded company task at a time. These instructions are loaded automatically by Wrapper Coder before every coding turn. Continue from saved evidence; never invent a successful action or skip a failed gate.

## 1. Establish scope and baseline

- Confirm the exact company name, company ID, configured ATS and careers URL. Confirm the official employer-to-provider relationship using public evidence. Keep employer, subsidiary and geographic scope explicit.
- Read existing wrapper, source-repair entry, normal dispatcher, related tests and any saved company development note. Check for existing completed work before duplicating it. Use short excerpts to conserve context.
- Run the relevant existing tests with code_test before editing. Record actual exit code, passing/failing counts and failures. Pre-existing failures must be distinguished from regressions.
- Save progress to docs/<company>-development.md when edits are authorized. Include task scope, source URLs, baseline and next action. Work stays in the scraper computer's dev/wrapper-coder/repo; temporary tests stay in dev/wrapper-coder/runs. Do not create a Jetson workspace. Public web searches and page reads also execute on MuleLab through the host bridge; keep the Jetson focused on inference.

## 2. Inspect actual public source behavior

- Use permitted web tools to establish current redirects, listing structure, pagination, IDs, description fields and empty-state behavior. Record URLs and observation time when available. A reachable HTML shell, HTTP 200, search snippet or sample job does not prove inventory completeness.
- If tools cannot inspect the necessary public listing or detail data, state exactly what evidence is missing. Do not guess a new schema or invent fixtures and call them captured evidence. Existing fixtures may support a clearly labeled provisional change.
- Distinguish captured public fixtures from synthetic edge cases. Minimize fixtures to the fields/content needed for tests; exclude credentials, private data and unnecessary copied content.

## 3. Implement a bounded change

- Reuse the existing provider adapter where appropriate. Update wrapper, exact source aliases and dispatcher together as required. Use code_read hashes for edits and preserve unrelated changes.
- Preserve stable job identity, employer scope, full descriptions, pagination and final inventory reconciliation. Never replace an old hard-coded count with a new hard-coded count. Do not accept an unproven empty inventory or broaden an allowlist to arbitrary hosts.
- Do not loosen a test merely to make it pass. Fix the cause or document a legitimate contract change with source evidence.

## 4. Verify through scraper code offline

- Before describing what a test proves, read its actual assertions with code_read. Never invent coverage from a filename, a pass count or these instructions. If only execution output was inspected, report the count and exit status without claiming specific assertions were checked.

- Tests must import the development scraper code, not a duplicate implementation. Use the real public entry point job_search_helper.ats.fetch_inventory(configured_ats, configured_url, company_id, company, ...) so source repair and dispatcher routing are exercised.
- Include a nonempty normal-dispatch test starting at the actual configured careers URL, not only a direct wrapper call or already-repaired provider URL. Check returned ATS, canonical source, stable IDs, descriptions, counts, requested pages and final reread.
- Exercise default transport selection by mocking the lowest relevant network boundary. A permissive injected fake can hide production URL restrictions or the wrong client; direct-wrapper fixtures alone are insufficient.
- Cover the applicable cases: multiple pages; duplicate/missing IDs; wrong employer/tenant; missing description; missing listing marker; explicit empty state versus an unproven empty page; truncated results; changed final membership; allowed redirects and rejected foreign targets; blocked/network responses. Mark non-applicable cases with a reason.
- Run focused company tests plus the relevant source-routing/provider regressions with code_test. Tests are offline, time limited and filesystem restricted. A sandbox, timeout or import failure is not a passing test. Split large suites into bounded groups if necessary.
- Inspect code_diff and read new files separately because untracked files may only be listed in the diff result. Record changed files and actual test evidence in the company development note.

## 5. Required live read-only scraper validation — operator gate

- The current Wrapper Coder code_test tool is OFFLINE. Web page reads are not a live scraper run. There is no tool in this profile that runs the full scraper against the network. Never claim this gate passed from fixture results or website accessibility.
- Hand off the exact company inputs, changed files, focused test names, public evidence and missing checks to the operator. Until a receipt is supplied, report IMPLEMENTED_AWAITING_LIVE_VALIDATION (or BLOCKED if implementation cannot proceed).
- The operator reviews the diff and runs the development checkout's actual fetch_inventory with the original configured ATS/URL, company ID/name and default production transports. Use a bounded isolated read-only harness, no live credentials, no browser profile, no inventory/checkpoint database writes and no Sheet publication. Do not run the production start/resume command or a full scrape cycle for this gate.
- Verify that imports resolve to the development checkout. The successful result must have proven complete employer-scoped inventory, unique stable IDs/URLs, full descriptions for all included jobs, all pages accounted for, and a stable final inventory reread. Reconcile returned IDs/counts against the actual public listing, not a historic expected number. An empty result needs explicit source evidence. A partial, blocked or timed-out run fails this gate even if some descriptions were saved.
- Save a receipt locally under the dev folder: UTC time, exact invocation, source/code hashes, company inputs, final URL, result status/reason, inventory/detail counts, pagination and reconciliation evidence, unresolved issues, and evidence-file paths. Feed the result back into the company note; repair and retest if needed. A sample-only check must be labeled sample-only.

## 6. Delivery and completion

- Live validation, installation, run adoption and Sheet publication are separate states. Never equate a passing test, local commit, HTTP 200, generated file or model claim with all four.
- After required tests and live validation pass, the operator compares the development changes against the current active checkout, preserves unrelated work, backs up replaced files, installs wrapper/dispatcher/tests/notes alongside the existing integrations, verifies installed hashes and routing, and saves sanitized source/evidence notes to GitHub. The model's local commit does not perform these steps.
- Report VALIDATED_AWAITING_INSTALLATION until installation is verified, and INSTALLED_BACKUP_PENDING until the GitHub copy is verified. Report COMPLETE_FOR_IMPLEMENTATION_AND_DELIVERY only after both; report run adoption and Sheet publication separately. Do not restart the running scraper or modify live data solely to test a wrapper.
- End every work response with: current stage; files changed; actual test results; live-validation status; installation/GitHub status; and the next concrete action. If context or tool limits are reached, save a concise handoff when authorized and stop honestly. If the host or this protocol cannot be loaded, stop coding actions; do not fall back to Jetson storage.

## First trial: Scythe Robotics

COMP-0506, Scythe Robotics; configured ATS: Dover careers; configured URL: https://joinscythe.com/. Inspect scythe_robotics.py, its company_sources.py entry, ats.py route, and tests/test_scythe_robotics.py. Existing tests include synthetic wrapper cases and a normal-dispatch empty-page fixture; these are not live acceptance evidence. Investigate the current Dover redirect and actual listing schema before extending them. Do not mark the company complete merely because the original four tests pass.
