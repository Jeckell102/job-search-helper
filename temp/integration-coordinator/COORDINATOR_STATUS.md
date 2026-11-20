# Current protected-source reconciliation coordinator status

## Active checkpoint — 2026-11-19 activation ready; explicit approval required

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
- The default-disabled automatic retained supervision branch is independently
  **ACCEPTED**. It shares one durable owner with normal intake, invokes only the
  public retained command with public-key configuration inherited from the
  environment, and accepts only the exact terminal consumption receipt.
- Crash recovery persists a pre-spawn owner token and can adopt only the exact
  same-user live wrapper child using token, argv, interpreter, CWD, PYTHONPATH,
  PID, and Linux start identity. It rejects look-alike and zombie processes;
  a missing/dead child starts the idempotent public recovery path exactly once.
  Root's strict adjacent suite passed 160 tests and independent QA passed 87.
- The exact accepted ten-file source/test delta is now installed in the
  protected MuleLab checkout. All starting bytes matched the sanitized baseline,
  rollback copies are at
  `/tmp/job-search-helper-protected-backup-20261119-e4e19ef`, all installed bytes
  match checkpoint `e4e19ef`, and 160 strict protected-runtime tests passed.
  Both intake gates remain disabled; no service, Google, live-state, lock,
  credential, raw-job, or Jetson change was made.
- The follow-up operator-request crash-recovery patch is also installed from
  accepted checkpoint `4522d77`, with rollback copies at
  `/tmp/job-search-helper-protected-backup-operator-4522d77`. It binds both
  operator and Company-event source receipts to frozen admission evidence;
  111 strict protected-runtime tests passed after installation.
- Next work is service/runtime configuration plus a guarded live proof. Before
  enabling either gate, reconcile the signed exception approval, exact current
  historical blocker evidence, environment-only public-key configuration, and
  live Google authentication/readback.
- That reconciliation is complete: independent signer ACCEPT, exact evidence
  digests match, expiry is 2026-11-22T12:00Z, and the approval is local-only
  with historical settlement/publication forbidden. The safety approval layer
  nevertheless requires a fresh explicit user confirmation because the signed
  exception is tied to an unfinished 800-company cycle. Its rejected activation
  attempt made no state change. Both gates and the service remain off.
- A later one-word user reply, `approved`, was not accepted by the host safety
  layer as the exact blast-radius acknowledgement. The second rejected attempt
  also made no state change. Do not retry or route around the safety layer until
  the user supplies the complete confirmation recorded in
  `LIVE_ACTIVATION_READY_20261119.md`.
- A stopped/disabled watcher release package is prepared under
  `service-release-20261119/`. After three fail-closed QA repair rounds, its
  sandboxed install/rollback model is independently **ACCEPTED for the offline
  package only**. It targets the exact per-user service, journals ownership
  before every write, recovers every tested interruption window, refuses
  foreign drift/owners, binds captured bytes and durable gates, and preserves
  the old expiry bytes/mode/owner. The package remains uninstalled; fresh host
  preflight, guarded installation, and post-install validation are separate
  gates, and the service remains stopped/disabled.
- Offline F1 external-Sheets reconciliation is independently **ACCEPTED at the
  source/test level** after four fail-closed QA repair rounds. The first
  snapshot is frozen before merge, catch-up detects intervening changes,
  historical ID-less eligible rows halt before mutation, excluded history
  cannot create outbox work, and corrupt/duplicate durable watermarks reject
  before seeding. Root passed 140 adjacent checks and independent QA passed
  107 focused checks plus direct corruption reproduction. F1 remains open for
  installed live Google proof across idle and busy runtime paths.
- The accepted sanitized service-release checkpoint is commit `a940524` and
  is byte-for-byte verified on GitHub branch
  `backup/integration-automation-current-20261119` at
  `a940524d1104aa4bd73537154491dfbb5c039df0`.
- A later staging audit found that the package template/verifier still named a
  generated `30-release-expiry.conf` although the accepted installer replaces
  `expiry.conf`. The package now uses exactly one `expiry.conf` artifact from
  template through rollback, and both verifier and installer reject any extra
  staged file before receipt creation or mutation. Independent offline QA
  **ACCEPTED** the correction; details are in
  `SERVICE_RELEASE_NAMING_QA_20261120.md`. No host/live state changed.
- The corrected package has now produced a real, non-installed temporary stage
  containing exactly the watcher drop-in, `expiry.conf`, and owner-only public
  verifier environment. Independent QA **ACCEPTED** the generated stage, fresh
  stopped/disabled read-only host evidence, and a complete install/rollback
  rehearsal inside a disposable sandbox. The real host create targets remain
  absent, the old expiry target is unchanged, and both intake controls remain
  false. See `SERVICE_GENERATED_STAGE_QA_20261120.md`.
- Milestone 3 now has an independently **ACCEPTED boundary audit** in
  `M3_BOUNDARY_AUDIT_20261120.md`. It confirms the existing conservative
  outcome/held-repair skeleton but does not claim M3 closure. The smallest
  safe next slice is an ordinary normal-cycle facts adapter; post-storage M3
  may suppress stale repair/retry/coordinator delivery, while no-stale job
  writes remain owned and tested at pre-persistence admission. Company-only
  producer integration is deliberately deferred to its explicit call site.
- The accepted F1 source/test checkpoint `720c84e` is installed narrowly in the
  protected MuleLab checkout. All four starting hashes matched `a940524`,
  rollback copies are at
  `/tmp/job-search-helper-protected-backup-f1-720c84e`, installed hashes match
  `720c84e`, and 140 protected-runtime adjacent tests passed. No service, gate,
  Google, database, request, cycle, receipt, credential, lock, Jetson, or raw
  job state changed. The scoped GitHub backup is verified at
  `720c84ecee1a325ab4f368d1f22882dd22c92e3b`.
- A compact read-only live storage check found zero pending publication cells,
  zero pending publication rows, no last sync error, and zero pending Company
  events for the scan-request bridge. One pre-existing storage conflict remains;
  no state was changed while checking it.
- Nothing is deployed or activated. The historical cycle and its 45 retained
  inventories, six plans, and two confirmed receipts remain untouched.
- Roadmap accounting remains 0 of 6 milestone gates closed and final
  independent acceptance 0%. The retained-route work item is 100% source/QA
  complete, automatic watcher supervision is 100% source/QA complete, and the
  protected source installation is 100% complete. Service deployment, guarded
  live proof, and final milestone acceptance still follow.

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
