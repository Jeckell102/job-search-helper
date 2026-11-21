# Independent applied checker amendment and restoration selection review

**ACCEPT the applied amendment and fresh restoration selection.** The verification used preserved and private bundle artifacts while the coordinator was running recovery.

| Artifact | Verified SHA-256 |
| --- | --- |
| Preserved original checker | `2152e99bd8994cc5bd51aa6cb9fea1c6ff36557fd975793456543342bc5101b8` |
| Active replacement checker | `b96589be7d70647187eb61e41f9cc5beec08e6c4e0c2e982c13862dabe5bda98` |
| Archived original controller journal | `ed80792a28eaaf6e1baa2a014621ae8f374472a955ffd4647ae60f9cbc9ee2b2` |
| Durable amendment plan | `fad7dee009b153e60ffff8649dcc5a300a510c7f8200eb019c5705c06b6ec0cd` |
| Reconstructed amended controller journal | `74797a455c1fab71912748ccf63fca5a54409499fec99ca4557ad18c515cf04a` |
| Installer rollback transaction journal | `25ed055b256e1c2f2c63c39c102d39aa3ee16fb82cd47c0543f089bfc00cedb9` |
| Prior restoration selection | `7a1261a26c9061d6a4cdeb20b23c9fe5e0c7a0c5eec1a2faf1358dbf786429e9` |
| Fresh restoration selection | `040ace71817e9166ba479b68aeb99948ff4197ea7d195109a43722b61ea39128` |

- The old checker at `host-check.rollback-amendment` retained exactly the original device, inode, ownership, mode, and digest. Its reference matched both the archived original journal and the durable plan. The replacement at `host-check` matched the replacement reference in the plan.
- Replacing only the archived journal's checker reference and encoding the result canonically reproduced the exact amended-journal digest. The installer transaction retained its prior hash and matched the archived `ROLLED_BACK` receipt; owners matched the pinned manifest.
- Both selections were private and canonical. The sole change was the new SHA-256 under `tools.host-check`. All 12 selected private bundle files matched their tool pins. The selection still pinned the original bootstrap before-image digest and exact current exchange policy, and still had `pilot` set to null.

The active controller journal, checkout, production SQLite files, and services were outside this read. Terminal rollback and exchange restoration remain separate verification.
