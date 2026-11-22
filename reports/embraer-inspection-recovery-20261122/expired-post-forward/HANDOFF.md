# Original expired task withdrawal after coordinator forward

Staged only; root owns acceptance and authenticated native actions. Two offline tests passed in 0.05s. This new directory leaves the original armer, original pre-forward expiry capsule, accepted post-forward normal disarm and all deployed files unchanged.

`native_expired_post_forward.py` derives from accepted post-forward disarm eb5fe67a0b13f120109e1bf337cd409758664fa2c6963a9ff2bef26af0874003. The normal disarm terminal branch still calls the original armer without changed eligibility. The added default-off `--allow-original-expired` branch loads the previously reviewed expiry-only helper at exact pin 9819e9a54d7fea065a3dc8f34f78fe0582487bdecd088aee31cc650da4325de7 and uses the actual task unchanged.

Only task WRAP-fbb9ff24d3, original activation 1795373201.1956606, elapsed deadline 2026-11-22T19:46:41.195661+00:00, actual PAUSED/stop_requested=true/inspect and empty pilot slot qualify for the expiry branch. Root must obtain that state using the supported authenticated pause and pilot-stop actions after real expiry. This entry never issues either action or starts a task. It pins both original paired receipt hashes to d3964ed3d2f3d63adb17d0af72ce616a397a3c8e8a62676ed1711b15d5a24afb and all inference must be COMPLETED. Queue/campaign/autopilot remain off; all active tasks, unresolved inference and pending tool responses hold.

Both branches require the actual independently reviewed forward receipt 9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b. The unchanged verified_forward_receipt checks the current exact coordinator physical reference, installed hash, restart reference and original -12 application/route predecessor. The unchanged extended_window retains original source/custody checks using that one exact recorded tool transition. It does not change the active application release REL-2a5c7bb2ad922f73cf868d15. The current -13 authenticated observer and wrapper/bridge route proof remain required before and after restart.

Private invocation after independent acceptance and all prerequisites (not executed by this lane):

```sh
/home/chris/job-search-helper_old/.venv/bin/python -I -B -X pycache_prefix=/dev/null /tmp/jsh-embraer-owned-pilot.xXaXrqW0/inspection-recovery/expired-post-forward/native_expired_post_forward.py inspect --request-id operator-embraer-20261122-01 --request-sha256 19e7af99bd90d243f9b9f7465d5b6c38455ef99208cade05b7e1cfe5ca7536d2 --entry-sha256 ff6aa8e3d59138c256962cbcddd3f2e70fac693534f57bff1d0ae3547453cce5 --forward-receipt-sha256 9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b --allow-original-expired
```

Use `disarm` with otherwise identical exact arguments after accepted inspect. Omitting `--allow-original-expired` retains normal existing terminal eligibility and does not admit PAUSED. There is no apply, resume, arm, successor dispatch, source installation or task-state write. The only permitted changes reuse original paired owner-disarm receipt recording, exact manager enrollment removal and targeted wrapper restart when needed. A lost restart response replays the saved owner/environment state; a truly inactive wrapper holds under the inherited active-wrapper requirement.

Fixture scope: real unchanged armer/expiry/environment libraries and a real disposable physical coordinator file; native process/systemd boundary remains substituted. Exactly two new tests: accepted expiry/restart-response-loss replay plus negative deadline/task/state/receipts/control checks through reused focused fixture, and current forward receipt physical/hash/reference refusal. AST comparison confirms inherited controls, process_scope and verified_forward_receipt are unchanged. No external connection or subprocess was allowed by the offline test audit hook. No provider, Google, model, production state or service was accessed by this lane.

Exact files/pins are in RESULT.json.
