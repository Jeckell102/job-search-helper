# Maintenance source policy evolution — bounded design review

**PROCEED with a new explicitly versioned manifest policy in a fresh disposable source/capsule.** Keep the accepted v1 policy and old capsule/journals byte-identical. Do not pad the changed set with an unchanged receipt bridge, and do not merely expand the global WRAPPER_PATHS constant.

Read-only source review of the accepted Freeform installer/controller. No parser execution, application/DB/service/lock access, network, or live changes. The reported 38-path overlay and nine additional wrapper names come from the coordinator's current payload check; this review does not independently enumerate that overlay.

## Exact cause and narrow repair seams

1. `installer.py:95–120` accepts only canonical `sprint-4-source-manifest-v1`, permits just three wrapper paths, rejects unchanged before/after entries, and requires all three wrapper endpoints to have present before-images. An unchanged `coordinator_receipt_host_bridge.py` therefore cannot be omitted *or* legitimately included in v1. The parser is correctly rejecting the new request under its old contract.
2. Preserve that entire v1 acceptance policy. Add a distinct v2 schema branch using the same exact canonical JSON, endpoint and owner checks. Its closed wrapper-name policy should contain only the existing three names plus the nine explicitly reviewed names needed by this payload; do not introduce arbitrary directories, extensions or a broad writable wrapper-tree rule. The manifest SHA remains the independently approved authority selecting the exact changed subset. Require `host_server.py` in the changed set with present before/after images, because the controller's physical host close/reopen protocol depends on it (`controller.py:734–764`). V2 may omit unchanged bridge/store endpoints. Every listed entry must still have before != after, exact owner, exact after bytes/mode, and either exact before or explicit before-absence. No deletions need to be added.
3. `installer.py:191–200` maps known wrapper destinations to the existing pinned tools directory. Extend only destination recognition to the union of reviewed versioned names, leaving schema-specific admission in load_manifest. Alternatively derive the same validated routing from SourceManifest; no broad filesystem lookup is needed. Keep same-mount, no-follow, single-link, owner and descriptor checks untouched.
4. **Critical companion change:** `controller.py:477–479` must compute wrapper_names from the actual validated `self.manifest.paths` classified as tools, exactly as it already derives package_names. It must not use the complete permitted-name universe. Under v1 these are the same three mandatory names, so the old exclusion behavior stays equivalent. Under v2 the omitted receipt bridge and every other unlisted sibling remain in the unscoped snapshot.
5. Reuse the existing protection unchanged: `controller.py:254–268` hashes unscoped entries with file identity, mode, owner, digest and mtime; `:728–729` seals it; `:814–816` rechecks it throughout publication/rollback. Scoped install/rollback already loops only manifest.paths (`installer.py:444–520`) and preserves explicit absence. `controller.py:294–313` purges bytecode only for the supplied changed paths and must continue using the correct tools routing.

Simply broadening WRAPPER_PATHS would be wrong: `controller.py:479` would exclude permitted-but-unlisted files from the unscoped hash, while scoped verification only visits manifest.paths. The unchanged receipt bridge could then be protected by neither check. The dynamic actual-path exclusion is required before any v2 qualification.

The source manifest SHA is already bound in controller approval and installer transaction (`installer.py:394–408`), and tool file identities are pinned in the controller (`controller.py:495–496`). No rewrite of prior receipt schema or active transaction is needed. Use a fresh hold ID/capsule and independent tool pins. The new controller must still parse and verify an old v1 predecessor without altering its journal, receipt or original protected guard. Existing predecessor verification is at `controller.py:580–599`.

## Must-pass probes before maintenance preparation

| Probe | Required evidence |
| --- | --- |
| V1 compatibility | Existing exact v1 fixture still passes; omitted required bridge, unchanged entry, new wrapper name, noncanonical JSON and wrong manifest digest still fail as before. Existing predecessor receipt/journal readback remains identical. |
| V2 exact payload | The exact reviewed 38-path manifest loads; the nine reviewed additions/replacements route only into the existing tools directory. An unlisted tenth wrapper name, traversal, nested path, alternate extension or package initializer remains rejected. Missing host or absent host before-image fails. |
| Untouched bridge and siblings | V2 changed set omits the unchanged bridge. Confirm its name is in the unscoped measurement and absent from the mutation/bytecode lists. Inject bridge byte, inode, mode/owner or presence drift and one ordinary unlisted sibling change: controller must hold before publication. Also reject appearance of an unlisted new sibling. |
| Exact creation, replacement and rollback | Reuse the existing disposable real Controller/installer fixture: one wrapper addition (before absent), one replacement and the changed host. Install reaches only the declared after endpoints; rollback restores exact before bytes/modes/owners and removes only the declared addition. Unscoped sibling identities remain exact. |
| Restart cut | Interrupt after the first declared source effect, reopen the same new transaction and complete install or rollback. Assert exact manifest/tool pins, no mutation outside the pinned set, durable host closure until final verified reopen, and no old predecessor receipt change. |
| Drift before write | Changed before bytes, candidate after bytes, mode/owner, appeared before-absent file, symlink/hardlink, or substituted parent must refuse using the existing checks. New policy must not bypass these paths. |

These are tests to perform in disposable fixtures, not claims of passed QA. The existing accepted composed maintenance harness can supply real install/rollback mechanics with host observations substituted and explicitly limited; no new controller framework is necessary.

## Scope limits

This change only makes the reviewed maintenance payload expressible and keeps unscoped wrapper files protected. It does not resolve the application-level unfinished-cycle release gate, create native qualification, change the protected historical data, or authorize an installation. Optional new wrapper paths must not enter the allowlist or the manifest without their own accepted source pin and runtime need.

Installed source pins reviewed:
- installer.py: 796e8b04cca48c7641c45480611ab43f2d19a2a96da9dc9a08d548d029fc1ee4
- controller.py: 927063a9797c121a8c6e4b73011a79ea2874d72427c64387e969355503b092eb
