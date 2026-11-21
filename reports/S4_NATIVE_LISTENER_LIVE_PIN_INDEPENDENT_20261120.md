# Independent staged preflight pin review

**ACCEPT for the two exact private staged capsules.** The review used read-only staged files. Native mount, running service, and production verification belong to the coordinator.

| Artifact | SHA-256 |
| --- | --- |
| Original checker | `6e55698a54f2df58605a92e3f61326e75628caa9c89bf2e5d9d1cfac015c8406` |
| Listener checker | `c70212dccd5791e0173949605e8bd54f4736a03e6c9bd6ef788c0f87363eaa6a` |
| Original enrollment | `53db1324ba127b3df7d01a1f75bdbb2e029b68866e0c07bb6b091f10d3e2b391` |
| Listener enrollment | `49176a2101216667b53ca238b5e46910c2461a27b96cc81c4a3508a3a676ce15` |
| Shared original exchange policy | `850bf36bc9d2d7e8b4484b1856f866cbdd22e23ac459c09a086ed2533da4afcd` |
| Shared original protected-state pin | `abab8873ce31e0c0b8526f9bdcaa7ff684fc53498c3293f25b12a49092f28b96` |

- Recomputed and matched all 69 payload hashes in each capsule. The 47 candidate files matched the same manifest hashes and modes in each capsule. The staging plan and manifest were byte-identical.
- The changed staged source and embedded Python members were `ancillary_process_witness.py` at `f4a82eaed30a46b507c525875418d4ec471b8b9147036adc67061970a5e70819` and `host_checkpoint.py` at `fe5ac8bed3ab1e88ff645859ba6f156229694643d3b3549415748c8952016e43`. Checker member inventories and CRCs passed.
- The embedded policy changes were exactly the capsule path to the `-listener` suffix and the observer socket from `/run/jsh-s4-atomic-machines-01/observer.sock` to `/run/jsh-s4-atomic-machines-02/observer.sock`. The configured wrapper port remained 18789. Both recorded unscoped source inventories, the canonical identity record, and the external controller and lease bindings matched.
- Both enrollments and policies reference the same original protected-state pin and exchange policy. Resolving each same-parent pair to absolute paths reproduced the enrolled pairs and the exact recorded journal intent, including its digest. At review time the exchange record was prepared at phase `closing`, with zero completed pairs and no terminal proof.
- At review time, each enrolled attempt directory held only its own empty `attempt.lock`. Neither capsule held a transaction directory, controller journal, service-hold directory, pending guard, or sealed wrapper images.
