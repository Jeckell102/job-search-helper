# Current protected-source reconciliation coordinator status

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
