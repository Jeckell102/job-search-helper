# Independent six-tool source-scope verification

**REJECT the exact scope metadata as written; one narrow correction is required.** This is a source/package verdict only. It neither qualifies the live candidate nor authorizes native execution.

Reviewed `/tmp/jsh-amphenol-native-source-scope.r0nuir0k/STAGED_SOURCE_SCOPE.json` at SHA-256 `4a89449a876971dd8321ae7aae75e4eac88f74a4d403d8f46d6432b3366c8dca`. Of 38 comparisons, 37 matched. The only discrepancy is the `existing_maintenance_source_refs.controller.py.mode`: the document says `0664`; the current approved native predecessor `/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03/controller.py` is `0700`. Its size 68543 and content SHA `f63f9399f3fcdec3d3b46a6d5e14fc3d1d78e420234b357b0adf44bd68a53ff8` match. The package must correct that reference, or identify a different intended physical source explicitly; no native file needs changing.

All six staged files are ordinary, single-link physical files, with exactly the declared names, sizes, modes and accepted content hashes. Current production before-images match, including absence of the three new modules. Current host reference, existing native installer and gate match. Accepted pins are supported by the saved independent one-shot, quiet-window, activation-cut and terminal-completion reviews.

| Tool | Accepted SHA-256 |
| --- | --- |
| amphenol_operator_one_shot.py | 8af5c70848baec3b8da53df209ff260aaeff3940b4d48c4c3a4552440e5432c6 |
| amphenol_operator_quiet_window.py | 8b124170b12897dcc37a82d6a5af5ed38538fee22d9194ddf4146c2565a2fdc4 |
| amphenol_operator_retained_release.py | df7e0aabcc961342aa18fed318ee957c6f679342a938d22dd4e8e51570e403b4 |
| amphenol_retry_completion.py | 1b598db426c24611adc5303a71c4f9d21fe4ddc5e2560459be7a78d1989abf67 |
| coordinator.py | db41607834c42a90f742d048c3df5a9e68ac8c9f75deb1414cc4d554c0d9caec |
| coordinator_store.py | 4b09a063fd657be2f4febaddaa23f2d283987e18604f6a8d20d97b0910d423b2 |

The application proposal remains exactly `REL-af662a11bf656819d418120a`, canonical manifest SHA `fe5b0654bfe17f349d73162588a50e489d43427f5cbe55f7755dfe25b7bc8350`. It changes only `src/job_search_helper/acquiretm.py`, from `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61` to `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`; both mode and size match. A fresh independent file-only reconstruction of all 252 runtime source members on each side matches the before `aae173eaf94a553d51cd280a5e9ba7915bffdb7244f3b5a5ab8b9cfa87922813` and proposed `7269a0b5f2cb593f5a5b44b70d62b58646d7a902a7e2b81969d7031e57fc98f4` vectors, with no other application source difference.

Scope remains `STAGED_SOURCE_SCOPE_HELD`; installation, live qualification receipt provisioning, and alternate-process/current-native-authority enrollment are all explicitly false. The one-shot defaults to held without explicit execution and requires a supplied approval plus maintenance scope. The quiet-window adapter requires independent admission/exclusion/restoration callbacks and its accepted code supplies no fresh native approval by itself. Existing accepted fixture evidence does not replace these missing native inputs. The six wrapper files are a separate maintenance scope, not hidden additions to the one-connector application manifest.

No candidate code was imported or executed. This check read only named tool/maintenance source, held proposal metadata and application source-tree files. It did not read credentials, configuration contents, native databases, job/workbook data, processes or services, and made no external requests. No tests or provider checks were rerun. Only this private report directory was written.

Machine evidence: `RESULT.json`, SHA-256 `e719e225a0dd228a4da59cb68a2898984989f36ee52e05e54b226389c591134a`.
