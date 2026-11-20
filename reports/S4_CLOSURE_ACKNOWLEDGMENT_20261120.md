# Sprint 4 durable closure acknowledgment

November 20, 2026. The coordinator staged the revised site candidate
in `/tmp/jsh-s4-acknowledged-site.QzgJ0Rvm`. The underlying controller
now records a second phase only after the completed closure journal has
been synchronized to disk. The unchanged read-only site adapter requires
the acknowledged phase through the controller's public witness API.
Starting restoration also requires acknowledged closure and independently
verified terminal evidence.

A complete legacy or interrupted plain closure is eligible for explicit
close replay. Replay syncs the existing record, checks all placements and
publishes acknowledgment without moving any route again. The old staged
reader refuses the new acknowledgment phase. Keep the corresponding
controller available for recovery and do not switch to the earlier version
while a release journal is active.

The source SHA-256 is
`8168d900979d68aebc950d7bb8495705a5190368e8ca3ac932a7da4d4c7dfb1f`.
All 84 disposable tests passed. Independent QA reran the two focused
interruption cases and accepted the staged change. The first failure
occurs when the completed closure is visible but its directory sync
fails. The site and restore refuse it. The second failure occurs when
the acknowledgment itself is visible after the earlier closure sync
succeeded. The witness can rely on the earlier sync. Replay restores
durability of the acknowledgment without exchanging paths again.

Read-only MuleLab checks verified that the launch account owns its home,
the production checkout and three alternates. The wrapper host and tunnel
are enabled and running. The scheduled job-search sync unit is loaded,
inactive and disabled. This evidence supports release planning. Continuous
custody of the actual routes and policy, accountable writer drainage,
the bounded eligible pilot, and authenticated restoration remain open.
No service, checkout, job data, Sheets or Jetson state was changed.

[Independent source QA](S4_CLOSURE_ACKNOWLEDGMENT_INDEPENDENT_QA_20261120.md) ·
[Independent host readiness review](S4_MULELAB_RELEASE_BOUNDARY_REVIEW_20261120.md)
