# Joint release physical identity and restored-host repairs

November 20, 2026. Source candidate only. Independent QA held the original
tool snapshot on endpoint mount/ancestor identity and missing restoration
attestation. The corrected snapshot is
`/tmp/jsh-s4-combined-release-tools-repair.JpgiG3IM`.

Absolute paths opened by the installer now traverse each ancestor with
no-follow directory descriptors. Each scoped file descriptor must share the
mount of its parent, including payloads, source checks and controller
terminal receipt verification. The controller rechecks source and receipt
around fresh restoring and restored host attestations. A refused witness
reestablishes the durable marker and service hold before exiting, leaving
RELEASING available to the same-direction recovery. Restoration skips a
second start if the wrapper is already active during recovery.

Six focused regression cases failed on the prior tools and passed on the
repair, covering a simulated file mount, ancestor path alias, and initial
and restarted restoration with accepted and refused attestations. A fresh
independent source recheck and the full repaired controller fixture are
assigned separately.

The architecture reviewer proposed a journaled canonical host absence
fence. In a disposable OS-level Python probe, canonical absolute and
tools-relative script starts both failed while the entrypoint was absent;
a file descriptor opened before removal still read the original bytes.
This supports the need for a post-fence process drain. It does not verify
production exclusivity or a controller implementation of that design.
The reviewer and QA reports are preserved alongside this checkpoint.
