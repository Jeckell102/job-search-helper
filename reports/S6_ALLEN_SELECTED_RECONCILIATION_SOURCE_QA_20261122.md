# Allen selected Company reconciliation

**ACCEPT for this staged repository change.** All 255 copied source paths matched the baseline pin inventory except `sqlite_repository.py`. Reversing the supplied one-function patch in memory reproduced the exact baseline hash.

The selected path resolves one Company and compares its current source revision within the same existing `BEGIN IMMEDIATE` transaction that writes the revision and outbox event. It leaves the preceding field-aware merge as its own committed operation. Missing, duplicate or drifted selection exits before event insertion. Omitting the selection retains the original all-Company behavior, origin rules and result shape. The unchanged event writer suppresses an already-recorded current revision.

The recorded fixture exercises an actual scoped merge, one selected event after reopening SQLite, lost-response replay without another event, and rollback after an injected event-write failure. It preserves dirty notes, priority, the old job's Last Checked and normal old-source fences, and leaves a genuinely changed second Company unreconciled. Both test-log hashes matched the staged result, which records five focused and six compatibility tests passing. I reviewed the fixture and logs without rerunning them.

- Candidate source `a5a22c4d683ff58925370915aa63c8c58c5aa7e7f8ecefacb60b8af9d3dade3f`
- Focused test `8d6a6aa23ac8afa6548c8864011f8806c69791a88e4e699fb190e38dd7ec84bb`
- Recorded result `614303b4b564b475fbec73bd990edcc4ae6a78a58addabe871ec8197df797055`

The live guarded external correction, exact readback and ordered Allen admission remain separate. No live access or code changes during this review.
