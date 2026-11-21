# Fresh Amphenol application release — next native dependency

**Proceed with the existing qualified installer and fresh one-shot; the exact native maintenance adapter is still a prerequisite.** The completed -05 builder update and real automatic build are accepted inputs. They do not authorize a candidate installation. This source-only check uses the 16:39 restart card, saved QA and named source files; no live state/process, provider, workbook, service or GitHub call was performed.

## Current input and exact release path

The saved [fresh build QA](/tmp/job-search-helper-integration-automation/temp/integration-coordinator/S5_AMPHENOL_FRESH_OUTCOME_BUILD_QA_20261121.md) supplies request `operator-amphenol-20261121-05`, request digest `f8c53183ae54bb8b66f79f92edc68d1e0a9d136ed8d2e21a07d7ff497fde7feb`, outcome `OUT-1dc536eeadea2d283052b05d`, task `WRAP-11dc97a3dd`, source revision `b7a94094c57cb879e25db5aef9de565437f8ec5a855ad7b1275958e944f6a501`, and one COMPLETED model receipt. Its automatic candidate is `895ec36e…`, patch `ce042dff…`, build receipt `aa12f5a8…`. Preserve the old spent task.

Current production **source** measurements agree with -05: host `a1cafe60d2025116bcaa43dd8dd1b4099a9c2845c35353f3f25dec98a8df5567`, Store `16c442d8019d5173f188348890fd89fe224d2c4315fde67528ed26e25478134d`. Operator host checks the canonical a95953 baseline before reading the choice and again before saving; it deliberately bypasses the stale task checkout ([host lines 477–522](/home/chris/job-search-helper_old/dev/wrapper-coder/tools/host_server.py:477)). No fresh provider or candidate validation was performed here.

The supported call sequence is:

1. `run_fresh_operator_release(approval=..., original_outcome=..., request_sha256=..., completed_task_id=..., maintenance_scope=window.hold, execute=True)`.
2. Exact fresh reader verifies current settled/acknowledged operator owner, REVIEW_COMPLETE_LIVE_NOT_VALIDATED task with stop_requested false, one completed choice, task source/patch/build receipt, canonical baseline, full candidate and independently pinned approval.
3. Existing `qualified_release_owner.release_and_continue_qualified` → `release_controller.release_and_schedule_qualified` → `integration_release.activate_release`; qualification and projected runtime are checked before writes and again under the scraper lease, with unfinished-work admission and installed verification.
4. Fresh installed `job-search-scraper continue-qualified-repair` performs the scoped retry, local application and exact remote publication. The one-shot then calls `deliver_qualified_operator_retry` and compares the exact attempt/outcome before returning OPERATOR_RELEASE_CONFIRMED.

[One-shot](/tmp/jsh-fresh-operator-candidate.p1Jipj/tools/amphenol_operator_one_shot.py:73) · [fresh reader](/tmp/jsh-fresh-operator-candidate.p1Jipj/tools/amphenol_candidate_release.py:122) · [installed qualified owner](/home/chris/job-search-helper_old/src/job_search_helper/qualified_release_owner.py:27) · [pre-install gate](/home/chris/job-search-helper_old/src/job_search_helper/release_controller.py:40).

**Do not call `OperatorQuietWindow.run()` for this task:** that convenience method still selects the historical retained-task route. Passing its accepted `hold` context directly to the fresh entry needs no new release architecture. Recheck the real task/current source after pilot withdrawal; a saved successful build report alone is not the reader's current authority.

## Minimum immutable preparation/approval inputs

| Input | Exact required binding |
|---|---|
| Full candidate and app manifest | Current measured production before vector/config/dependencies; only acquiretm.py proposed after image from the actual task; fresh failed_request_id and source revision; new canonical release ID; validation measurement for the expected installed runtime. Keep sparse build, full evaluator vector and metadata-based release vector distinct. |
| Independent qualification | Actual complete normal-dispatch evidence under unchanged listing/detail/cohort and first-429 criteria, bound to the fresh request/outcome/task, sole model receipt, three task artifacts, full candidate/manifest, evaluator/runtime and reviewed execution tools. No old PASS or public-only held result substituted. |
| Qualification owner | Private physical directory + device/inode; `REL-….manifest.json`, full `REL-….candidate`, and exact `REL-….json` receipt. Approval is the five-field RetryReleaseApproval: release_id, directory, device, inode, receipt_sha256. Receipt must say PASS/live_normal_dispatch/release_qualification=true, with exact manifest, candidate-validation, capture-manifest and reviewed-tools digests. |
| Fresh native window | New private mode-0700 window, exact release ID, original service/route observations, approved latest -03→-04→-05 lineage, source/tool/module pins, fresh exclusion policy and observer identity, durable restoration journal, precise quiet controls and no unresolved inference. Native execution must preserve the existing recovery branch if an application release is nonterminal. |

