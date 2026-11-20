# Observation-only Company-control race repair

This exact three-file overlay requires a callable Company-control guard before
every observation-only remote read and reruns that guard after the read, before
any chunk or receipt confirmation. The exact-v2 publisher binds the callback to
the established fresh local/remote Company guard and frozen control evidence.

It does not authorize Google access or a live observation. Installation remains
a separate guarded step after independent package and rollback review.
