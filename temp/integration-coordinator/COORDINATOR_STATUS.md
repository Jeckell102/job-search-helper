# Current protected-source reconciliation coordinator status

## Active checkpoint — 2026-11-19 accepted port and retained-route repair

- Persistent goal `01a1f124-9793-7e53-9d37-92f11052c967` remains active.
- The default-disabled Company intake dispatcher, exact controller handoff,
  and sync-watch wiring were ported onto the current protected-source snapshot
  in commit `2b95dd7`. Independent QA accepted that port after 37 strict
  adjacent checks; the implementation lane passed 65 strict checks.
- The dedicated signed retained Company-event route is still **rejected and
  uncommitted**. Independent QA found four activation blockers: nested
  nonreentrant scraper locking, no operational signed-envelope activation,
  replay risk from an unconsumed `next-scan.json`, and success reporting before
  terminal FIRST PASS settlement.
- Repair work has removed the outer nested lock, added an exact external
  `{manifest,envelope}` activation bundle, and is building crash-safe exact
  request consumption. That last recovery boundary must bind the archived
  request to the retained admission and durable `FIRST_PASS_RELEASED` evidence,
  preserve a newer request, and complete without refetch or remote replay.
- Nothing is deployed or activated. The historical cycle and its 45 retained
  inventories, six plans, and two confirmed receipts remain untouched.
- Roadmap accounting remains 0 of 6 milestone gates closed and final
  independent acceptance 0%. The current retained-route work item is about
  70% after QA rejection; automatic watcher supervision of that route, service
  deployment, live proof, and final acceptance still follow.

Reread this section after every context reset and before a major/live action or
user update. It supersedes older current-status claims below.

## Active checkpoint — 2026-11-19

- Persistent goal `01a1f124-9793-7e53-9d37-92f11052c967` remains active.
- This workspace is an isolated, sanitized copy of only the current protected
  MuleLab code, tests, `pyproject.toml`, and public launch scripts. It contains
  no live state database, credentials, raw job batches, lockfiles, or services.
- Baseline commit `c19c08b` freezes the copied protected code/test bytes before
  new work. The original `/home/chris/job-search-helper_old` remains the live,
  dirty protected checkout and must not be overwritten wholesale.
- Lane 1 is porting the independently accepted Company-event dispatcher,
  controller handoff, and default-disabled sync-watch wiring onto this current
  source.
- Lane 2 is implementing the dedicated signed retained Company-event route
  recommended by the historical-blocker decision. It must preserve all 45
  retained inventories, six legacy plans, two confirmed receipts, normal
  State/Inbox, locks, and the historical cycle.
- Nothing in this workspace is deployed or activated. Roadmap accounting
  remains 0 of 6 milestone gates closed and final independent acceptance 0%.
- Before any protected installation: independently review each lane, reconcile
  overlapping edits, run strict adjacent and full focused tests, build an exact
  narrow patch against freshly revalidated protected target bytes, save
  rollback copies, and keep intake disabled.

Reread this file after every context reset and before any protected/live action.
