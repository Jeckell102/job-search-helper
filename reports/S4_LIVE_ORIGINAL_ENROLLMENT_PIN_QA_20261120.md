# Independent QA for the actual original enrollment pin

2026-11-20 17:59 EST

**ACCEPT the staged original enrollment and unused custody as observed. Native activation remains separately gated.**

- The private canonical enrollment bytes hash to `53db1324ba127b3df7d01a1f75bdbb2e029b68866e0c07bb6b091f10d3e2b391`. The final checker hashes to the trusted `6e55698a54f2df58605a92e3f61326e75628caa9c89bf2e5d9d1cfac015c8406`. The protected pin hashes to `abab8873ce31e0c0b8526f9bdcaa7ff684fc53498c3293f25b12a49092f28b96`. The original checker archive binds the same physical capsule, protected pin and exact ordered exchange fence.
- The original controller file and directory bindings, six original leases, capsule and attempt lock identities, and unscoped package and wrapper measurements matched the enrollment subject to the native scope below. All 47 live before and 47 staged after manifest entries matched presence, content, mode and owner pins.
- The original alternate directories remained at their canonical routes. All parked names held the expected empty sentinels, and the enrolled non-mount pins matched. The prepared journal matched the exchange policy and intent and showed `closing` with zero completed pairs. The attempt directory held only the expected empty lock. There was no controller journal, installer transaction, marker, service hold, maintenance drop-in, wrapper seal or extension guard.

The read-only review used a different mount and user namespace. It verified the enrolled systemctl device, inode, mode and file digest, while the review namespace displayed the native root UID and GID as 65534. Native mount pins, native root ownership, and continuing exclusive custody remain the coordinator's checks before route closure or invocation. No host mutation, application launch, or privilege escalation was performed.
