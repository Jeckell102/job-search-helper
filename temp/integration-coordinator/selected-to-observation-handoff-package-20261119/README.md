# Selected-to-observation handoff

This four-file overlay provides one narrow recovery from an untouched signed
selected-recovery `FROZEN` journal into the established full-legacy
observation-only path.

Cancellation requires the exact signed scope and normal scraper lock, archives
the complete selected candidate and evidence in the same SQLite transaction as
deleting the live marker, preserves the inventory and original legacy plan,
and refuses any local application, exact state, remote plan/chunk, receipt,
ordinary migration, or control-before-prefix progress. Identical retry
validates and returns the archive. Ordinary legacy migration refuses any live
selected or control-before-prefix owner before both new and retry paths.

Normal selected apply retains its expiry requirement. The rollback-only
cancellation verifies the exact signature and claims but remains possible
after expiry; it confers no publication authority. The protected
control-before-prefix schema, begin path, cleanup barrier, and inventory guard
are retained.

This package authorizes no live installation, cancellation, adoption, Google
access, publication, scrape, queue action, or service change by itself.
