# Offline test runner thread compatibility

The baseline and verification receipts for the ATS repair show the
unchanged shared SuccessFactors cases failing to create a thread. In a
disposable subprocess the installed offline filter returned EPERM on
glibc's clone3 attempt. No fallback was attempted.

The staged fix changes only that refusal to ENOSYS, so glibc uses the
already permitted legacy thread creation path. The trace confirmed that
clone3 still failed and legacy clone created the thread. The existing
filesystem, network, process interference, memory, task-count, and
timeout configuration was kept intact. The unchanged
`tests/test_successfactors.py` file passed all 24 cases using the actual
`coding_tools.run_tests` entry with the staged helper on the frozen
before-source snapshot.

Evidence is under `/tmp/jsh-ats-thread-runner/` in `BEFORE.trace`,
`AFTER.trace`, and `SHARED_SUITE.json`. The trace contains process
addresses, so keep it local. The source and evidence summary can be
included in the scoped backup. This fix has not been deployed and does
not make the rejected ATS parser valid.

Independent QA accepted the exact staged helper SHA-256
`3309cff389adc446c21f84bb787e946bfb47ff986624c374b6947fdf859067cd`.
The unmodified coding-tools runner and shared test bytes match the
installed versions. The existing denial of clone3 and the other
sandbox restrictions are preserved.
