# Independent acceptance of signed late-control archive admission

**ACCEPT** for deriving exact continuation claims from the existing bound source-transition preview and freezing one original-byte-preserving Inbox archive. This disposition covers the signed preview through `FROZEN` only.

| Reviewed candidate | SHA-256 |
|---|---|
| `late_control_continuation_journal.py` | `505ac53a21f7f6ee12695c3ed73ba5be6d0d6b3006b9dd8c029f68e12b5e4d60` |
| `late_control_pending_plan.py` | `a22a672cbd90ee1aa28b57019e8b3a254b398a176ad45be182397f9297f7b953` |
| `late_control_continuation_authorization.py` | `83102f7181738d023dfa444cf6c25c4c6d55e1016f4527bb3360b12ee6a0311b` |
| Maintained journal fixture | `1aac731e5724ca5e37064379114df46109a9a41c4e772e5b0a5d311749654c0a` |

The original journal `6c59e5ecc32592b8c0076dcf3578886cbd972fdc0c4478be65230438ff22527b` accepted a valid old Ed25519 approval after one newline was appended to either original Inbox JSON text. The corrected claims include both raw-text SHA-256 digests and both semantic digests. The original regression independently reproduced twice and refuses both changes on the corrected pins. The archive retains the exact raw texts and cursor.

The corrected journal re-derives the selected Company and workbook scope, current preview and operation mapping, distinct indexed observation and pending-write evidence digests, and the signed approval before any schema or row is written. A missing original, blocked inventory, changed cursor, incorrect signed plan, changed evidence, another exact Inbox journal, and either cycle-keyed or request-keyed competing receipt all prevent admission. An exact restart reuses the `FROZEN` entry. Tampered archive or approval and a second valid but different envelope hold without replacing the entry.

The disposable positive run checked that claims preparation creates no schema, freezing leaves existing Inbox plan, cursor, inventory, receipt and remote plan rows unchanged, and the Jobs SQL dump is identical. An independent test passed the frozen plan to the real generic publisher with unusable store and transport arguments. Its existing dedicated-release hold fired before touching either. The pending plan is sealed local-only and has no ordinary remote release path.

**Evidence** — 30 passed and one downstream local-application test deselected under a socket audit guard. `run_qa.py`, `test_independent.py`, `INITIAL_OUTPUT.txt`, and `CORRECTED_OUTPUT.txt` are in this directory. Disposable Jobs and Inbox fixtures only. Source selection through the owner and separately validated remote transcripts are prerequisites at wiring. Jobs-only competing application, origin-writer ownership, local application, and remote publication are separate effect-boundary checks.
