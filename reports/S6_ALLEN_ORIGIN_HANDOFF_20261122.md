# Read-only preflight follow-up

The final source moves only the writable-client requirement from shared `_local` into `continue_allen_source_reconciliation` before inspection, claim or remote work. `preflight_allen_source_reconciliation` now accepts actual SQLiteRepository(readonly=True). All existing guards remain.

The added fixture sets the historical Active Cycle ID to CYC-B639C6D864EC, reopens the fixture database read-only, installs a SQLite authorizer that denies writes/schema/transactions, and obtains READY with zero denied-write attempts. Continuation refuses immediately. A fresh read-only reopen proves identical logical contents and the historical field remains exact. Outer native admission owns verification that this cycle is retired; this helper neither clears that marker nor treats it as current-cycle permission.

Six focused cases passed. The first added fixture run failed only while trying to remove a Python 3.10 authorizer before the final dump; that result is preserved in TEST_RESULT_READONLY.txt. The fixture now closes/reopens read-only for its final dump, and TEST_RESULT_READONLY_FINAL.txt is the passing run. No application behavior was changed for that fixture issue. Original five-case source report/results remain as HANDOFF_INITIAL.md and RESULT_INITIAL.json.

## Specific downstream publication gate (read-only source review)

The old-source fence remains intentionally intact. The actual currently installed `SheetsSynchronizer._plan_exact_row` checks any conflict on the selected tab/row at sheets_sync.py:681-684 and raises `Exact Sheets scoped row has an unresolved conflict.` It does not make an ordinary-event exception for Companies.__company_source__. `exact_cycle_sync._publish_exact_v2` calls `sync.plan_exact_scope` at line559. `exact_local_plan._row_scope` derives targets from the frozen remote projection. The ordinary finisher removes redundant source-field changes but retains Company progress fields (`exact_cycle_planner._ordinary_company_operation`:693ff); Engine's final Company operation includes public Next Action, Last Checked and Last Scan Result (engine.py:1429ff), so the source-fenced Company normally remains a publication target.

Consequently a selected ordinary plan that includes that Company row cannot currently pass the stock exact planner with its source conflict intact. Do not clear the generic fence or relabel old data. The one next required proof is an actual disposable newly admitted Allen event/plan after this source merge, preserving the Company and old-job fences: inspect its final projection and exercise the exact planner/receipt path. If the Company is targeted, the exact conflict guard above is the concrete first refusal to address with independently scoped source provenance. No broad publisher exception, implementation, or production inspection was attempted in this lane. Existing job conflicts are not evaluated away by this report.

Installed code readback pins for this specific finding:
- sheets_sync.py 52845a8c0b59ce59e22840abc21748785dd35ad6c74db30f76be74b5697d2589
- exact_cycle_sync.py 40450ef4fa250daf473c5afc549533046b1caa41ccb73f543a6f410c40b3f80e
- exact_cycle_planner.py ddea425474e8559a3bbe95b96876c407eb21cc174086ec6f89815b1a1026df02
- ordinary_company_event_command.py a224af180302e4a69951a9cd7995585931e4ab2195612c8bfdb3740250687d38

## Final candidate pins
- src/job_search_helper/allen_source_reconciliation.py: 6e27a14271b56b13d72aef8ea118a730e6922ed2de8afe52442343327cc4e90a
- src/job_search_helper/sqlite_repository.py: a5a22c4d683ff58925370915aa63c8c58c5aa7e7f8ecefacb60b8af9d3dade3f
- tests/test_allen_source_reconciliation.py: ad010a37af229fccf4db286401b9173f0fccc904c1017919860e26b8ea33f668
- TEST_RESULT_READONLY_FINAL.txt: 3d21a127b7a92acb5fc8e3b27e835b2af5ded9c103c88f6dea1a245994cb1f4f

No live action or display/transport failure occurred. This follow-up supersedes source/test pins in the historical handoff below.

---

# Allen external-first continuation handoff

OFFLINE PREPARED; independent QA pending. No real Company, Google workbook, provider, Jetson, services, production source or native release was accessed by this callable or fixture. This is preparation for Allen's ordered turn, not authorization to run it.

## Files and API

New module: src/job_search_helper/allen_source_reconciliation.py. All copied dependency source is byte-identical to `/tmp/jsh-s6-allen-selected-events.5py9qk0t/src/job_search_helper`; only this module was added. The accepted selected SQLite reconciler is reused unchanged. New fixture: tests/test_allen_source_reconciliation.py.

