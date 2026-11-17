# MuleLab wrapper coordinator QA assessment

Assessed: 2026-11-17. Source revision: `470d447cc33a8445866b5ea7d2d97a4dbbde7e03` on `tools/wrapper-coder-20261117` in `Jeckell102/job-search-helper`.

**Verdict: changes required before unattended development.** The sequential worker architecture and durable task records work in the covered cases, but five confirmed control defects remain. Two are high priority. The existing 40 tests pass; six added adversarial checks fail and reproduce the five findings below. These are reproducible software defects, not evidence that a live task has already caused damage.

This assessment changed no runtime code or service configuration, restarted no services, and submitted no live coordinator tasks. All fault injection, model responses, test-runner responses, edits and receipts in the new probes use disposable fixtures on MuleLab. No model inference or company website access was required for these probes.

## Findings

### F1 — P1: An explicit instruction not to modify files enables development edits

Location: installed `tools/coding_tools.py:40-46`, used by `tools/coordinator.py:109`.

The objective `Review src/a.py; do not modify any files. Run tests/test_a.py.` selects `develop`. The scope parser sees the word `modify` as authorization, while its negative guard only recognizes a few phrases such as `do not edit`. The probe then supplies ordinary worker tool calls; the coordinator changes the fixture from `value = 1` to `value = 2` despite the prohibition.

Impact: a review request can expose editing tools and permit unwanted changes in the development checkout. Production installation remains a separate gate, but the user's development files are still at risk. Phrasing such as a request to review a proposed “fix” is also treated as editing authorization by this keyword design.

Required repair: use an explicit, validated task mode selected by the command interface, defaulting to review. Do not derive write permission from arbitrary words in an objective. Preserve an explicit no-write constraint even if the objective discusses changes. Add regression coverage for negative wording and descriptions of proposed edits.

Reproduction: `test_explicit_do_not_modify_must_not_enable_or_perform_edits`.

### F2 — P1: A snapshot-write error can kill the scheduler without stopping the service

Location: installed `tools/coordinator.py:159-177`; `tools/host_server.py:75-78`.

After an export fails, the scheduler's exception handler calls the same export function again outside further protection. A second failure escapes the daemon thread. Injecting a snapshot `OSError` left the task `QUEUED`, with the coordinator thread dead and an uncaught `OSError`. The HTTP server runs separately; its main loop can continue, so the service's `Restart=on-failure` cannot detect this thread-only failure.

Impact: every queued task can stop progressing while the service still appears active. This is especially relevant to the promised ability to continue after the chat closes.

Required repair: contain failures in the scheduler's recovery path, preserve the authoritative database state, and expose worker liveness through a health check. Stop or restart the process under supervision when the worker cannot recover. Distinguish a failed readable export from an uncertain tool action; never replay an edit merely to regenerate a snapshot.

Reproduction: `test_snapshot_write_error_must_not_kill_scheduler_thread`. The HTTP-server consequence is established by code inspection; no live storage failure was induced.

### F3 — P2: Inspection can finish without reading the assigned code or obtaining source evidence

Location: installed `tools/coordinator.py:353-359`.

The inspection gate accepts any successful `code_read` and any successful web tool when a URL appears in the objective. The probe reads only the protocol document, makes an unrelated web search returning an empty result list, and requests `phase_done`. It advances through verification to `REVIEW_COMPLETE_LIVE_NOT_VALIDATED` with a successful fixture test result. It never reads the assigned wrapper or its test assertions and never obtains the requested company page.

Impact: the label “review complete” and progression into editing can represent missing investigation. The live-validation qualification remains intact; this finding does not imply automatic production approval.

Required repair: track task-specific required files and source targets in structured state. Require receipts for the assigned wrapper, source mapping, routing and tests where applicable. Distinguish search discovery from retrieved company evidence and retain an explicit blocked state when the required source cannot be inspected. Keep the separate live scraper validation gate.

Reproduction: `test_empty_unrelated_search_and_protocol_read_cannot_satisfy_inspection`.

### F4 — P2: Per-task token and time limits are not enforced at dispatch

Location: installed `tools/coordinator.py:236`, `:288-311`.

The loop checks tokens already consumed, then reserves and dispatches a new call without comparing the reservation to the remaining task allowance. With 119,999 tokens already accounted against a 120,000 limit, the probe still starts a call and finishes at 120,559. The one-hour check runs before a session, not before each call: advancing the fixture clock past the deadline during the first call still allows a second call.

