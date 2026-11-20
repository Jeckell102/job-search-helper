# Sprint 3 guarded source deployment and rollback design

**Preliminary verdict: adapt the proven Sprint 1 controller and guard, but
do not run the Sprint 1 scripts or receipt in place.** The controller's
service, admission and crash-recovery mechanics fit. Its transaction format
and verification assume that every source target exists on both sides.
Sprint 3 includes genuinely new modules. The old parking path also still
belongs to the successful Sprint 1 rollback record. Prepare a separately
named, independently tested Sprint 3 bundle with explicit absence handling.
Production remains held while the staged source is changing and until its
composed application QA and deployment rehearsal pass.

This is a read-only design. I did not run a production launcher, contact
the network, query or change a service, change source or state, or implement
an installer.

## Exact scope and observed live prerequisites

- Compare the final candidate with the existing dirty production source.
  The provisional delta is 17 runtime files, comprising 11 replacements
  and six additions. The table below records the observed paths, bytes
  and modes. The candidate was still in development when inspected.
  Re-freeze the exact candidate and run independent source QA before
  treating these hashes as install pins. Any changed author, path set,
  file state or code since review requires a new comparison.
- Keep the accompanying tests and evidence in the durable candidate and
  backup bundle. Do not copy the candidate tree, venv, tests, Git metadata,
  environment, signer material, policies, jobs, review data, or database
  files into the production checkout. Root `job-search-helper` was
  byte-identical to production and is outside scope.
- The production root `job-search-scraper` currently sends `start` and
  `sync` through the F3 bootstrap. The candidate adds exactly the
  `run-retained-operator-company` bootstrap branch. Its runner rejects a
  direct operator invocation without a matching inherited scraper
  descriptor and canonical SQLite layout. The bootstrap binds state and
  jobs path/device/inode and source/config/dependency measurements before
  executing the runner. The bootstrap source digest covers package files.
  The deployment manifest must independently bind the root shell file and
  bootstrap itself.
- The last independent Sprint 1 receipt is `RELEASED / INSTALLED`.
  The production canonical package remains inode `64513:28605656`.
  The preserved marker-only Sprint 1 parking directory remains
  `src/.f3-maintenance-package`, inode `64513:29265145`, and the canonical
  package had no extension initializer. The old controller's `new()`
  refuses an existing parking directory. Preserve the Sprint 1 bundle,
  receipt, backup payloads and marker directory as historical evidence.
- The inspected production install/scraper/publisher/review lock paths
  already exist. The production integration-release marker, retained
  operator journal, retained start journal and intake-dispatch database
  were absent. This establishes file presence at inspection, not safe
  host quiescence or absence of pending rows in other state authorities.
- The checkout and external maintenance root have the same device number
  but different mount IDs in this chat's execution namespace. The
  executing host must independently measure mount IDs. The Sprint 1
  installer stages a file in its transaction directory and renames it
  into the checkout. That can fail across mounts even on the same device.
  Use a verified same-mount capsule on the real host. If unavailable,
  stop and separately rehearse destination-local same-mount scratch
  with an externally durable journal. Never fall back to copy-and-delete.

## Minimal transaction changes

1. Copy the proven tools into a new private, durable Sprint 3 capsule.
   Use distinct controller and transaction schemas/IDs, a distinct service
   drop-in name, and a new parked package basename such as
   `src/.s3-maintenance-package`. Change the matching installer, gate and
   independent host-check paths together. Keep the backend-resolved
   `integration-release-journal.json` filename and recognized nonterminal
   state; give the marker the new maintenance ID. The stable pre-import
   bootstraps both consult that filename. Do not reuse the historical
   controller journal or old parked directory.
2. Replace the fixed 13-entry manifest with an independently pinned
   allowlist of exact paths in the two supported roots. For each path bind
   both endpoints as either `ABSENT` or explicit SHA-256, mode and owner.
   Bind the ordered manifest identity, disposition, destination inode
   identities, durable snapshot location, hold/verifier identity and
   intended owner for newly created files. Use no-follow readers and
   directory descriptors. Only ENOENT for an exact final component
   represents absence. A symlink, hardlink, directory, unreadable
   object or unexpected byte/mode/owner is a conflict. Preserve
   pre-existing owners and check any filesystem metadata the replacement
   primitive would otherwise discard. Bind the added-file owner to the
   intended checkout owner rather than inferring it from the source
   artifact's copy metadata.
