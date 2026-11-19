# Selected-prefix full-prefix boundary repair

This two-file overlay permits an independently verified selected prefix to
equal the complete local operation stream. That case is already accepted by
the immutable planner and validator and produces no suffix replay.

The direct end-to-end regression exercises a 1/1 prefix, confirms zero
remaining operations, reaches `V2_PLAN_FROZEN`, and confirms no publication
receipt or remote write. The installer requires both exact protected
preimages, holds the existing integration lock, retains a durable rollback
copy, and hash-verifies install or rollback.

This package authorizes no live installation, database mutation, Google
access, publication, scrape, queue action, or service change by itself.
