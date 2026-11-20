# Current protected-source reconciliation coordinator status

## Active checkpoint — 2026-11-19 retained route accepted; supervision next

- Persistent goal `01a1f124-9793-7e53-9d37-92f11052c967` remains active.
- The default-disabled Company intake dispatcher, exact controller handoff,
  and sync-watch wiring were ported onto the current protected-source snapshot
  in commit `2b95dd7`. Independent QA accepted that port after 37 strict
  adjacent checks; the implementation lane passed 65 strict checks.
- The dedicated signed retained Company-event route is independently
  **ACCEPTED** in the production wrapper runtime. The four prior activation
  blockers are closed: no nested nonreentrant lock, an operational external
  Ed25519 signing/activation flow, crash-safe exact request consumption that
  preserves a newer request, and nonzero exit until durable FIRST PASS
  settlement plus consumption are proved.
- The public preview writes a mode-0600 signer artifact; activation accepts only
  an external `{manifest,envelope}` bundle and public key. Successful activation
  prints a minimal six-field receipt rather than the manifest/envelope. The
  focused wrapper-runtime suite passed 149 strict adjacent tests after this
  cleanup; independent QA separately passed 93 retained tests and 40 privacy
  follow-up tests.
- Next work is the default-disabled automatic supervision branch described in
  `AUTO_RETAINED_EVENT_SUPERVISION_DESIGN_20261119.md`. It must share durable
  ownership with normal intake, supervise the public retained child across
  restarts, and accept only exact consumption-receipt completion.
- Nothing is deployed or activated. The historical cycle and its 45 retained
  inventories, six plans, and two confirmed receipts remain untouched.
- Roadmap accounting remains 0 of 6 milestone gates closed and final
  independent acceptance 0%. The retained-route work item is 100% source/QA
  complete; automatic watcher supervision, protected installation, service
  deployment, live proof, and final milestone acceptance still follow.

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
