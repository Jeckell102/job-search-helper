# Protected MuleLab integration report — 2026-11-19

This report records the owner-reviewed installation of the independently
accepted M1-M6 source candidates. It contains no credentials, job records,
Google Sheet contents, prompts, or private runtime payloads.

## Scope and rollback

- Protected checkout: `/home/chris/job-search-helper_old`.
- Coordinator tools: `/home/chris/job-search-helper_old/dev/wrapper-coder/tools`.
- Exact pre-install copies of every replaced file are retained at
  `/tmp/job-search-helper-protected-backup-20261119-OT8k9K`.
- Each backup was compared byte-for-byte with its target before installation.
  Files absent before installation are separately identifiable as new files.
- Installation held the existing `.integration-install.lock`; no lock was
  deleted. No database, cycle, receipt, job, prompt, credential, or runtime
  history was copied or replaced.
- The source reconciliation worktree was created after the protected target
  files' last modification times. A checksum comparison after installation
  showed the installed application source exactly matched the reviewed
  reconciliation source. The installed coordinator source exactly matched the
  reviewed feature source, plus the recorded compatibility updates below.

## Installed compatibility corrections

The protected coordinator contained additional production-owned tests that
were not present in the sanitized feature copy. Installed verification found
and corrected three obsolete fixture assumptions without weakening behavior:

- Retained the prior `supervise(...)` health entry point as a compatibility
  wrapper while the actual host uses the accepted planned-shutdown watchdog.
- Updated the ownership test stub to accept the current recovery callback.
- Updated local publication tests for the receipt keyword, intentional stable
  reread, and the separation between scraper CLI forwarding and the public
  `main(start ...)` FIRST PASS preflight.

The read-only `supervision-status` command was added to the existing local
operator CLI, with parser coverage.

## Installed verification

- Full protected coordinator suite: **434/434 passed** with resource warnings
  treated as errors.
- Current protected integration selection covering durable Company events,
  request admission, outcomes, release, retry, publication, restart,
  synchronization, SQLite migration, runner behavior and local pipeline:
  **202/202 passed** with resource warnings treated as errors.
- No real scraper run, Google authentication, Google Sheets read/write, or
  managed FIRST PASS was started by these tests.

## Service proof

The actual service name is `wrapper-development-host.service`; an initial
check against older guessed names incorrectly reported inactive. The real
service was then identified before restart. Its queue was already paused,
campaign mode was off, and no task was active.

- Controlled restart loaded the accepted installed source.
- Host and existing tunnel returned healthy; the queue remained paused.
- Startup catch-up returned `ok=true`, `remaining=0`, with no delivered replay.
- Supervision reported `ACTIVE`, healthy disk space, no recovery required,
  automatic cleanup disabled, and all external retention categories visible.
- A controlled SIGTERM stop persisted `SHUTDOWN_PAUSED` with
  `recovery_required=false` before process exit. No active boundary needed
  pausing.
- The subsequent start returned to `ACTIVE`; catch-up again found no missing
  work and the queue remained paused.
- The installed disk-pressure simulation retained an active task row, action
  receipt, uncertain inference receipt, and unacknowledged scrape outcome
  byte-for-byte; it disabled the queue, reported exact protected counts, and
  performed no cleanup. The separate ownership check admitted only one
  supervision owner.
- A live-service exercise temporarily raised only the supervised free-space
  threshold; it did not fill the disk or remove data. After restart the host
  entered `DISK_PRESSURE_HOLD`, both host and tunnel remained active, the
  queue remained paused, automatic cleanup remained disabled, and the exact
  runtime retention counts stayed at 114 tasks, 214 action receipts and 21
  inference receipts with every external protected category still visible.
  The temporary override was then removed. A second restart returned the host
  to `ACTIVE` with catch-up `ok=true`, `remaining=0`, unchanged retention
  counts, both services active, and no supervision override left behind.
