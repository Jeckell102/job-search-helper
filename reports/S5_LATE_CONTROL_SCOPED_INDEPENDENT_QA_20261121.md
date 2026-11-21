# Independent recheck of late-control delta readback

**ACCEPT** for the revised pending-plan seal, signed `FROZEN` archive and exact local-primitive application/replay on a disposable copy.

| Reviewed file | SHA-256 |
|---|---|
| `late_control_pending_plan.py` | `270ebe50c6b2a72c4d8a19180c5551552ca4d7d193523588ed42598f9854ad96` |
| `late_control_continuation_journal.py` | `505ac53a21f7f6ee12695c3ed73ba5be6d0d6b3006b9dd8c029f68e12b5e4d60` |
| `late_control_continuation_authorization.py` | `83102f7181738d023dfa444cf6c25c4c6d55e1016f4527bb3360b12ee6a0311b` |
| Maintained journal test | `1aac731e5724ca5e37064379114df46109a9a41c4e772e5b0a5d311749654c0a` |

The combined corrected run passed 31 tests, including the maintained journal's formerly failing local composition. The real primitive applied the two selected operations with one operation per chunk, returned `VERIFIED`, and replay recovered the same record digest. The selected Job History kept `Keep` and `Human Reviewed` while moving to the archived source and `$100k`. The new source had its Job Evidence row. The original Inbox cursor stayed 1 and the publication receipt count stayed zero. The generic publisher still holds the delta before any remote or store access.

The accepted preview pins all seven review columns in its selected History operation, and the signature covers the parent digest including the successor-operation digest, current row-presence digest and hidden manual-choice snapshot digest. The hidden digest covers choice value, timestamp and serialized row policies. The new effective delta omits protected review values and expected guards so its fingerprints conform to the existing SQLite manual-choice write behavior. The signed original preview and archived parent retain their guards.

Two independent disposable tests changed (1) the hidden timestamp while preserving the visible choice and (2) the visible Fit Level while preserving the hidden choice. Each altered the corresponding parent digest and the existing approval refused to re-freeze. Direct use of the archived effective plan still verified in both changed fixtures and preserved the newer review data. That difference identifies the required check at the future dedicated apply boundary.

Before the first application effect, the dedicated owner must re-derive and match the authentic signed parent under established scraper/writer ownership, with the admission archive and original rows revalidated. Recheck the visible review and opportunity fields, exact stable history row identity, hidden manual choice value and timestamp, and row policies. A missing or replaced manual pin also holds. On a partially applied restart, verify those immutable review protections against the already bound pre-apply state while recognizing only the exact planned source and evidence effects proven by the Jobs apply journal. Rebuilding the entire original preview after the expected source transition would treat owned progress as drift. This review supplies fixture evidence for the archive and local primitive. Dedicated live application and remote publication require their own acceptance.

Guarded run outputs and the independent test are alongside this report.
