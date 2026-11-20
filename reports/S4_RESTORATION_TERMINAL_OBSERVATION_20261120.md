# Sprint 4 terminal release observation

The staged joint controller holds its existing controller, application
and installer leases while it verifies the completed installed or rolled
back release, exact installer receipt, absence of runtime and service
holds, and restored unit status. It produces the maintenance ID, target
manifest, exact controller journal SHA-256 and installer receipt
SHA-256 for the eventual matching exchange and pilot verifier. The
ordinary release entry point reuses the existing released-source checks.

The focused disposable test passed after independent QA required the
terminal method to compare canonical bytes from the same journal read.
It verifies a refused interrupted release, exact digest after recovery,
retained leases, stable replay, and refusal of semantically identical
JSON with changed bytes. Independent recheck accepted the staged source.
The controller SHA-256 is
`a4a45a1de5ad9076d223ef3e535cf1c8a4d73e96142ce7bb315959a3f62cd786`.
The preceding full 15-case rehearsal passed in 258.134 seconds before
the narrow canonical-byte follow-up. The full exact rerun, session 29460,
passed all 15 cases in 247.925 seconds. Its log is at
`/tmp/jsh-s4-restoration-terminal-final-rehearsal.log`.

The observation is one input to the outer restoration decision. Pilot
settlement, correspondence to the closed exchange generation and
continuous site custody remain gates. No live action was taken.

[Independent first review](S4_RESTORATION_TERMINAL_INDEPENDENT_QA_20261120.md) ·
[Independent recheck](S4_RESTORATION_TERMINAL_INDEPENDENT_RECHECK_20261120.md)