Impact: the advertised task limits can be exceeded, occupying the limited Jetson inference capacity longer than intended. The separate 12,288-token context check remains functional; this defect concerns cumulative task limits.

Required repair: check the remaining token allowance against prompt plus requested output before dispatch, cap output where feasible, and check an elapsed-time deadline before every model or tool action. Account conservatively for uncertain calls and reject invalid usage counters. Define whether queue and paused time consume the task deadline and report that choice consistently on resume.

Reproductions: `test_dispatch_must_reserve_remaining_total_tokens` and `test_elapsed_deadline_must_stop_next_call_inside_a_session`.

### F5 — P2: Timing changes defeat the no-progress stop

Location: installed `tools/coordinator.py:345-351`; `tools/rendered_web.py:98`.

Progress compares the entire result JSON. The rendered reader includes `render_seconds`, so repeating the same request with identical content but slightly different durations counts as new evidence. Four identical fixture page reads with timings 1.0, 1.1, 1.2 and 1.3 seconds leave `no_progress = 0` and the task `QUEUED`. The expected stop after three subsequent sessions without new evidence never happens.

Impact: a worker can consume its remaining sessions and inference budget rereading the same material. This weakens the automatic handoff loop on the Jetson.

Required repair: compare stable evidence fingerprints—source URL, meaningful content, links, source hashes, exit status and normalized test results—and exclude durations and other incidental metadata. Retain the full unnormalized receipts for auditing.

Reproduction: `test_render_timing_alone_must_not_count_as_progress`.

## Verified strengths and limits

| Check | Result |
| --- | --- |
| Existing host suite | 38 passed, rerun against installed modules |
| Existing gateway suite | 2 passed against staged source matching installed gateway hashes |
| New adversarial suite | 6 failures reproducing F1–F5; no unexpected test errors |
| GitHub backup | All 14 manifest-listed files fetched at the assessed commit and verified by content/hash; six installed host files and four installed Jetson hashes match assessed source |
| Running services | MuleLab host and tunnel, and Jetson orchestrator, reported active |
| Endpoint authentication | Both `/coordinator` and `/api/wrapper-turn` returned HTTP 403 without credentials |
| Task storage | Read-only SQLite integrity check returned `ok`; no queued/running/pausing tasks at assessment time |
| Earlier Scythe acceptance record | Still durable: review complete, live not validated; 2 sessions, 8 model calls, 44,994 tokens, 12 receipts |
| Actual MuleLab tokenizer | Complete protocol plus representative task/tools: 2,960 prompt tokens, 9,296 available generation tokens in the 12,288 context, including the 32-token safety margin |

Existing passing coverage includes pending-action recovery without automatic replay, preserving pauses across recovery, guarded source edits, rejecting truncated tool calls, test-failure gates, source drift detection, explicit `do not edit`, context-driven checkpoints and removing private reasoning from the gateway response.

The workload placement is appropriate: durable state, tool execution, web rendering, tests and host context calculation live on MuleLab. The gateway uses the existing shared background inference gate. The gateway tests stub inference; this assessment did not remeasure GPU memory, latency, interactive priority under load or actual concurrency. The previous Scythe run remains a historical acceptance record, not a fresh live scraper validation. Authentication checks are narrow endpoint probes, not a full security audit.

## Reproduce and accept fixes

Run the new isolated checks from this directory:

```sh
python3 -B test_qa_controls.py --tools /home/chris/job-search-helper_old/dev/wrapper-coder/tools
```

The current assessed revision should report six failures and exit nonzero. The probes import the installed test fixture, replace its repository/task directories with temporary directories, and mock model, web, tests and Git operations. They never create a task in the running coordinator database.

Repair F1 and F2 first, then F3–F5, keeping all scheduling and evidence checks on MuleLab. Require these six regressions and the original 40 tests to pass. Then perform one bounded real review task spanning at least two fresh worker sessions and a controlled recovery check. Confirm a meaningful saved handoff, exact evidence coverage, and successful completion of the protocol's separate live scraper check before treating a wrapper as verified and ready for installation.

Supporting files: `adversarial-results.txt`, `baseline-host-results.txt`, `baseline-gateway-results.txt`, `health-results.txt`, `backup-comparison.json`, and `test_qa_controls.py`.
