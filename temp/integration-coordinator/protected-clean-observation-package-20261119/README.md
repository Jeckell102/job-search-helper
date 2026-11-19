# Clean-field observation-only repair package

This source-only package is an exact 10-file overlay for the current protected
Job Search Helper checkout. It adds separately pinned legacy delivery evidence
and a durable observation-only remote mode. Observation-only recovery performs
fresh exact Google readback and never calls the remote commit method. A remote
mismatch remains held with no automatic write.

This revision also permits a clean selected field with no saved baseline to
reach observation only when both its immutable direct target and its current
local value are blank. Nonblank values, dirty fields, append-note targets,
conflicts, and unresolved delivery attempts still refuse. The same blank-only
predicate is rechecked during exact planning and on both sides of remote
readback before any confirmation can advance.

`PROTECTED_BASELINE_SHA256SUMS` pins the only accepted protected preimages.
`SHA256SUMS` pins the candidate files. Installation must hold the existing
integration lock, verify every preimage, create an fsync-backed rollback copy,
replace only these ten paths, verify every installed hash, and retain the
rollback manifest. No live database or Google action is part of source install.
