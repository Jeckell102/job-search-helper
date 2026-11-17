# Coordinator QA repairs — verified 2026-11-17

**The five reported defects are repaired and installed.** A coordinator and three workers implemented and cross-reviewed the changes. Final validation passed 99 software checks and a real read-only task spanning two fresh Jetson worker sessions. The task and its receipts survived a controlled MuleLab service restart unchanged.

## Repairs

| Finding | Installed behavior |
| --- | --- |
| F1: unwanted editing permission | Task creation defaults to review; an explicit development flag is required. Supported no-write wording conflicts with development mode. Host and Jetson forwarding scope share the same prohibition checks. Older development tasks without explicit authorization pause. |
| F2: silent scheduler death | Snapshot failures report degraded health and are retried while SQLite remains authoritative. Database/control-loop failures receive bounded recovery. An unrecoverable or dead worker causes the host watchdog to fail the service for supervised restart. Missing action receipts never permit blind replay. |
| F3: weak inspection gate | Original tests and assigned wrapper/routing/source files need current read receipts. Declared source targets require meaningful successful retrieval; unrelated searches, empty results, HTTP errors and JavaScript shells do not qualify. Implementation needs a diff matching current source hashes. |
| F4: resource limit overruns | Prompt plus capped output must fit the remaining task token allowance before dispatch. Invalid usage pauses without executing returned tools. Time is checked before model and tool actions. Queue and pause time count toward the one-hour lifetime; resume retains all budgets. |
| F5: timing counted as progress | Progress compares stable evidence and source changes, excluding browser timings and test durations. Repeated identical material now reaches the no-progress stop. |

Cross-review found an additional F3 case: resume after an outside file change could retain the verify phase. Resume now reruns the baseline and requires inspection of current files. A dedicated regression proves old read hashes cannot pass that gate.

## Validation

- **84 host tests passed against the installed modules**, including the original host coverage, authorization, evidence, recovery, budgets, cross-interface parity, integration, and gateway-error handling.
- **9 gateway/command tests passed** against source matching the installed gateway/forwarder; backend inference is stubbed in these unit tests.
- **All 6 original adversarial QA checks pass unchanged** against installed modules. These were the six failures in the assessment.
- Real tokenizer check on MuleLab: 3,086 prompt tokens and 9,170 available generation tokens within the 12,288-token profile for the representative pre-follow-up request. Live inference also completed within the configured task allowance.
- Both host and Jetson forwarding permission paths rejected the contradictory development request. The authenticated health command returned healthy with a live worker and no snapshot errors.

The test fixture updates explicitly authorize development where required and supply newly required test-file reads; assertions for guarded edits, recovery, offline verification and operator gates were retained. The original six QA reproduction assertions were not relaxed.

## Real workflow acceptance

Task `WRAP-7f9c2bc240` completed as `REVIEW_COMPLETE_LIVE_NOT_VALIDATED`:

- 2 fresh worker sessions, 9 actual model calls, 49,451 accounted tokens.
- 10 durable tool receipts and a saved `HANDOFF.md` on MuleLab.
- Baseline and final Scythe tests both returned exit 0: **4 passed in 0.07s**.
- Requested tests, Scythe wrapper, company source mapping and dispatcher were read; the Dover page was rendered on MuleLab. Its recorded final URL matched the requested target, HTTP status was 200, and the receipt contained Scythe identity and an explicit no-positions statement.
- Baseline and final source-manifest digests are identical; no company source files were changed.
- A controlled restart of the idle MuleLab coordinator preserved the complete task state and every receipt exactly. Database integrity returned `ok`; scheduler health returned healthy.

An earlier attempt, `WRAP-9151133d19`, passed its baseline but paused after the gateway rejected too many tool calls in a model response. The exact error was `too_many_tool_calls`, not a Jetson outage. The worker prompt now requests one tool call per response, and bounded machine error codes are retained in status. The successful task above validates the follow-up. The earlier failed task remains paused as historical evidence; it was not marked successful or deleted.

This acceptance validates the coordinator workflow. It does **not** certify the Scythe integration's live `fetch_inventory()` result, inventory completeness, installation or Sheet publication. No company wrapper was repaired or installed in this task. Model-authored summaries remain untrusted; the acceptance facts above were checked against receipts.

## Installed files and rollback

All task data, tests, source observations, repair development and rollback copies remain under `/home/chris/job-search-helper_old/dev/wrapper-coder/` on MuleLab. The Jetson changes are limited to the command/permission forwarding runtime; model configuration, inference gateway and weights are unchanged.

- Development archive: `repairs/qa-20261117-155718/`
- Initial rollback copies: `rollback/qa-repairs-20261117-155718/`
- The intermediate coordinator before the transport follow-up is also preserved as `host/coordinator-before-transport-diagnostics.py` in that rollback directory.
- `DEPLOYMENT.json` records installed hashes. `LIVE-ACCEPTANCE.json` contains sanitized receipt facts and the restart comparison. Full task receipts remain local under `tasks/WRAP-7f9c2bc240/`.

For code rollback, stop at an idle boundary, restore the backed-up host and Jetson runtime files, then restart their respective services. Preserve the current task database and task directories; no schema migration or task-history rollback is required. Restoring the pre-repair code also restores the assessed defects.

Source, tests, updated operator instructions and sanitized verification were published with explicit approval to the existing public GitHub backup branch, `tools/wrapper-coder-20261117`. The source publication commit is `33da8a268fb0f5299790329c2e52429e2b5a3510`; all 27 published files were read back from that immutable commit and matched the prepared content byte for byte. Runtime task databases, bridge credentials, private prompts and full page bodies were excluded. The complete development archive remains on MuleLab, and `BACKUP-RECEIPT.json` records the remote verification.

## Operator commands

```text
/wrapper health
/wrapper start <review objective with tests/test_company.py>
/wrapper start --develop <development objective with tests/test_company.py>
/wrapper status WRAP-xxxxxxxxxx
```

Manual live scraper validation and installation of generated wrappers remain separate operator gates.