`preflight_allen_source_reconciliation(local, remote, intent)` reads only and returns READY or HELD_UNCERTAIN_WRITE with intent hash, remote phase and whether a write would be needed. It constructs no client and writes neither database nor workbook.

`continue_allen_source_reconciliation(local, remote, intent)` uses those already-open clients and returns COMPLETE with exact Company event, intent hash and whether this invocation attempted a remote write. Caller owns canonical-client custody, runtime measurement, scraper/writer ownership, active-cycle admission and live approval. This helper does not acquire locks, schedule work, create a cycle or acknowledge an event.

Intent is a closed dict:
- schema: allen-source-reconciliation-v1
- spreadsheet_id: exact shared client workbook ID
- company_id: COMP-0164
- company: Allen Control Systems
- company_status: exact current active status text
- before: ATS / Source = Greenhouse; Official Careers URL = https://job-boards.greenhouse.io/allencontrolsystems
- after: ATS / Source = Ashby; Official Careers URL = https://jobs.ashbyhq.com/allen-control-systems
- expected_source_revision: canonical source_revision of the before Company fact

All fields are required. The caller must supply real measured expected input; the fixture workbook/intent is not live authority. The exact approved Greenhouse route is deliberately closed; another current source is a hold.

## Order and restart contract

Preflight requires one matching local and remote Company, exact name/status/source transition/workbook, no claim, completed external watermark, clean source/identity baseline and no pending source dirty/conflict/delivery fields. It preserves unrelated dirty fields and existing old-source fences. The existing retained-publication guard remains in force.

Remote discovery reads the Company ID column, then the exact matching native row with the existing repository. The sole write is existing guarded remote.commit with permanent Company ID identity, expected current control/source values and available claim controls, two source values, and append_if_missing=False. No whole-row update or append is possible.

Before this write, the helper saves one fixed Company intent claim in existing Jobs meta under `allen_source_reconciliation:COMP-0164`. This is a tiny restart record, not a new schema/framework or second authority. A conflicting intent is refused. The sequence is WRITE_CLAIMED -> REMOTE_CONFIRMED -> COMPLETE. This deliberately never retries a claimed write, including a crash immediately before dispatch; exact AFTER readback is required to advance. A definite pre-write refusal after claim requires explicit owner diagnosis, not automatic claim deletion.

After either a normal write or UncertainWriteError, exact remote AFTER readback must succeed before local work. If remote remains old, replay stays held with zero additional writes. A partial or changed source/control is also held. If the remote is already exactly AFTER, including a lost-response restart, no commit is issued.

The existing merge_remote imports only Company ID and the two source fields with complete_snapshot=False. The selected reconciler emits only the current exact Allen revision. These remain two durable transactions: a crash after merge replays event reconciliation; a crash after event commit recovers the same immutable outbox event. The terminal record binds that event and terminal preflight/readback rechecks it. No queue delivery or consumer acknowledgement occurs.

## Verification and limits

Five offline tests passed under system Python with private PYTHONPATH, bytecode disabled and an audit hook rejecting sockets/process spawn/shell execution. Normal completion and committed-response-loss each use one real MemoryRepository guarded commit, the real field-aware synchronizer, real SQLite revisions/outbox and close/reopen replay. Every unrelated workbook field/tab is equal; unrelated local values and dirty entries are equal; a genuinely changed second Company receives no event. Separate cases preserve uncertain-before-visible hold without reissue, resume after a committed merge, and refuse a dirty source before claim/write. Both initial and final logs are retained.

This proves composition with an in-memory workbook, not actual Google behavior, live locks, source freshness or installed authority. Parent must review/package the module and selected reconciler, then independently verify the exact live intent and normal guarded entry. Source-transition fences are retained; this helper does not prove subsequent provider, publishing or model-choice/retry acceptance.

## Exact pins
- src/job_search_helper/allen_source_reconciliation.py: ca6860b52ba34995b3fff473b3984bdf2f6e14a395ff569916d51a0f98b25fe9
- src/job_search_helper/sqlite_repository.py: a5a22c4d683ff58925370915aa63c8c58c5aa7e7f8ecefacb60b8af9d3dade3f
- tests/test_allen_source_reconciliation.py: 42905cdea72b69391e5925a6d16833169cc76db40cf54fd004df39d3fc4f0473
- TEST_RESULT.txt: 654841aa157ce63d67810d4a06a288710a2b625715a34f6cccbbc66f60e9d7d0

No display/transport failure occurred.