- Runtime retention snapshot: 114 task records, 214 action receipts and 21
  inference receipts retained; no pending external event, outcome,
  publication, or release record was discarded.
- Automatic repair profiles remain empty. All unmatched or unqualified source
  families are honestly routed to engineering review.

## Principal installed hashes

```text
7eb59e5b6b2ec229da7a6a8c4aa4b52c0569f05bc427f793d7502dc4d2451ea4  src/job_search_helper/company_events.py
2b7c39ec0a117e9f1d71ce13858e9bcad0af8c9d61ca54a5604e5f76b5d01f0c  src/job_search_helper/engine.py
482895c72900ddcdfda1089090a6277af494bea7941b1f1289ac8f2ae5cb23cd  src/job_search_helper/inbox.py
1a15c158f699193e675c429f1e8e96e5b43ad83040e7e161ccb45d06773ad4d8  src/job_search_helper/integration_release.py
6f47c8f6a88908e8843c50a5e5639300e4b862a415a7fc72000d391cd54da4f8  src/job_search_helper/local_pipeline.py
f8824da599f27646421b9c480da920f706ca1653507fd65b82d6ff49aea0e939  src/job_search_helper/outcomes.py
68b029585948b9dcf99c6277f2fe5334eed38642f5679e072fd5375d93384ff2  src/job_search_helper/publication_receipts.py
cb916ba55634051420f0998ab6dcc76455fb184e4f6901c8074ccf29eee0031d  src/job_search_helper/release_controller.py
c6169e17fce73706f3d697c933d3dfb17900fb455a1e00df364c0416eea3d1b2  src/job_search_helper/repair_retry.py
178600cf76b5ba223780e563b37d05aa3e902c059890efc43776df99485d74fa  src/job_search_helper/runner.py
f47e0746e4f5528611b55af6e54080cfb5b4b77608984ce4dad54d26b3669c30  src/job_search_helper/scan_request.py
6f9d38029c23d32062f11efe448c948f38ff2bb6f9deed6cd4f2e8164bf0e393  src/job_search_helper/scrape_outcome_producer.py
27b136135be61c185ea5d33a6c9830ff106d7e859aee9a3ec3ce5992bc889713  src/job_search_helper/sqlite_repository.py
bc276d79b23c7b39b983656a0b6b50b3a13ee1d1396c6462049e1ed7e9801664  tools/coordinator.py
63f9f9b65b410bdc2019f33b7ccf4a48ad4ccc7369668bddf8d794d34e6cf337  tools/coordinator_inference.py
a16eb6931aa566c3c592dfa7e9492f082cfcdf16b88017369f3b8aa93e2d83a5  tools/coordinator_repair_profiles.py
3c2f930997198b750bdf2d529231e78583b9b6f18a19de7fff6b89616dd8a970  tools/coordinator_store.py
5a6a943a16c9bc7bb2b32fe0c4cea325abf2aace2bb4ead42547dac6454d56f3  tools/coordinator_supervision.py
ebb7f0904991642ac54615d3c0aacba6f9499ade4f16e4e48966829a857e8ce7  tools/host_server.py
2719bcc4553440414101edda1f67499545db36f2cb34f5a11d73a3ad1a198758  tools/inference_control_store.py
a4e61105917dea6fb963f4a1a81e3b0745f863c529aa0a0affabd32b9ab0d1c7  tools/wrapper_task.py
```

## Open gates

- Independent QA accepted the final threshold control and independently
  confirmed the installed hash, absent temporary override, both active
  services, `ACTIVE` recovery state, zero unfinished catch-up, paused
  admission, zero running work/open action receipts, unchanged 114/214/21
  retention counts, visible external categories, and disabled cleanup.
- Administrator-authenticated Jetson F4 interruption proof and independent
  receipt/service verification.
- Final sequential demonstration with three unfinished Companies having
  distinct source structures, shared-adapter regression coverage, confirmed
  Google Sheets publication, and managed FIRST PASS start.
