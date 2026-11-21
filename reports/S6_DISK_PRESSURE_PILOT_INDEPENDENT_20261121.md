# Independent Sprint 6 disk-pressure QA

**ACCEPT for staged source on the supervised scheduler path.** The verified changes gate queue/campaign enablement and explicit task activation. The existing scheduler and inference receipts remain authoritative.

| Reviewed file | SHA-256 |
| --- | --- |
| `coordinator_store.py` | `9f0a84a626fcf910f24233759ff940ff68db81c97b9b0e7096a3d4b0580ea835` |
| `coordinator_supervision.py` | `c06e77fc42170277e462f811b32c2ff9821993c78a1765a83a4c92929eeeb012` |
| `test_owned_recipe_scheduler.py` | `62327ec9c8c4845b6845d662eb6e828a54b3ca2ff1c8dc740d8292a3fba66441` |

The first pressure observation durably disables the queue and campaign, clears the selected pilot, records its stop boundary, sets the guard, and advances control generation within one SQLite transaction. The early activation snapshot rejects before isolated workspace work, and the commit rechecks under its own transaction. A healthy tick clears the guard while controls and prior pilot disposition stay paused. Ordinary operator queue pause leaves a queued selected pilot available. [Store transaction](/tmp/jsh-s6-disk-pressure-pilot.20261121/dev/wrapper-coder/tools/coordinator_store.py:1027), [supervision tick](/tmp/jsh-s6-disk-pressure-pilot.20261121/dev/wrapper-coder/tools/coordinator_supervision.py:179)

- Both maintained regressions reproduced against the prior stage. Reopening after the low-disk tick still found the selected pilot. The in-flight pilot remained `RUNNING`.
- Both sustained regressions passed on the final pins. The gate also held before workspace creation and reopened only after the healthy tick.
- An independent composed probe attached the existing durable control binding to one actual fixture dispatch and applied pressure before the exact W1 reply. The in-flight receipt remained identical during the hold. Final settlement was `RESPONSE_DROPPED`, with no accepted choice or builder invocation. One call and 560 tokens were accounted. Reopening the store after a healthy tick preserved the paused task, disabled queue and campaign, and empty pilot slot.

The explicit `activate_next_campaign(..., require_enabled=False)` compatibility argument can still preselect work during the guard. Current runtime calls use the enabled check, and claiming remains gated by the disabled campaign. Guarding that compatibility call too would extend the no-selection invariant to direct callers.

Source and disposable fixtures only, with outbound connections and DNS denied. Native behavior, installation and deployment were outside this review.
