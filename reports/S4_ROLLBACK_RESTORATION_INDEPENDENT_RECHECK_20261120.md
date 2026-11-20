# Independent recheck of pre-pilot rollback restoration

2026-11-20 17:16 EST

**ACCEPT for staged source.** Both required repairs are present.

- The rollback callback compares the retained checker path and bytes with the digest from the original authenticated controller binding before reading the archive. The terminal context already holds the release leases and validates the journal binding. The archive's policy must still identify the selected project, maintenance ID and exchange. Its protected-state verifier must support the retained FIRST PASS tree, and its private pin must equal the complete current measurement. An older checker or pin lacking that coverage cannot authorize rollback restoration. `pilot_restore_command.py:93-119,184-202`, `controller.py:532-560,989-1007`, `pilot_restoration.py:31-53`, `protected_state.py:328-350`.
- The protected baseline distinguishes missing and present FIRST PASS output roots. It fingerprints bucket names and all ordinary file content, including changes with no accompanying database row. The continuity witness also records the physical root, bucket and file identities. The original protected pin must be enrolled before installation, and the rollback path reuses that exact pin. `protected_state.py:59-87,252-278`, `physical_protected_witness.py:121-129`.
- The added fixture cases expect refusal, with routes still closed, for a changed checker identity and a new FIRST PASS output independent of database edits. The existing changed-outbox and wrong-terminal-target cases remain. I reviewed the source and assertions only. No host actions or new fixture executions were performed. `test_rollback_restoration.py:80-120`.

Site compilation and production use still require the approved original checker and private baseline captured before installation, continuous custody of the approved routes, and the independent restore approval.
