# Coordinator verification, 2026-11-17

## Actual installed checks

- Installed MuleLab host regression suite: 38 tests passed, including 15 coordinator tests.
- Jetson gateway behavior tests: 2 passed. They verify shared background inference priority, bounded output, unsupported-tool rejection, and omission of private reasoning from the result.
- Host exact tokenizer loaded the pinned assets successfully.
- Wrapper Coder `/wrapper help` worked through the actual chat endpoint and SSH tunnel.
- Host bridge, tunnel and Jetson AI service were active after activation.

## Real model acceptance task

Task `WRAP-a7541481cf` was a read-only Scythe Robotics coordinator acceptance check, using `tests/test_scythe_robotics.py`. It requested continuation from one worker session into another, with no source edits.

- Two fresh worker sessions ran automatically.
- Eight actual model calls; 44,994 input plus output tokens reported across those calls.
- Actual host tool receipts include source and test reads, public searches, a blocked raw web read, test runs and a diff inspection.
- Baseline: `4 passed in 0.07s`, exit 0.
- Final verification: `4 passed in 0.07s`, exit 0.
- Terminal state: `REVIEW_COMPLETE_LIVE_NOT_VALIDATED`.
- State, receipts and a readable handoff remained available after restarting the host service.

The worker's prose is model-authored. One summary described the identity test as a wrong-company-ID case, while the actual assertion supplies the correct ID and a wrong company name. That statement is not accepted as verified coverage. The status display labels worker summaries for review; tool receipts and actual assertions remain authoritative. Successful offline tests do not establish a working live Scythe integration.

The live task validated automatic coordination and persistence, not deployment or live scraper acceptance. The runtime source has since received small receipt, status, recovery and prompt-context refinements covered by the final installed suite. No production scraper or Sheet state was changed by this check.

## Behavioral regression cases

Fresh-session continuity; completion requests without evidence; review-mode write denial; rejection of truncated model tool calls; external file drift; missing action receipts after a crash; safe recovery; pause/resume; pause across restart; repeated failures; no-progress stopping; early checkpoint mode; failed final tests; development edits with final source-bound test receipts; and budgets that cannot be reset by resuming.
