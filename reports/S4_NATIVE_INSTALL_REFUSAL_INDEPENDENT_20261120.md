# Independent first-preflight refusal review

**ACCEPT the captured first-preflight refusal and unchanged scoped source. REJECT the original restoration approval file encoding.** Its parsed contents match the refusal, enrollment, and acknowledged closed exchange. The original file ends in a newline, which the restoration parser rejects because it requires the exact canonical JSON bytes.

| Artifact | SHA-256 |
| --- | --- |
| Captured refusal | `4c67668ac78f396fd8af13c2e44f6a66b5713e054b56524688b315a1c0f680fe` |
| Listener enrollment | `49176a2101216667b53ca238b5e46910c2461a27b96cc81c4a3508a3a676ce15` |
| Listener checker | `c70212dccd5791e0173949605e8bd54f4736a03e6c9bd6ef788c0f87363eaa6a` |
| Original exchange policy | `850bf36bc9d2d7e8b4484b1856f866cbdd22e23ac459c09a086ed2533da4afcd` |
| Proposed approval as supplied | `54f83a758d8e3132ddf797c592d04e5a9d46e2139f290de0c96d6edca5d78bef` |
| Expected canonical approval bytes without the newline | `4dc2b2ad75566f880ac296cc8553837c15a7d3a456ba0abd4366b4f31e6881a4` |

- All seven attempt artifacts were present with the expected permissions. The canonical launch, process, and exit records matched the receipt. The controller exited with status 1, its standard output was empty, and the retained error output matched the refusal receipt and its exact first-preflight refusal wording. The recorded process identity no longer existed on the same boot.
- The only new controller or installer artifact in the listener capsule was its empty private transaction directory. Its device, inode, ownership, mode, and change timestamp matched the receipt. The receipt's recorded mount identity matched the enrollment's recorded mount identity. The controller journal, service-hold directory, pending admission guard, and sealed wrapper images were absent.
- Recomputed all 47 scoped source before-images against the pinned manifest, including ownership, mode, hash, and expected absences. The parked package, release marker, admission guard, and both maintenance drop-ins were absent.
- The exchange journal showed `closed-acknowledged`, three completed pairs, and no terminal proof. Reconstructed the absolute pairs and policy intent. The full intent and digest matched the journal, enrollment, refusal, and normalized restoration approval. The source explicitly treats this acknowledged phase as its durable closed witness. [Exchange witness](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01/host_exchange.py:461) · [Approval parser](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-listener/preinstall_abort.py:49)

These were read-only checks of the recorded artifacts and source. The coordinator separately performed the protected-state, native exchange placement, and runtime checks.
