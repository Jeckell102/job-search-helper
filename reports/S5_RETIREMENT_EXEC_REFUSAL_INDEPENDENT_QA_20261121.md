# Independent exec-refusal recovery review

Read-only source and private artifact metadata review. No production database, services, lock acquisition, observer, route change or recovery command executed by this lane.

Initial script 5c43c828b1750942c6bd3e1ba4915059e15329c0178ea58994b5b81f4f0a1aa0: HOLD. The directly imported top-level host_exchange.py was not in TOOL_PINS. Required exact accepted SHA 8168d900979d68aebc950d7bb8495705a5190368e8ca3ac932a7da4d4c7dfb1f. This is the component that performs route exchanges and was not otherwise included in Controller's original tool file binding.

Second script a1cde6663d4c8f3d4aafc30ef52c1e5c38b73dff637f00a10e42c906df3e4860: fixed the HostExchange pin and rejects unexpected top-level Python members. One exact original helper parity check remains: recheck `abort.attempt_identity(log) == original['attempt']` at each check_log call, before and after protected readback, not only when entering attempt_custody. The original preinstall_abort.original_source does this at its proof boundary.

The proposed narrow recovery otherwise matches the established contract: exact original enrollment and canonical launch transcript, no execute bits on the enrolled controller, exactly launch.json plus empty stdout/stderr and original attempt.lock, no controller/transaction effects, all original release and attempt leases, full original source and protected witness, exact closed exchange, separately approved canonical observation, existing HostExchange.restore callback and terminal replay. It preserves the failed transcript and does not fabricate process, exit, refusal or installer receipts.

Observed metadata: controller hash 83eb3246bdf0d5818e322ed85fb6fd73c6f2cd0138b62ad23585d73ba0b7d708, mode 0664; enrollment 2fc818bf1a58db5b2a03736ef86b4bef6efea31c2f6f3563813eabd9edb18db3; launch d061768f2a2807eabfe5d95aaaf3b4358efcbe6bcf698f310a1fa3270fd9bf39; exactly four named attempt files; empty output files; no controller.json or transaction. These observations are not substitutes for root's native ownership/protected observation.

The reported EACCES cause is consistent with the exact approved mode and direct Popen argv. The source-only preparation preserved controller mode 0664 while the original capture helper invokes it directly. The earlier disposable preparation fixture substituted that final runtime launch boundary and did not test executability. Do not chmod or rewrite the already sealed capsule or erase its attempt.

Invocation must be a fresh isolated interpreter with -I -B -X pycache_prefix=/dev/null; source hashes should be verified immediately before root's native observation/restore. Awaiting final fixed source and independently reviewed native observation digest before a terminal source ACCEPT.


## Final verdict — ACCEPT exact recovery source and observation

Final source `/tmp/jsh-retirement-launch-recovery/restore_failed_exec.py` SHA `6a9c010951e89e3fd53142c1eb34dfad62b425d071336b68be9163cb54c26efb` includes the exact HostExchange pin, refuses unexpected top-level Python sources, and now checks named attempt-directory/lock identity inside check_log both before and after protected verification. Both original findings are fixed without changing the old capsule or transcript.

Approved observation `/tmp/jsh-retirement-launch-recovery/observed-restoration-final.json` SHA `03641f02de9f851b1b42c2abba5b76fe3abee8ada1d071e7ffcd1c8e3b1af1fc` was independently read as canonical bytes in an owner-only 0600 single-link physical file. It has exactly the expected schema, enrollment SHA, failed-launch SHA and original scope. Its exact scope equals the original canonical launch exchange and enrolled fence, including all three pairs, control, generation, policy and intent. Exact launch argv still names the original non-executable controller and install argument. No fabricated controller exit/refusal was added.

The coordinator reports that the final isolated native observation exited zero under the actual original leases and unchanged full protected witness, matching the earlier observation bytes. This lane did not rerun that native observation or acquire locks; it independently reviewed the source and supplied evidence. The approved restore path rereads the full boundary and original protected witness under those same actual leases inside the HostExchange callback, before any route move, and verifies terminal restored witness afterward. Its replay requires identical terminal approval bytes.

ACCEPT applies only to restoring this exact failed-exec attempt using those fixed source and approval pins and a fresh isolated interpreter (-I -B -X pycache_prefix=/dev/null). It is not install, retirement, new invocation or pilot acceptance. Preserve every original launch/capsule artifact and verify actual terminal restoration after the coordinator executes it.
