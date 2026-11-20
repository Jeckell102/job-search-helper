# Sprint 1 post-exchange import guard

**Prefer the package exchange as the admission point.** Keep the actual
package parked until all checks needed for safe direct admission have passed.
Use the canonical post-exchange check to confirm the published result while
services and the bootstrap journal remain held. A crash in that interval can
expose only the already-verified complete package. This approach retains one
physical commit and adds no transient file to the package.

**If ordinary canonical imports must stay blocked after exchange, the empty
extension works for the tested Linux CPython routes.** It adds a second
durable transition and does not replace the host holds established in
`ROUTE_DECISION.md`.

## Synthetic test results

The tests created a disposable package, alternate package, synthetic editable
venv and bytecode caches under `/tmp`. They did not invoke an application
command or import a production module.

- Tested CPython 3.11.18 using the production interpreter and system CPython
  3.10.12 for resolver coverage. The project requires Python 3.11 or later.
  On both tested builds, stock `PathFinder` selected the generic
  `__init__.so` using `ExtensionFileLoader` before `__init__.py` and
  sourceless bytecode. Import failed with `ImportError: … file too short`.
  The zero-byte file contains no executable extension code and Python did not
  retry the source loader or continue to a fallback on the path.
- Twelve resolver/flag configurations denied entry after exchange. They
  included in-tree tagged and legacy bytecode, a custom cache prefix seeded
  for the canonical filename, the `/dev/null` cache prefix, explicit
  production-first search paths, an isolated synthetic editable `.pth`,
  and ordinary `PYTHONPATH`. Two `python -m` configurations and a synthetic
  console script also failed before executing the real package. A
  production-first path stayed blocked with an alternate path behind it.
- A child performed the atomic exchange, synced the source parent, and died
  by SIGKILL before release. Fresh imports stayed blocked. Removing the
  extension and syncing the package restored ordinary source, console and
  custom-cache imports. This tests process death and ordered fsync calls;
  it does not simulate sudden power loss.
- A pre-warmed finder still saw the guard even with the package directory
  mtime held fixed. An already-loaded module in `sys.modules` bypassed it.
  An alternate-first path loaded the alternate package. Explicit source
  loading and direct execution by filename can bypass package resolution.
  An explicit, isolated source-loader probe successfully loaded the real
  initializer from the guarded canonical package.
- A read-only directory listing found only `__init__.py` among initializer
  filenames in the present production and candidate trees. Compare all
  extension suffixes for every admitted interpreter again under the actual
  source hold before relying on this.

## If the stronger import boundary is required

1. While the original sentinel is still canonical, finish verifying the
   parked tree and root paths. Record a durable guard-creation intent.
   Require all extension initializer paths absent, including the
   interpreter-specific and `.abi3.so` names. With the recorded package
   directory open, create exactly `__init__.so` via exclusive no-follow
   creation. Enforce zero bytes, regular type, expected owner and mode,
   single link, and recorded device/inode. Sync the file and package
   directory before exchange. Existing unexpected files are a hold error.
   Establish the intent/inode record and recovery policy before exchange.
2. Treat the file as a separately authenticated maintenance artifact.
   The current controller's non-scope fingerprint **includes** it, so an
   unmodified controller would reject the change. If adopted, explicitly
   account for only this exact file and identity while it is required;
   compare the rest of the tree to the existing full expected fingerprint.
   After removal verify the unmodified fingerprint again. Do not add the
   guard to the 13-file release or rollback payload.
3. Exchange the guarded package and sync the source parent. Verify canonical
   directory and guard identity, the expected complete tree, and negative
   stock-import probes in every supported canonical environment. Use an
   isolated explicit source-loader subprocess for positive canonical code
   checks. Pin its source and module search path, bypass old caches, and
   prohibit state/network side effects. A successful ordinary import cannot
   be part of pre-admission proof while this guard is active. Exercise
   ordinary real-wrapper dispatch in the credential-free rehearsal. On the
   host, check the anticipated denial and defer ordinary positive checks
   to the admitted state.
4. Persist an admission-ready checkpoint only after all required
   pre-admission verification. Just before unlink, reverify the exact
   canonical directory and guard identity. Unlink that entry and sync the
   package directory. This unlink is the point at which normal canonical
   direct imports reopen. Retain the nonterminal journal and affected
   service holds until the remaining release conditions succeed. Resume or
   roll back only through the recorded transaction.

### Recovery boundaries

| Observed state at restart | Required behavior |
| --- | --- |
| Sentinel canonical, guarded real package parked | Verify phase, inodes, and pinned target; repeat the parked checks and exchange when ready, or run guarded rollback. |
| Real package canonical, extension intact | Repeat the canonical held checks using the terminal receipt. Keep launches blocked until the durable admission-ready checkpoint. |
| Real package canonical, extension absent, admission-ready checkpoint durable | Verify that the already-admissible tree is exactly the recorded target, sync metadata, and finish release. The unlink may have landed before the next phase write. If the guard reappeared because unlink was not durable, treat it as held and repeat validation before removal. |
| Extension absent after exchange without admission-ready, or unexpected identity, extra extension, or tree mismatch | Keep remaining holds, stop recovery, and investigate. Missing guard at this stage is a potential premature admission. Do not infer success or silently create a new guard. |

Hold existing processes and alternate writer routes independently. This is a
stock CPython canonical **fresh-import** guard. It cannot close a resident
interpreter, an alternate-first environment, a direct file loader or a
publisher using the separate checkout's own source. Limit the claim to
inventoried supported paths. Rehearse the chosen controller and its exact
crash recovery before using it.

## Simpler alternatives

The existing atomic exchange, with every release-critical verification
performed while parked, is the simpler standard option. Moving only
`__init__.py` out of the way is unsafe: the test imported a submodule from the
resulting namespace package. Temporarily replacing it with a raising Python
initializer would introduce a non-scope source replacement and require
dealing with both stale pre-hold and stale held bytecode for every effective
cache location. The extension avoids that source/cache ambiguity on the
tested platform. Where an enforceable host launch restriction already covers
every supported direct writer, keep it through canonical validation and use
the ordinary exchange.

No controller, production file, service or job data was changed.
