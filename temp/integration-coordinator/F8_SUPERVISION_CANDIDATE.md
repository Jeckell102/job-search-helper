# F8 supervised operation and retention candidate

Updated: 2026-11-19. The source candidate was installed through the protected,
rollback-backed integration process after independent acceptance. The live
host has since passed restart, planned-stop and disk-pressure hold/recovery
exercises without starting scraper work or discarding evidence.

## Implemented boundary

- Extends the existing coordinator host; it does not add a second task
  scheduler. The existing `scheduler.lock` remains the only task owner, while
  `supervision.lock` permits one maintenance owner.
- Runs bounded durable scrape-outcome catch-up at service start and while the
  service remains connected. Catch-up failure leaves the producer outbox
  authoritative and records a retryable state.
- Stores the current supervision state in the coordinator's maintained SQLite
  `settings` table.
- Pauses queue, campaign, and pilot admission under disk pressure. It never
  deletes evidence automatically.
- Reports protected coordinator records plus read-only counts for
  unacknowledged Company events, unacknowledged scrape outcomes, unconfirmed
  publication receipts, nonterminal release journals, and active release
  records.
- Marks planned shutdown before either worker is stopped, so the watchdog does
  not convert an intentional stop into a crash. Shutdown disables all scheduler
  modes, waits for the scheduler's current action to end, then durably pauses
  active work at the existing action boundary. A timeout records
  `SHUTDOWN_RECOVERY_REQUIRED`; it never falsely records a safe pause.
- Reports automatic repair support only from the reviewed profile registry.
  The registry is currently empty, so every unmatched or unqualified family is
  honestly reported as requiring engineering review.

## Verification

- Independent QA reviewed the corrected exact source and returned `ACCEPT`.
  It confirmed the real host closure supplies both exact consumer identities,
  the planned-shutdown/watchdog repair remains covered, and no source-level F8
  blocker remains.
- Focused supervision plus inherited live-coordinator checks: 33 passed.
- The real host-wiring check proves its zero-argument closure supplies the job
  database and both consumer identities, then persists nonempty external counts.
- Full isolated coordinator suite with the application source available: 233
  passed.
- The same focused supervision selection over the current protected-source
  reconciliation copy plus the host-wiring check: 34 passed.
- The shutdown integration check runs the actual coordinator scheduler with an
  action held in progress, a live watchdog, and a concurrent planned stop. It
  proves there is no forced exit, the scheduler releases ownership, the task is
  durably `PAUSED`, and supervision records `SHUTDOWN_PAUSED` only afterward.
- A separate timeout check proves unfinished work remains `RUNNING` with a
  durable recovery-required record rather than a false pause.

## Open gates

- Final sequential acceptance across three unfinished Companies with distinct
  source structures and the shared-adapter regression set.
- The separate administrator-authenticated Jetson F4 interruption proof.
