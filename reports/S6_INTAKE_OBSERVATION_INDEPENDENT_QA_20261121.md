# S6 independent Company intake observation

**ACCEPT for the staged observe-only command.** Three separate processes used the actual `./job-search-scraper storage intake-observe` shell and a private virtual environment. The first proposed only the latest eligible Company event. An eligible-looking outbox event whose current Company changed was `HELD_STALE_SOURCE`. The latest withdrawal was `HELD_WITHDRAWN`. Earlier revisions of the active and withdrawn Companies were excluded from the report and from proposed work. [Initial output](/tmp/jsh-s6-intake-observe-independent.yB38eD5M/shell-observe-kxuzej10/CHECKPOINTED.stdout)

A normal SQLite writer committed a newer active revision only to a 53,592-byte Jobs WAL. The Jobs main file digest remained equal to its pre-commit digest. Observation exited 1 with `STATUS_SNAPSHOT_BUSY` and no events. After the writer closed and SQLite checkpointed, observation proposed exactly the newly committed revision and continued to hold the other Companies. [Busy output](/tmp/jsh-s6-intake-observe-independent.yB38eD5M/shell-observe-kxuzej10/COMMITTED_WAL.stdout) · [Post-checkpoint output](/tmp/jsh-s6-intake-observe-independent.yB38eD5M/shell-observe-kxuzej10/AFTER_CHECKPOINT.stdout)

Every child status call preserved the full private State, Jobs and Inbox directory manifest, including device, inode, mode, size, mtime, ctime and file SHA-256. That comparison includes existing SQLite support files in the nonempty WAL case. The idle calls created none. No queue, scraper lease or bridge evidence path appeared. The fixture confirmed each child loaded a guard that rejected network and watched lease, admission, delivery, acknowledgement, provider-fetch and workbook-publication calls. All stderr captures were empty. Python bytecode generation was disabled to isolate the application's filesystem effects. Fixtures were offline and disposable. [Independent harness](/tmp/jsh-s6-intake-observe-independent.yB38eD5M/prove_intake_observe.py:126)

The observed command uses the existing `storage` dispatch. Source review confirmed that `sync` remains on its existing bootstrap and lease path and the new command returns before the normal storage writer, intake bridge or remote factory. Its immutable Jobs read uses the accepted before-and-after checkpoint verification. The reported proposal is advisory. Actual admission remains subject to queue and workflow checks. [Exact CLI branch](/tmp/jsh-s6-intake-observe.20261121/src/job_search_helper/sync_cli.py:104) · [Exact observation method](/tmp/jsh-s6-intake-observe.20261121/src/job_search_helper/company_events.py:617)

Rerun with `/usr/bin/python3.11 -B /tmp/jsh-s6-intake-observe-independent.yB38eD5M/prove_intake_observe.py`.

| Artifact | SHA-256 |
| --- | --- |
| company_events.py | `0c82c1091b413622f0fc4a727225efcd3792598e527d0731e78d3d427b5d265b` |
| sync_cli.py | `4c94908e60638a49cf066e550829c9241d10a8c78d7583a6d7b8e8f0caffe529` |
| test_company_intake_observe.py | `ae876c2a0562eda8ccecbd85cba7daea462917c191b6adf767ef7241b7c92927` |
| repair_retry_status.py | `ef5e8d51490e073de119fca876e5cc85ffb6418961f3daf97b36191e041b5290` |
| sqlite_repository.py | `3ab772748e685a131f885c0eefa7bd8055ed5c22114d4f89204a6dce3d8ff742` |
| job-search-scraper | `2556de3371c32be1991273a1ee88d2baa25753dfcdc73a9656d34de6b91de78c` |
| release_admission_bootstrap.py | `c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f` |
| Independent harness | `cfed5934b1b78bb0bb4037d9002bcdf9b3221099cb7c24cf3d90ceb4b9ecdd60` |
| Independent result | `f1767cff5147f22016c7e0cafb421bfcb34b0bd6f91c2d698683596025cd129b` |