The seven staged modules still match their accepted scope. They are **not all deployed**: the installed Coordinator lacks existing_store_only and installed Store lacks existing_only. A one-path application manifest cannot install those tools. The native executor must either use the independently pinned private seven-tool composition with explicit verified import origins and existing production host/config roots, or separately stage and approve an exact tool deployment. Do not accidentally import the older installed Coordinator, alter the application manifest to hide tool changes, or assume the -05 builder installation included these tools. [Existing scope](/tmp/job-search-helper-integration-automation/temp/integration-coordinator/S5_AMPHENOL_FRESH_RELEASE_TOOL_SCOPE_STAGED_20261121.json).

## Native controller, observer and assistant bridge

The application installer is the existing **Python release_controller**, not a rerun of the historical maintenance Controller.install transaction. The historical [controller.py](/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03/controller.py:329) supplies the accepted Systemd fence and existing native guard patterns. Its UNITS contain only wrapper-development-host.service and job-search-sync.service. The [accepted quiet window](/tmp/jsh-fresh-operator-candidate.p1Jipj/tools/amphenol_operator_quiet_window.py:26) closes/verifies/restores those units, rejects mismatched State/Jobs/backend, keeps a nonterminal release fenced and re-fences failed restoration. Its outer admission/verify_exclusion/verify_restored callbacks were substituted in disposable QA; fresh native packaging of them is not yet accepted.

**Another fresh administrator observation is required under this existing proof contract.** The 16:39 card says the previous observer expired. The actual listener/route checker requires authenticated ancillary-process evidence when the normal account cannot read helper descriptors; it binds maintenance ID, checkout roots and listener ([host_checkpoint.py:175](/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03/site-source/host_checkpoint.py:175), [route drain:300](/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03/site-source/host_checkpoint.py:300)). An expired -05 socket or old observer receipt is not current exclusion. Prepare the exact new scope and entry first; the owner needs only the concrete bounded startup step when execution is ready.

**The assistant bridge needs different treatment from the -05 builder update.** The latter intentionally preserved its PID/start and only changed tools. The existing full native [run_retry_release.py](/tmp/jsh-operator-native-prep/run_retry_release.py:46) stops jetson-assistant-bridge.service before process/route drain and restores its original active/enabled posture in finally. QuietWindow does not do this. Its new native admission must reuse a properly journaled bridge exclusion/restoration or prove a separately accepted narrower exclusion; keeping the bridge alive merely because the tool updater did so is not the established application-release proof. No bridge stop or authorization request was made by this lane.

Two non-transferable guards:

- Old CurrentToolGuard only projects the -04 host over the -03 manifest. It does not represent the installed -05 host/Store pair. Preserve all old receipts and verify the actual -05 successor receipt and both current after images in a fresh bound guard.
- **Never retain historical Controller.restoration_terminal or CurrentToolGuard.terminal around the one-shot.** They hold the application scraper/writer locks (controller lines 472/494); the installer and fresh child must acquire those themselves. QuietWindow explicitly requires outer deployment/alternate-writer exclusion without retaining worker app locks across its yield. Otherwise the proposed composition conflicts with its own child admission.

The smallest next useful preparation, parallel with public qualification, is a private native executor/preflight for this exact fresh call: measured seven-tool imports, latest lineage, renewed observer scope, bridge and alternate-route exclusion, accepted quiet window and terminal restoration. Its first proving check should be default-off inspection plus one disposable fresh-call/restoration composition, including refusal before service changes without approval. Do not start another broad framework or regenerate the candidate.

## Rechecked source pins

| Staged tool | SHA-256 |
|---|---|
| amphenol_candidate_release.py | bf9ac48a86ee6e19290423899409f2603031e2ce3977247f05df21a4cd7d7c42 |
| amphenol_operator_one_shot.py | e00a40688045377d06a515004360ded7004fb336a99a6e5faa92ccca95a35638 |
| amphenol_operator_quiet_window.py | 8b124170b12897dcc37a82d6a5af5ed38538fee22d9194ddf4146c2565a2fdc4 |
| amphenol_operator_retained_release.py | df7e0aabcc961342aa18fed318ee957c6f679342a938d22dd4e8e51570e403b4 |
| amphenol_retry_completion.py | 1b598db426c24611adc5303a71c4f9d21fe4ddc5e2560459be7a78d1989abf67 |
| coordinator.py | db41607834c42a90f742d048c3df5a9e68ac8c9f75deb1414cc4d554c0d9caec |
| coordinator_store.py | 48e3f2ccee38b83f5577d2a66398074d58ab16b3f3c9afd5fda69e83af8e3d7b |

Installed qualified_release_owner: `5cf4e70829ad40d797dde4779cb6a1f0a75953f303ed330c0610ee7f0e5b23e6`; historical controller: `f63f9399f3fcdec3d3b46a6d5e14fc3d1d78e420234b357b0adf44bd68a53ff8`; historical host checkpoint: `fe5ac8bed3ab1e88ff645859ba6f156229694643d3b3549415748c8952016e43`; old native runner: `ccf7e1bb5c9d70d1fa956a1da859e98cc4fbd9d0ef9d364bb6b1429cf5ee759f`. These are reuse references, not fresh native authorization.

Only this private report was written. No target access or UI/display failure blocked the review.