3. Durably save exact before payloads for replacements and after payloads
   for all scoped files outside the package, syncing the files and
   containing directories before recording INSTALLING. No before file is
   synthesized for an absent entry. Revalidate production under the hold
   against the agreed base, including exactly six absent target names
   after the final scope is fixed. Capture the current non-scope package
   digest plus fingerprint of the protected source/config/dependency
   inputs outside it. Exclude only the known runtime cache paths and
   authenticated transient guard. Preserve unrelated existing edits and
   files, including the recent temporary-retry and Sprint 2 changes.
4. Retain the verified Sprint 1 convergence model. Under a durable phase,
   accept only each exact before or after endpoint. Replace an existing
   file with independently verified staged bytes and atomic rename.
   Create an absent target by exclusive atomic publication, e.g. Linux
   `renameat2(RENAME_NOREPLACE)` within the verified mount, with a
   fresh absence check. Set and verify approved mode and owner, and
   synchronize the affected directories. Verify exact postconditions.
   On replay an already correct destination is a no-op, followed by
   directory synchronization. Any third state keeps the hold. Never
   omit presence from the source fingerprint or treat a missing file
   generally as an accepted intermediate state.
5. Rollback uses the same controller and runtime hold. Restore only the
   replaced files from their captured before payloads. Remove an added
   path only if a no-follow final read verifies it is exactly the
   installed after version with the committed ownership. A recorded
   original absence already observed is a replay no-op. Sync each
   unlink, verify the full BEFORE manifest including absence, and purge
   bytecode for removed modules as well as modified ones. Do not delete
   other files or rebuild the package. Preserve the two durable
   transaction records and the source backups.
6. Reuse the proven guarded package publication sequence. Atomically
   exchange the canonical package for the marker, apply scoped changes
   to the original parked package, purge the scoped caches including
   audited external prefixes, and verify the target and non-scope
   fingerprints while parked. Publish with the authenticated empty
   extension initializer still blocking stock canonical imports. Do
   guarded canonical verification, persist ADMISSION_READY, then
   remove that exact guard inode and synchronize the directory. Only a
   complete verified source version is then importable. Verify the
   admitted state before removing the nonterminal marker and releasing
   service holds. Retain the existing crash/rollback replay logic around
   package exchange and guard unlink.

The ordinary application release manager does not cover this root shell
and bootstrap handoff. A whole-package shadow copy or wholesale Git
checkout would replace non-scope user work and change directory/file
identities. The parked-original transaction above preserves the strongest
parts of the installed Sprint 1 procedure.

## Runtime hold and independent preflight

The authorized real-host operator should confirm all of these before
source mutation. Current records and static configuration are evidence
for the plan, not evidence that a present hold is in effect.

1. Reserve the host maintenance window before the first mutation. Pause
   owned edits, installers and launches using either checkout that target
   the production tree, production databases or shared workbook. Hold
   identified scheduler/automation entries persistently and drain their
   running processes. The second checkout's default editable console
   can import production. Its own source has distinct SQLite state but
   can publish to the same workbook using a different lock. A process
   census cannot fence that writer. Verify user cron, timers, path/socket
   activations and unmanaged sessions with the host owner. The bridge
   that shares the interpreter has no source-package import in prior
   inspection; leave unrelated services alone if that remains true.
2. Record original wrapper and sync unit state and full effective unit/
   drop-in bytes. Use an outside-capsule persistent condition and durable
   sentinel for `wrapper-development-host.service` and
   `job-search-sync.service`. Verify effective conditions, then stop and
   drain both affected cgroups. Sync must start and end inactive and
   disabled, retaining its expiry drop-in. Restore the wrapper only if
   it was active before. Recheck the actual current wrapper build and
   dependencies after Sprint 2, including no dispatched or uncertain
   inference and no pending outcome delivery. Account for its immediate
   catch-up on restoration. Sprint 1 proved that catch-up could make an
   additive SQLite schema write, so compare the protected witness under
   the hold before restoration and independently again afterward.
