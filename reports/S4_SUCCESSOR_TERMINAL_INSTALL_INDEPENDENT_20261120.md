# Independent Sprint 4 terminal installation verification

**ACCEPT for the terminal source, installer receipt, alternate-route closure, and historical pin.** The independently read attempt returned zero with empty stderr and an exact `RELEASED` /`INSTALLED` result. The existing alternate-route closure stays in effect. The service observation below came from the coordinator's native readback. [Successor capsule](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-02) · [Attempt transcript](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-02-attempt/stdout)

| Verified artifact | SHA-256 |
| --- | --- |
| Terminal controller journal | `1b3c2acf0d0410ab8e25e1193f1c442b0d98e74efc6c8b92a306fe11500ffb67` |
| Terminal installer transaction | `45b3bc70da5c3033948d463a51d1e1802709e77ffe76571427916c64e4aa7e23` |
| Approved 47-path manifest | `a1863753a251058e1cd99266568aef3b6e9b3076e49c52dd0adff11d93f6a163` |
| Recomputed after-image aggregate | `477e398f83dd5a192c6e6a96e75d2421d159003f53d383b4c4669a8e79c36e97` |
| Attempt stdout | `7fd4b1e1d5cbefe9dca4440bf432cb60d06aed910c445d6e1d81b3cdfead4fee` |
| Attempt exit record | `637ea31588318d89abbac997963f8ea16bd4df7341b50d29704da722c1b19b93` |
| Closed exchange journal | `41bc7de446c7b01dabda0ccd14a006b55efd6679b7fcb25e876de5b8780ad604` |
| Verified protected-continuity attestation | `8e9358d209b0ab93f2cbb4ca630a36601df68ec4a07c34efda8b64f4972b2c50` |
| Original protected pin | `abab8873ce31e0c0b8526f9bdcaa7ff684fc53498c3293f25b12a49092f28b96` |

All 47 exact installed target paths were ordinary single-link files with the approved SHA-256, mode and owner. Each matched its archived after-image, including the distinct sealed wrapper-host payload. The package, inherited guard, source paths, installer gate and transaction directory retained their recorded device and inode identities. The installer journal minus its separately checked owner map matched the controller's receipt and the attempt output byte-derived receipt. Independently computed before and after manifest aggregates agree with that receipt, and the project maintenance marker is absent. [Source manifest](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-02/manifest.json) · [Installer journal](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-02/transaction/transaction.json)

The closed exchange journal records three of three placements and no reopening proof. I rebuilt the intent from the pinned policy and checked all three canonical names as empty, exact sentinel inodes and all three parked names as the original checkout inodes. Parent, exchange-control and lock objects matched their recorded device, inode, mode and owners. This inspection saw a consistent namespace-local mount ID 1487, and the retained native pins consistently use mount ID 30. [Exchange journal](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-02/exchange-private/exchange.json)

The historical protected pin still hashes to its original approved digest and matches the terminal continuity record and checker policy. The continuity record identifies the same boot, process and source manifest as the successful attempt and reports `verified` for `INSTALLED`. The predecessor controller, installer transaction and restored exchange journal retain their previously independently observed digests. I read those attestations and pin files without opening any production database. [Verified continuity](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-02/protected-continuity.json) · [Historical protected pin](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01/observed-protected-pin.json) · [Predecessor immutable evidence](/tmp/jsh-s4-successor-enrollment-independent.md)

The coordinator's supplemental native service query observed wrapper PID 487472 and assistant bridge PID 487522 both active, running and enabled. Scheduled sync was inactive, dead and disabled with PID 0. My read-only query could not connect to the user service bus because the tool environment returned `Operation not permitted`. The independent check acquired no maintenance or application locks and changed no services, deployment paths, alternate routes or data.
