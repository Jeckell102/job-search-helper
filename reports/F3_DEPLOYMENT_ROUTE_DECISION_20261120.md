# Sprint 1 route decision

**A bounded host closure plus pre-publication probes can establish coherent
source for supported production launches. The current census and probes alone
cannot establish durable exclusion of every writer to production state and the
shared workbook.** The package exchange can be the admission point for
canonical direct imports if the owner explicitly adopts that boundary and all
coherence checks run before it. If the existing contract requires direct
writes to stay closed through the published check, an additional launch or
resource hold is necessary.

## The actual second checkout

I inspected both checkouts without running application commands or exposing the
workbook ID. Both default to SQLite. Their effective default state and job
database paths resolve to four distinct on-disk files, and their configured
workbook IDs are equal and nonempty.

| Route | Observed resolution and resources | F3 consequence |
| --- | --- | --- |
| Second checkout's copied `.venv/bin/job-search-helper`, or its venv Python with no overriding path | The console script explicitly names the production interpreter in its shebang. The second checkout's own editable `.pth` also points to production `src`. A no-import `find_spec` confirmed this even with `-I`. The selected package derives its project root from its module path. | This is a concrete production route. The canonical sentinel rejects a fresh ordinary import while parked, and after exchange the route sees the complete target tree. Drain processes that started before the sentinel and include this route in both checkpoint probes. An explicit environment override can change the result. |
| Second checkout's root `job-search-helper`, scraper, or reviewer, using its own `src` first | The wrappers set or prepend their own `src`. A no-import probe confirmed the local package wins over the editable path. Its module-derived root selects its own SQLite files and lock directory by default. | Ordinary local execution here cannot mix the two versions merely because production changes. No hold on local-only copy operations is needed on this evidence. Inspect staged/actual invocations for absolute production state or job paths and for cross-checkout child launch. Any such invocation is a production consumer and belongs in the host hold. |
| Second checkout's own code running sync `once`/`watch` or review writeback | The same workbook is configured. The sync publisher constructs a write client after taking the writer lock in the selected state directory. Its own lock inode is separate from production. Whether publishing is active or its credentials usable was outside this read-only review. | This is a real concurrent workbook pathway if launched with write access. Its code stays independently coherent. It matters to any claim that shared job data stays untouched during the window or to any verification that consumes shared workbook state. |
| Unrelated remote writers | No evidence of a route into the production checkout, and this review authorizes no remote action. | Exclude from the source coherency claim. Describe any assertion of unchanged workbook data in terms of which writers were actually held. |

An alternate-first import finding demonstrates an alternate code path. It
does not establish that modules from either checkout mix in a fresh default
Python process. Production mixing is possible when an old production process
retains modules, source handles, or parsed launcher code across the exchange
and later imports or dispatches against the restored path. This requires
draining the process, not just stopping one parent PID. Separate-checkout
commands using production path overrides and separate-home publishers also
need explicit classification. There is no need to close every reader of the
host or workbook.

## Smallest supported production boundary

1. Keep the persistent affected-unit conditions in force, drain their
   cgroups, and keep sync disabled. On the real host, inventory the actual
   terminal, scheduler and automation launch routes that use either checkout.
   Verify effective interpreter, module root, path overrides and write
   targets. Include any copy route that imports production, targets
   production local state, or publishes to the shared workbook. My static
   search found no reference to the copy in the readable unit, cron and
   desktop launcher definitions inspected. That narrows the inventory but
   does not establish host quiescence or cover the live user cron spool.
2. Keep the atomic sentinel and nonterminal marker while changing source.
   Close additional identified write-capable launchers using their existing
   scheduler's persistent disable/condition or pause, then drain and confirm
   on the full host. Retain the controller and application locks in their
   established order. Reserve source edits and ungoverned manual launches
   with the host owner for the duration, including post-crash recovery.
   A census validates the reserve at a checkpoint but cannot implement it.
3. With the sentinel canonical, probe resolution with effective supported
   environments. Cover production root launchers, the production editable
   console, the second checkout's copied console and default editable venv,
   plus direct legacy/sync/pipeline/review routes. Test a production-first
   environment with an inherited copy fallback, and confirm that a
   copy-first path resolves only to its own source and intended resources.
   Use resolution and non-writing checks on the real host. Exercise actual
   start dispatch, cache cases and parked target behavior in the
   credential-free version-matched rehearsal. Verify receipt, all 13 scoped
   hashes and modes, non-scope bytes and effective cache prefixes before
   exchange. Never run a real scraper or a real publisher to prove routing.
4. Make exchange the point when canonical direct imports may see the
   verified complete target. Keep the unit conditions, release marker and
   write locks through the published probe and release. A crash after
   exchange leaves a complete version, but direct imports are immediately
   possible. Live locks cover cooperating operations while the controller
   is alive. The marker covers journal-aware bootstrap routes. Neither
   fences every direct control path, particularly after controller death.
   For example, direct `sync_cli intake-enable` reaches its policy setter
   before `sync_cli` takes the publisher lock. Release QA should record the
   exact boundary and what remains held at each state. If the contract
   requires all direct writes to await the published probe, keep a separate
   enforceable host launch/write hold through that probe and crash recovery.

## Authority and release decision

For the **supported-route** claim, obtain a bounded MuleLab maintenance
window from the host owner covering both checkouts' production-bound writers,
any same-workbook publishers from the second copy, and edits to the production
tree. Begin before the first hold/source mutation and end after verified
release or verified rollback. Get authority to pause or condition only
identified writer launchers and drain their processes, if any beyond the two
already-held units are found. The owner must stop initiating those commands
from unmanaged sessions during that window. Document who can launch them,
the persistent controls for all automated launchers, and how the hold remains
in effect if recovery crosses a reboot. This requires no edits to the
separate checkout and no shutdown of unrelated services. If a copy publisher
is active and its controller cannot be paused with current authority, the
specific outstanding authorization is to pause that launcher or to obtain a
publisher-free window from its owner.

For a **hard guarantee** against manual direct writers even after
republishing, an operator reservation is insufficient. Same-user bare Python
and the second copy's own-source routes do not consult the maintenance
controller. Require the host owner to provide an enforced boundary over those
actual launch contexts or their production write access through terminal
verification. An existing, constrained publisher access control could fence a
shared-workbook writer if one is available. None was demonstrated, and
blocking a whole user, changing workbook-wide permissions, or editing the
separate checkout is outside this review. If QA keeps that stronger contract
and no narrow host control exists, retain **HOLD**. A passing probe is not
authority to weaken the contract.

No production program, service, job data, configuration, or external
destination was changed by this decision review.
