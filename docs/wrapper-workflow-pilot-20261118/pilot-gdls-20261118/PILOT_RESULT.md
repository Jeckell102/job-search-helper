# Controlled integration pilot — FAIL

Company: General Dynamics Land Systems (COMP-0097). Task: WRAP-8be410e6f4.

The repaired coordinator ran one isolated company through baseline/evidence collection and four genuine Jetson inference calls. It stopped PAUSED_BLOCKED because repeated actions added no source coverage or edits. Accounted tokens: 32,025. No budgets were reset and no replacement task was launched.

Baseline offline tests: 2/2 passed. Assigned source and test files remain byte-identical to the frozen baseline. No wrapper was installed.

Live normal-dispatch test: actual task-checkout fetch_inventory, original configured company inputs, default production transports, in a network-enabled read-only OS sandbox with no user credentials or production databases. Result: PARTIAL, zero jobs, HTTP 308 from the configured General Dynamics careers route. Complete inventory, full descriptions and stable reread were not achieved. The second full read was correctly skipped after first-read failure.

Evidence: live-validation-2/live-validation.json and inventory-1.json. live-validation-1 is an invalid environment attempt: the initial sandbox omitted the DNS resolver symlink target; corrected read-only resolver exposure produced the conclusive HTTP 308 result. Do not attribute the first attempt's network failure to the wrapper.

All scheduling is OFF, pilot slot cleared, no active tasks. Other companies were not launched. The integration test FAILED despite passing coordinator unit QA.

Next repair: inspect why the AI repeats already collected evidence instead of following the mapped listing redirect and inspecting its current schema; capture current scoped listing/detail evidence; repair redirect/parser behavior with meaningful regression tests; repeat this controlled live gate before installation. Also fix the CLI status response truncation at 100000 bytes (full authenticated JSON reads work). No coordinator/runtime code was changed during this pilot.
