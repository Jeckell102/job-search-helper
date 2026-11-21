# Independent terminal rollback and restoration approval review

**ACCEPT the exact canonical approval for alternate-path restoration.** The diagnostic controller had reached terminal `RELEASED/ROLLED_BACK`, the original canonical source matched its before-image, and all three alternate path pairs were still pinned in the acknowledged closed layout when read.

| Artifact | Verified SHA-256 |
| --- | --- |
| Active terminal controller journal | `92c8a5b3e0c9429651aec328c3c30d42fc5751bcc689cca3b1d742f5d0c87120` |
| Installer transaction journal | `25ed055b256e1c2f2c63c39c102d39aa3ee16fb82cd47c0543f089bfc00cedb9` |
| Canonical restoration approval | `67f974ffa58a4d6cb825015198c8f6ec18bfd4aafcabc06b401163b5d4bd7cce` |
| Rollback selection | `040ace71817e9166ba479b68aeb99948ff4197ea7d195109a43722b61ea39128` |
| Original protected-state pin | `abab8873ce31e0c0b8526f9bdcaa7ff684fc53498c3293f25b12a49092f28b96` |
| Diagnostic exchange policy | `04aad106dd9cf585d0d02854c4c315c55049f2a0364911af80c5e1fff3006f9a` |

- The active journal was canonical and matched the same hash on both reads. Its installer receipt matched the unchanged transaction after accounting for the transaction's separate owner inventory. The receipt phase was `ROLLED_BACK`; its canonical digest, maintenance ID, project, source manifest, and terminal controller journal all matched the approval's release record. The live checker file's inode and digest matched the controller binding.
- All 47 actual canonical source paths matched the approved manifest before-images, including modes, owners, file hashes, and required absences. The selection pins the original bootstrap before-image.
- The approval bytes matched the exact canonical `sprint-4-pre-pilot-rollback-restoration-v1` schema. Its rollback proof referenced the verified selection and the exact original protected pin embedded in the checker. This confirmed the pin linkage from the authenticated observation; no database was opened for this independent read.
- The exchange journal was `closed-acknowledged`, with all three pairs completed and no terminal restoration proof. Its normalized intent, digest, generation, and routes matched the embedded policy and approval. Each actual canonical route held its expected empty sentinel inode, and each parked path held its expected original inode, with modes and owners matching their policy pins.

All operations in this review were read-only. No database connection, service query, or exchange mutation was performed.
