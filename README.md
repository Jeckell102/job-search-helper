# Milestone 1 scoped backup

This is a source-and-evidence backup only. It excludes all databases, locks,
credentials, inventories, raw job data, and Google artifacts.

It captures the operator-provenanced one-company request path and the private
retained-work preflight extension. The protected checkout was already dirty,
so this bundle is a provenance snapshot for review and recovery, not a claim
that every copied file is solely this change's diff.

Verified before backup:

- 78 retained exception/runner/orchestrator/publication/provenance tests passed.
- 139 intake/exact/runner regression tests passed.
- The actual Samtec request is held safely behind the historical Saronic cycle.

The included authorization preview is read-only and expires as recorded. It
does not authorize or activate any production action.
