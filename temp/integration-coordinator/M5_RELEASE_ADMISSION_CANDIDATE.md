# Milestone 5 shared release admission candidate

Status: isolated source candidate; production unchanged; independent QA and maintained controller wiring pending.

## Implemented F3 safety boundary

- Release activation and every normal scraper start use the same existing scraper/writer lock. A release cannot begin while a scraper owns the run, and a scraper cannot begin while release files are changing.
- The reviewed manifest binds the exact Company source revision, every changed file's before/after metadata, the complete installed source tree, complete integration-configuration tree, runtime dependency digest, and exact validation receipt.
- Activation writes a durable journal before the first target change. A crash or failed verification leaves a nonterminal journal, and the actual runner boundary refuses to start until guarded rollback completes.
- Replacement uses per-file atomic writes and directory synchronization while the shared lock is held. The installed set and full source/configuration/dependency identity are rechecked after replacement and after the bound verification callback.
- Rollback holds the same lock, restores only exact recorded files, removes only recorded newly added files, refuses third-party changes, verifies the complete prior source/configuration tree, and records a terminal rollback receipt.
- A completed activation emits the complete release binding consumed by the repaired-company retry boundary. A fresh process is required for a subsequent normal run, so no worker retains partially imported release modules.

## Verification

Eleven release-specific checks cover successful multi-file activation, shared-lock exclusion, crash after the first replacement, startup refusal with a nonterminal journal, exact rollback, installed-test failure, substitute PASS-receipt rejection, Company revision drift, complete-tree drift in an unlisted file, dependency drift, and third-party rollback conflict.

The combined request, event, release, storage, publication and outcome regression selection passes 162 tests on Python 3.11. Static compilation and whitespace checks pass.

## Maintained release-to-retry controller

`release_controller.py` now consumes the completed exact release receipt and creates the durable retry intent from that receipt only. The failed request identity is part of the reviewed release manifest, so a caller cannot substitute a different failure after activation. A crash immediately after activation is recoverable: the next invocation reuses the byte-identical completed receipt and derives the same retry attempt without reinstalling. An existing normal scrape request remains untouched while the release intent waits. A Company revision change after activation produces a visible stale hold and no retry request.

Five controller checks cover the successful handoff, crash-after-activation recovery, idempotent replay, occupied scan boundary, post-activation Company drift, and immutable failed-request lineage. With this controller included, the combined focused selection passes 178 checks.

## Explicit remaining gates

- The candidate has not been independently reviewed, deployed or exercised against the protected checkout.
- The deployed release entry point must construct the full manifest and dependency digest from reviewed validation artifacts and invoke this maintained controller; no production command is wired yet.
- The coordinator now has source-level downstream stale-result precedence; independent end-to-end review and protected-store reconciliation remain.
- F3 still needs independent QA, a disposable production-snapshot race rehearsal, guarded deployment, and live old-or-new version receipt evidence.
- Automatic release controls remain disabled. The induced integration-failure-to-confirmed-Sheets demonstration remains open.
