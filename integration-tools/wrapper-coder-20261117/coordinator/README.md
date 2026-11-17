# MuleLab wrapper coordinator

MuleLab stores and schedules wrapper tasks, checks context size, executes tools, runs offline tests, and saves receipts and handoffs. The Jetson supplies one model inference turn at a time through the existing shared queue. Interactive inference takes priority when the next turn is selected. A running model generation finishes before a pause takes effect.

## Use from Wrapper Coder

Select **Wrapper Coder** on the Jetson and enter an explicit command:

```text
/wrapper start Inspect and fix Scythe Robotics COMP-0506 using https://jobs.dover.com/scytherobotics?src=app. Use src/job_search_helper/scythe_robotics.py, its company_sources.py repair and ats.py route. Run tests/test_scythe_robotics.py. Preserve full descriptions, exact employer identity, pagination and explicit incomplete states.
```

The reply provides a `WRAP-...` task ID. The task runs on MuleLab after the chat response ends; keep MuleLab and the Jetson awake. Fresh worker sessions start automatically and load the saved task state. Closing the chat does not stop the task.

```text
/wrapper list
/wrapper status WRAP-xxxxxxxxxx
/wrapper pause WRAP-xxxxxxxxxx
/wrapper resume WRAP-xxxxxxxxxx
```

`start` requires one to eight existing `tests/test_*.py` file paths. Include `fix`, `implement`, or another supported editing request to authorize source edits. Otherwise the task is read-only. The queued reply states the selected mode. The explicit `do not edit` instruction disables development edits. Slash commands are intercepted by software; model output or old chat history cannot enqueue a task.

The same commands are available on MuleLab through `tools/wrapper_task.py`. Its `start` command accepts `--max-sessions` between 1 and 20; the default is 10.

## Phases and acceptance

1. **Baseline:** MuleLab runs the requested tests through the existing filesystem- and network-restricted test runner. A failing baseline is retained for diagnosis.
2. **Inspect:** A worker reads the code, test assertions and applicable source evidence. The coordinator requires successful code-read receipts and, if the objective includes a URL, successful web evidence before accepting the phase.
3. **Implement:** Only development tasks enter this phase. A worker can make guarded changes in the development checkout. The coordinator requires code-read and diff receipts before moving on. A justified no-change result is permitted.
4. **Verify:** MuleLab reruns the original requested tests against current development files, checks that the source stayed unchanged during testing, and saves a source-manifest digest with the receipt.
5. **Operator gate:** Offline success ends at `AWAITING_LIVE_VALIDATION` for development, or `REVIEW_COMPLETE_LIVE_NOT_VALIDATED` for review. The coordinator does not certify full test coverage from a count or certify a repair from a worker's claims. Review the diff and actual assertions, perform the protocol's live read-only scraper check, then handle installation and GitHub delivery separately.

There is no automatic production installation, scrape cycle, Sheet publication or GitHub push in a generated task. The coordinator implementation itself is backed up separately on GitHub.

## Storage and recovery

All task records live in `dev/wrapper-coder/tasks/` under the active Job Search Helper directory on MuleLab:

- `tasks.sqlite3`: authoritative task state and write-ahead tool receipts.
- `<task-id>/checkpoint.json`: current phase, objective, counters, model summary and source hashes.
- `<task-id>/receipts.json`: actual tool inputs and results, including failures.
- `<task-id>/HANDOFF.md`: readable progress and exact status/resume commands.

Model summaries are marked as model-authored; tool receipts remain the evidence. Full tool output stays on MuleLab while bounded excerpts go into inference context. Worker private reasoning is not persisted. Generated task data, bridge credentials and package caches are not published to GitHub.

The coordinator runs one worker session at a time. Manual development edits, commits and tests through the bridge are rejected while it owns the workspace. An external file change causes a pause before the next session; guarded edits also check for source drift. Stop the task and wait for `PAUSED` before manual changes.

After a service restart, safely recorded work can resume automatically. An action with an intent but no result pauses for inspection; it is never blindly replayed. An in-progress pause remains paused. Repeated failure of the same request, three sessions without new evidence, failed verification, or exhausted budgets all stop with saved progress.

## Resource bounds

- Existing `qwen-wrapper:4b`, 12,288-token context; no second model is loaded by the coordinator.
- One inference request at a time through the shared Jetson gate, with background priority.
- Up to four ordinary inference turns per worker session, followed by a checkpoint-only turn.
- Closing starts when fewer than 3,800 generation tokens remain or the message count approaches the gateway's 24-message limit. If a checkpoint cannot fit, a deterministic checkpoint preserves receipts and the pending phase.
- Default 10 sessions, 48 total inference calls, 120,000 accounted tokens, and one hour per task. Resuming does not reset these budgets.
- Tests retain the existing 512 MiB, 24-task, 90-second offline sandbox. Browser reads use the existing rendered-reader bounds.
- Task orchestration, exact tokenizer work, web reads, tests, source hashing and receipts run on MuleLab. Jetson performs a final request-budget check and inference only.

## Installation and rollback

Host files install alongside the existing bridge tools. Install tokenizer dependencies into `tools/coordinator_vendor` using `requirements-coordinator.txt`; they do not alter the production scraper environment. Copy the existing pinned Qwen tokenizer assets to `tools/resources/qwen35`; the budget module checks their SHA256 values before using them. These are tokenizer assets, not model weights.

The existing SSH service adds a local loopback forward on port 18790 to the Jetson's protected `/api/wrapper-turn` endpoint. The endpoint requires the existing bridge token, uses the existing inference gate, permits a fixed model profile, and neither executes tools nor stores tasks. The existing reverse loopback bridge remains on port 18789.

The Jetson needs `wrapper_inference.py`, `wrapper_commands.py`, and the reviewed changes to `server.py` and `tool_runtime.py`. Existing manual chats retain their behavior; `/wrapper` commands select the persistent workflow.

Before installation, exact host/server/tunnel backups are stored in `dev/wrapper-coder/rollback/coordinator-<timestamp>/`. To roll back: pause tasks and wait for a safe boundary; restore the saved host server, Jetson server and tool runtime, and tunnel unit; reload those user services. Preserve `tasks/`, development source, receipts and checkpoints. No rollback requires deleting development work.
