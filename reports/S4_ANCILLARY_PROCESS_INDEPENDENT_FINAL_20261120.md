# Final independent recheck of native administrator process observation

2026-11-20 17:35 EST

**ACCEPT for staged source.** Both remaining follow-ups are satisfied.

- The message reader computes time remaining against its absolute monotonic deadline before every receive and refuses an expired result after parsing. The server uses the earlier of the approved observation window and per-request deadline, checks time before collecting the fresh privileged observation, and checks and caps transmission against the remaining time. The client also enforces an absolute response deadline. `ancillary_process_witness.py:101-131,161-196`.
- A process-level missing-metadata error now requires the process directory to be absent before the scan can continue. For a process still present the check holds. A descriptor that disappears during enumeration remains an individual descriptor race. `host_checkpoint.py:329-351`.
- The added fixtures cover a complete readable message with an expired deadline and missing root metadata for an existing process. Source and fixture assertion review only. No independent probe, live administrator action, or deployment was performed. `test_ancillary_process_witness.py:108-130`.

Activation still depends on the approved native launch and host release controls.