3. Under the same project installer lock and the new capsule controller
   and transaction gates, acquire the existing SQLite app locks in
   order `scraper.lock`, `writer.lock`, `review-writeback.lock`. Bind
   stable descriptors/inodes. Audit retained publisher ownership
   separately. When the existing `retained-publication.lock` is
   present, confirm no owner and use it after `writer.lock` in any
   additional maintenance acquisition, consistent with the candidate
   publisher. Do not create or replace an absent lock as a probe. The
   first source write waits for the durable nonterminal release marker,
   persistent service closures and verified parked state. Recheck the
   host census after the gate closes to catch late and resident imports.
   Advisory locks and the import guard cover ordinary supported routes;
   an already-loaded interpreter, explicit file loader or alternate-first
   writer still depends on the maintenance-window closure.
4. Verify the effective backend and actual absolute state and jobs
   locations without printing secrets. Require existing co-located
   regular single-link SQLite files with unchanged device/inode, and
   the same scraper lock as each supported launcher. Verify the absence
   of a pre-existing integration release journal or stop for a separate
   owning-protocol resolution. Verify queue/campaign/autopilot/intake,
   retained intake, temporary retry and unqualified release controls
   remain held. Read-only inspect the exact pending Samtec request and
   matched receipt, historical cycle, state/inventory/job authority,
   current operator/start/session/publication evidence and unresolved
   claims. Do not proceed with an active or indeterminate retained
   transaction, whether or not a particular file name is absent.
5. Record protected witnesses for the canonical state, inventories,
   jobs and WALs; held request, receipt, historical evidence and
   ownership; release/intake/retained state; and relevant unit/config
   identities. Use stable read-only snapshots while writers are drained.
   Immutable SQLite reads require verified empty/settled WALs. Preserve
   the witnesses privately without copying credentials, signer private
   keys, job rows or database contents into a source bundle. This
   deployment must not start a provider call or construct any live
   Google client.
6. Verify the exact final application and install delta in a disposable
   version-matched checkout with the actual shell/stdio boundaries.
   Final composed QA must cover compact workbook identity, the exact
   signer and inherited operator lock, eligible-only/mixed/all-screened
   inventories, missing destination schema before provider/claim,
   lost write acknowledgement without replay, terminal request/archive
   recovery, and preservation of history and manual fields. The
   observed candidate review still reports open application issues.
   Separately crash the exact deployment/rollback operation before and
   after adding files, while removing new files on rollback, at exchange,
   before/after the import guard's removal, and before service release.
   Include same-scope base/foreign-file drift, recreated added name,
   even empty stale bytecode, original parked-path preservation and
   fault/reboot replay. Prove no fallback to a real scraper, publisher,
   provider or credentials in these tests.
7. The independent deployed verification for this source-only checkpoint
   measures the approved bytes, mode, owners, added-name set, non-scope
   fingerprint, runtime pin and protected witness. Check source routing
   and stock interpreter resolution with no application execute or
   state/network side effects. Exercise actual launcher dispatch and the
   new operator verb only against the disposable fixture until separate
   pilot authority. A later signer preview is itself a live read of the
   configured workbook and an authorization step. It must use the final
   installed pin and precisely selected public trust; any change in the
   measured source, config, dependency or effective trust invalidates
   the earlier approval. Do not set trust, run preview or prepare a
   request as part of this source deployment.

**Rollback boundary:** source-only rollback is valid while no Sprint 3
operator work is outstanding. Once a pilot has persisted an admission,
frozen inventory, local apply, uncertain remote claim or incomplete
consumption, the installed runtime pin and hold are part of its recovery
authority. An old version can ignore the new operator journal or cannot
satisfy its runtime pin. Keep the candidate and its exact state for
reviewed recovery, or separately authorize a lifecycle-aware recovery
plan. Never delete journals, revert databases, re-key claims under a
different runtime, or conflate a terminal source receipt with settled
job state.

## Provisional observed source manifest

Production absence below refers to the exact path, with neither a
regular file nor a symlink. Modes and hashes were read from the two
checkouts without executing their source.

