# Protected-state legacy-restart-backlog classification

**Scope.** Direct SQLite reads with `sqlite3 -readonly` against the production Jobs database only. No queue delivery, acknowledgement, coordinator command, process, lock, or external request occurred.

## Actual durable facts

`jobs.sqlite3` contains exactly **one** `scrape_outcomes` record and exactly **one** outcome-delivery acknowledgement/receipt:

- outcome `OUT-73328ca07b6f86f7d8fc8dfc`; company `COMP-2522FE051E36`; outcome `COMPLETE`; action `save_without_repair`; recorded `2026-11-21T04:45:15+00:00`.
- it has **no** `wrapper-coordinator` delivery acknowledgement.
- it has exactly one `repair-coordinator` acknowledgement, at `2026-11-21T04:49:34+00:00`, and exactly one matching sender receipt. The receipt is `ACCEPTED`, has sink status `RECORDED_NO_REPAIR`, and binds the same outcome and record digest.
- `scrape_outcome_delivery_attempts` has **zero rows**. There is no pending/uncertain retry attempt for either consumer.

Thus the protected-state failure is a literal schema/consumer mismatch, not an outstanding transport operation: line 218 of the legacy `protected_state.py` requires every outcome to have an acknowledgement from the obsolete `wrapper-coordinator`, while actual current delivery is recorded under `repair-coordinator`.

## Settlement classification

The existing Freeform outcome is already settled for the supported repair route: the sender-side receipt is present and says `RECORDED_NO_REPAIR`. It must not be sent again merely to satisfy the obsolete consumer name. Creating a second `wrapper-coordinator` acknowledgement would be an unsupported historical replay and would not establish a valid receiver receipt in the newer protocol.

The smallest preserving alternative is to treat the legacy guard as unreachable for this native retirement capture and capture/verify state using the newer default-off host's supported `repair-coordinator` receipt-v1 evidence, while independently checking the existing sender receipt and the coordinator-side peer receipt in the actual host store. This requires no queue drain and no mutation.

## Reachability of the legacy guard

The legacy guard remains reachable **whenever the old Sprint-4 `protected_state.py` is invoked**: its line 218 directly queries for `wrapper-coordinator`, and line 220 also rejects attempts for either old or new consumer. The staged newer host has `SCRAPE_OUTCOME_CONSUMER = 'repair-coordinator'`; its source has a default-off receipt-v1 bridge and explicitly raises `Legacy production-shaped outcome drain is forbidden` for the repair consumer. Therefore the newer installed default-off host prevents a legacy drain, but cannot make that old protected-state predicate true.

Release consequence: do not weaken/rewrite the old guard in place and do not fabricate a legacy acknowledgement. The repair coordinator should supply an exact read-only two-sided receipt check for this one existing outcome, and the retirement bundle must use that newer checker rather than the old line-218 predicate.

## Remaining evidence gap

This probe confirmed the sender-side receipt in Jobs. The installed service unit points to `/home/chris/job-search-helper_old/dev/wrapper-coder/tools/host_server.py`, whose default `Coordinator` store convention is the adjacent `tasks/tasks.sqlite3`. That directory is mode 0700 and this confined read-only runner cannot traverse it, so the peer receipt must be read by the separately elevated host observer/owner. The ordinary `.state/state.db` is not that store and has no `scrape_outcome_delivery_receipts` table. Until the peer record is read and compared by outcome ID, record SHA-256, receipt text, and receipt SHA-256, call the supported settlement `sender-settled / peer-readback-pending`, not fully two-sided verified.
