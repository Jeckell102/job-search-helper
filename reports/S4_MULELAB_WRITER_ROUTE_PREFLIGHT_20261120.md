# MuleLab supported writer route preflight

November 20, 2026. Read-only configuration and effective service snapshots.
The wrapper development service was running and enabled. The job-search
sync service was inactive and disabled. Both units reported loaded
configuration with no pending manager reload. No action was taken on
either service.

Two additional local source trees have scraper launchers and the same
configured workbook as production. `job-search-helper_old_copy` uses
SQLite and a distinct State path. `job-search-helper backup` has a
different State path and does not select SQLite in its checked
configuration. `job-search-helper-sqlite-migration-20261012` also has a
launcher and distinct State. Its workbook identity could not be resolved
from that checkout's local configuration. Observations are configuration
comparisons only. No workbook identifier or credential was saved or printed.

A production-checkout scope witness must cover both known same-workbook
launch routes. Per-checkout SQLite and lock identities alone cannot
exclude writes to the same remote workbook. Resolve the remaining
checkout's effective routing, process ownership, command environment and
service or timer coverage before any live closure. Confirm that approved
holds are durable for all known same-destination routes or that the routes
are independently proven disjoint. Neither exclusive operation nor an
active competing writer was established by this preflight.
