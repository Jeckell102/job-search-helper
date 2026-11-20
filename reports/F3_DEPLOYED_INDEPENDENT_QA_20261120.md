# F3 independent installed QA

**ACCEPT** the installed Sprint 1 source and operational state on MuleLab on November 20, 2026. The maintenance controller records `RELEASED / INSTALLED`. The initial protected-state byte comparison failed for `jobs.sqlite3`. The complete difference was reproduced byte for byte by replaying the installed repository's schema initialization on a verified pre-maintenance copy. All pre-existing rows are unchanged.

## Deployed source and receipt

The 13 installed paths match the accepted candidate and the installer's receipt in both mode and SHA-256. The before manifest is `7db9d0c151a5a0f3599b1d942d315604ab20284362d35c9a6ec32b17c98f5cd6` and the installed manifest is `a8341ba3eeca99a2e52e02a1372143340e7fd3eb84b678bd80b4b7267e79a847`. The non-scope package fingerprint matched the pre-maintenance record at `d3215afb511d0be2e5a86beabd84fd80f49866c964aec8d767e21cf8429ef393`.

The canonical package is the original directory, device and inode `64513:28605656`. The controller receipt equals the installer journal's terminal binding, with file owners independently checked. The controller record SHA-256 is `91be297c006601491109e5d9b0dad4de0e9efe336657766bd8e045d17d582377`. The installer journal SHA-256 is `ba4b045902ebaaff90251cb471c52bb5b1734d119956cf23f65f53f6f117887b`. The service sentinel, nonterminal release marker, staged extension and canonical import-blocking extension are absent. The inert marker-only directory remains parked at its bound inode for rollback.

| Mode | SHA-256 | Installed path |
|---|---|---|
| 0775 | `f692b6b6dbe57961402972190b61d8fc4d575f944f9be163c9ef9b2a6ed7c5bf` | `job-search-helper` |
| 0755 | `cb8469304e44372e375baa6e33700be7326c2f237ce8e1b3e6980784c51435bf` | `job-search-scraper` |
| 0664 | `758509aad23c415e16d075f81776fa0348722e171655b51d9d281f3f8d148437` | `release_admission_bootstrap.py` |
| 0644 | `a2ceca8ea944d81f7385ad3771924671c2f6024cfd6c700c56fde4ff53e63e7f` | `src/job_search_helper/cli.py` |
| 0644 | `faf5d9493dce9f1c6fdb569cffdf3481c2ea35a2e9c6091a04958b955be0e1b5` | `src/job_search_helper/engine.py` |
| 0664 | `033a4bc48035cac0e28cb129029e88da12e7102e782679e7af3098fb9432b7a1` | `src/job_search_helper/exact_cycle_recovery.py` |
| 0664 | `e100003bd7f04d1dc7109c1f07b44cf19d502ab25a3316f04bec9f8cb2d346ec` | `src/job_search_helper/inbox.py` |
| 0664 | `9ddd1e9c6908670415f6e4c7b61dbf5e16d0297e2f32213afeedbd37d77217ff` | `src/job_search_helper/integration_release.py` |
| 0664 | `b0b58f207e6291c07d98e225f58f248708f9f4e2b695f3eede2ea935ab88eda3` | `src/job_search_helper/launcher.py` |
| 0644 | `1b5029b85d4d54bb9239881b7ec7ce4c19b1c50ffb350ef2b0d197a0e2f16862` | `src/job_search_helper/local_pipeline.py` |
| 0664 | `fed4267cb4c9afb55433f4d59a4f5691d4e49a45ed3011f55e7aad57faced7b3` | `src/job_search_helper/runner.py` |
| 0664 | `0f9faa554199a52d1b3279df51dc0f89af3a0f03f84a4b1429554903f100ea26` | `src/job_search_helper/scrape_first_pass.py` |
| 0664 | `336f688967d463fda07f69ba5625cf7170749edbe55555dcd11b429b08fc5662` | `src/job_search_helper/sync_cli.py` |

## Installed runtime and controls

- Both root helpers and the installed editable console returned help. The copied console that resolves to production also returned help. Production resolver checks selected the canonical launcher, runner and sync modules and matched their pinned bytes. The standard-library bootstrap measured runtime state `NO_RELEASE`. Its runtime source, configuration and dependency SHA-256 values were `50f6c0f9a8db1a5ec86fc72b144240aaccbf9af6f3723752301a1ffa521ccddc`, `fdb4049997bddf85ec7f421283951ca2121cba2fab3be2e21082d32bc5eaaa03`, and `98079522053bb0643717e2afc5a2cf7890566729bd951a96e4d1a18487e3c7fb`, respectively. The digest probe rejected SQLite, network and child-process calls.
- The wrapper host was active and enabled. Its main PID was the sole kernel-recorded owner of both scheduler and supervision locks. Sync was inactive and disabled, with its original expiry drop-in and configuration. Unit bytes, file metadata and enablement matched the pre-maintenance record. The maintenance, scraper, writer and review locks were unheld at inspection.
- Queue, campaign, autopilot, company intake, retained intake and temporary retry were off. Active tasks, pending inference and pending wrapper deliveries were all zero. The exact held Samtec control and its `REQUEST_WRITTEN` receipt matched the witness. The retained historical cycle remains `In Progress` in the unchanged state database.

## Protected-state comparison and writer attribution

Ten of 11 witnessed paths matched in hashes or recorded absence. This includes the state and inventory databases, their WALs, the jobs WAL, the request and receipt, and the latest first-pass control. The one physical mismatch was a 16,384-byte increase in `jobs.sqlite3` from 1,665,511,424 to 1,665,527,808 bytes.

- Two pre-maintenance snapshots matched the original size and SHA-256. The row comparison matched all 898,061 rows in all 23 pre-existing tables by row ID, value and SQLite storage type. Every pre-existing schema object retained its definition and root page. My independent raw-page comparison found that only three of the 406,619 pre-existing pages changed, all belonging to `sqlite_schema`. The only four added pages are the empty roots of two outcome-delivery tables and their primary-key indexes.
- The restored wrapper host starts its supervision catch-up immediately. That code opens the jobs repository in write mode before checking the queue, invoking the pre-existing additive schema initialization. The host journal records the wrapper start at 10:33:41.140882 Eastern. The jobs database modification time was 10:33:41.471185 Eastern, about 330 ms later. Sync remained inactive. This supports high-confidence attribution to the wrapper's initial catch-up. No process-level SQL audit trace was available.
- I replayed the exact installed `SQLiteRepository._ensure_company_event_schema` on a disposable copy of the verified pre-image. The resulting size and SHA-256 matched the entire installed database byte for byte. This independently accounts for the full physical difference. The two new tables and the existing delivery table were empty.

## Disposable exact-installed-source tests

All 228 copied package files were verified against installed bytes. The release controller, integration release, bootstrap, launcher, source configuration snapshots and binding, exact-cycle sync and recovery, and local pipeline suites passed **171 tests** in 26.56 seconds. Module origin checks confirmed the bootstrap, launcher, runner, sync and recovery imports loaded from the disposable tree. That check also covered all loaded application modules after the test run.

The staged maintenance tools passed **41 tests** in 160.715 seconds using the exact installed source as the candidate. These include the gate, installer, controller and independent end-to-end suites. They exercised interruption before installer handoff, publication with canonical imports still held, guard unlink and admitted replay, guarded rollback, and non-scope preservation.

Production checks were read-only. Test writes were confined to disposable copies. This report contains no raw request, credentials or job records.