| Path | Production mode and SHA-256 | Candidate mode and SHA-256 |
| --- | --- | --- |
| `job-search-scraper` | 0755 `cb8469304e44372e375baa6e33700be7326c2f237ce8e1b3e6980784c51435bf` | 0755 `a68fbe8d4531da53da1bba6570b27ccb752f5568d5e9b0312b966fb9700a78a4` |
| `release_admission_bootstrap.py` | 0664 `758509aad23c415e16d075f81776fa0348722e171655b51d9d281f3f8d148437` | 0664 `c508a85743d54f0840b4906d17bb6780c3c8daad2914d53f58a5006602e70862` |
| `src/job_search_helper/exact_cycle_planner.py` | 0664 `bd8b15fc75ef20759d421247cdaa849f3b08eab1443f226121665fc8d3634175` | 0664 `a33737c0ac67fa0dc1e25bce0427e3b523a892a0a1f52662f9196d955ab36cf3` |
| `src/job_search_helper/operator_company_request.py` | 0664 `c37092b2d61a5886d26cb97dd9b4bb3124dac4e656b7db4522477329e0120440` | 0664 `aa2ad170b8707489f532c2ac52d08a9cb421d7067b14244e40f7e58732e35f5b` |
| `src/job_search_helper/retained_company_event.py` | 0664 `23a63941f6fad00ec21376fbb2fd394573db9f8a4a12266ceb7a498781a714cf` | 0664 `cdfade3a00c00e2e71ae410454c123e09b8655935ce097d9fe36d0fe27945e27` |
| `src/job_search_helper/retained_first_pass.py` | 0664 `417c1a3765911cfe1d7250712737eef2d71cf78a3bfc545aeec799a03508c794` | 0664 `1751243d735a388fe0bddf1d03dd8aa8f15fae43c0144a9b89cc6223d37d6737` |
| `src/job_search_helper/retained_operator_authorization.py` | ABSENT | 0664 `bfe83db06ebcd4da2c6cd6320f65ab7127e0ef14f46276b60d74d91c4b2de395` |
| `src/job_search_helper/retained_operator_command.py` | ABSENT | 0664 `d2792f88767ee08ac86f048b8e36bd3126e8d02157032745879caeade628e8ae` |
| `src/job_search_helper/retained_operator_journal.py` | ABSENT | 0664 `de909d093b29ed7ed16fc86e18d31a9e1451c2a6a76469692fd258b2e93566db` |
| `src/job_search_helper/retained_operator_preflight.py` | ABSENT | 0664 `2f03e6592a94a3df6e31c6b08ea2950ec29a3b158cd3750c2dd1370018f15738` |
| `src/job_search_helper/retained_operator_run.py` | ABSENT | 0664 `0fb52e07515adff44c074c53f3c3891489d7e40ef49397a668491f90da8bcdcf` |
| `src/job_search_helper/retained_operator_scope.py` | ABSENT | 0664 `c868f04e3bf9044adc6b6bcbfa349c6dfff16acaa41969547f1fa0ee16744f4c` |
| `src/job_search_helper/retained_work_exception.py` | 0664 `6454a88349ddf3f4dce8ab853d8bf6577253301f36234a1394a4ac02eb5d7ee9` | 0664 `3f02d66fd1817164fcd813a715fad7af32562a970ba367366dbc1570bf10a078` |
| `src/job_search_helper/retained_work_orchestrator.py` | 0664 `78e663deb20cebdee69dd5a0fdcffcb60087f91117c91f7f786cdb0f9ce52ef5` | 0664 `e974d21985cd9f157cb9d77faf7cd0af6b51b7eede8c553a22cd27b8171b469b` |
| `src/job_search_helper/retained_work_publication.py` | 0664 `1b51b03e32a005a71ab5eeccb5411b6798eade07a8c330cef889b2e3f2ca8f46` | 0664 `829a9e17da1fc3a15a61ca4e5ffc287c5c7a652b8c3def042574a37ab1a322db` |
| `src/job_search_helper/retained_work_runner.py` | 0664 `f57cf819aaf4423fe25802d56151a07145aba070ea1601f3d68dd7f49b4d8785` | 0664 `82353933ccbf193171856159907caabe9786cf9fe9f139024c8a8f90311b6413` |
| `src/job_search_helper/runner.py` | 0664 `fed4267cb4c9afb55433f4d59a4f5691d4e49a45ed3011f55e7aad57faced7b3` | 0664 `726b70749c644a606f774bcb6b2b772291c6e84e9c324bbb2c8777ee16a61729` |

Measured 17 changed runtime paths in this pass.
