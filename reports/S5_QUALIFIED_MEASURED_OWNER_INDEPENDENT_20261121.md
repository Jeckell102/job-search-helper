# Independent source and focused QA: measured qualified-release owner

2026-11-21. **ACCEPT for this measured owner/launcher source seam.** No concrete must-fix finding. Candidate `/tmp/jsh-s5-release-controller-join.20261121`; independent private evidence `/tmp/jsh-s5-measured-owner-independent.ah7v0cjb`.

## Verified behavior

- The shell launcher routes `continue-qualified-repair` to the unchanged standard-library bootstrap with `-I -S`. `release_admission_bootstrap.py:236` loads configuration, obtains the ordinary scraper lock, measures installed source/config/dependency trees against the settled release, and only then executes the application module. The fresh worker receives that actual descriptor plus the runtime binding. `runner.py:66` proves the descriptor names and owns the same lock and remeasures the runtime before yielding admission. The new worker requires inherited admission; direct entry without it fails before creating application state.
- `qualified_release_owner.py:29` uses the independently supplied owner directory descriptor, inode/device and receipt digest. It invokes the existing qualified activation API, then passes that same approval descriptor with `pass_fds` to the fresh installed launcher. The runner opens and verifies the owner, exact durable retry intent, manifest and completed release receipt before opening writable stores (`runner.py:804–857`). Approval and scraper descriptors cease being inheritable once consumed. The proposal itself cannot replace the owner pin.
- The new optional `preinstall_guard` preserves existing callers. In this owner path it is supplied as `_require_idle_installation`. `integration_release.py:319–356` invokes it while holding the scraper lease, after source/qualification validation and before `_prepare_record`, journal creation or source replacement. The guard takes the writer lease, rejects retained lifecycle ownership, and checks both saved State and the local Jobs Scan Cycles mirror through the existing unfinished-cycle rules. Either surface being unfinished rejects installation without modifying those records. A same already-completed release may replay without replacing files; the installer independently checks its receipt and installed source before that no-replacement path.
- The measured runner constructs a local Engine only after admission/qualification and calls the existing admitted controller seam under the same inherited scraper lease. That seam owns its writer lease and exact Company/attempt scope. The remote repository remains a factory: no remote creation for waiting or held work, and destination mismatch is rejected before the factory opens the workbook. The controller also verifies the produced remote's workbook identity before exact publication.
- The worker closes local completion after exiting its earlier scraper admission, using the accepted independently locking closeout seam while qualification ownership remains alive. The owner expects exactly one terminal/held report. A COMPLETE report must contain a COMPLETE outcome with the same attempt, release, failed request, Company and source revision as the scheduled release; a foreign attempt is rejected. This is an exact one-attempt result, not a backlog drain or a new scheduler.

## Independent focused execution

**15 passed in 2.51 seconds**, preserved in `focused-results.txt`:

- Six owner cases: exact dispatch/descriptor arguments, stale Company prevents worker spawn, foreign attempt rejection, unfinished State rejection, unfinished Jobs mirror rejection, idle acceptance.
- Six launcher cases: direct entry requires inherited admission; measured waiting/complete routing; wrong owner pin; missing durable intent; wrong workbook. These use the real bootstrap and lease logic with exec/remote/controller observation substitutions, so they do not constitute an actual subprocess/install proof.
- Three independent integration cases reused the previously reviewed private captured Amphenol data and real State/Jobs/Inbox with fixture workbook: normal 39-posting capture replay became 18 unique filtered/published jobs, one batch, one confirmed receipt and one COMPLETE outcome; replay had no refetch, second remote creation or write and preserved unrelated records. Missing intent made no stage effects. An actual Engine-created saved partial inventory stayed held and unchanged.

System Python 3.11 ran in isolated private cwd with explicit copied source/test paths, bytecode disabled, pytest plugin autoload disabled, and a network audit denial. Only the system pytest dependency's known `py.__spec__` compatibility assignment lives in the private runner. No application/test source edits occurred in the candidate, and this lane did not modify any production checkout, database, service, queue, credentials or provider state. Raw captured public inventory and SQLite files remain private.

## Evidence separation

This report accepts the exact source and focused application contract. The other independent lane owns actual subprocess plus disposable install proof; it must not be inferred from these substituted launcher tests. Native deployment, fresh employer/provider validation and live synchronization remain separate gates. Historical protected Saronic/retained work was neither opened nor changed. No acceptance criteria were relaxed.

## Final pins

All listed candidate source/test files were rehashed after tests and matched the root-owned candidate. `EVIDENCE_PINS.json` contains the complete mapping.

| Artifact | SHA-256 |
| --- | --- |
| `src/job_search_helper/release_controller.py` | `2cd45aff4d52d3808c41b1bbd36e0c1a3a257634b2df79221185345742adff8c` |
| `src/job_search_helper/qualified_release_owner.py` | `607a08c3d3e4728e411b95cfa9e4bd54a8dbcb767560ff077351e7bc268ebec9` |
| `src/job_search_helper/runner.py` | `f1ade3af7fd4c50baf55078f8c158a8ecd66773f2d8c725ab9dfc4aaa65e26b3` |
| `job-search-scraper` | `2556de3371c32be1991273a1ee88d2baa25753dfcdc73a9656d34de6b91de78c` |
| `release_admission_bootstrap.py` | `c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f` |
| `tests/test_qualified_release_owner.py` | `bf14a7c0ffcf85ba8aed20273ea4cf40be9ce14c0c02225004551aaa296fb937` |
| `tests/test_qualified_retry_launcher.py` | `4c4ab47b6da47627a46b4f8162097e295fba3d01534cb22da7341813d7ee3a6b` |
| `test_composed_continuation.py` | `4034e63cbd9b6d74a3c4ee0ca68c9d8f6ceb233a16671e3ccb28d979389ef0bf` |
| `run_tests.py` | `55742fcaafa9e3587afe4c416a4dbc29ed70aa8f752fba83285f71cbab6124b3` |
| `focused-results.txt` | `4a5b613d83419ac589ef247f7dcb6714bdd66c0286013a8aa0a80477e3fc3e32` |
| `COMPOSED_RESULT.json` | `9246c27045261eafc476c635bd8203911ba21aef20968f7bc03e82f6d3b03a7d` |
