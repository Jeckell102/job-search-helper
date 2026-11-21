# Retained-cycle recovery triage

November 21, 2026. All checks were read-only. The current State and local
workbook mirror keep `CYC-B639C6D864EC` In Progress. The cycle has 45
saved inventories, including 40 without an Inbox block, and six legacy
plans. Five plans are at their end with blocked inventories. The Saronic
plan is the only incomplete one, with 67 of 208 operations and its
complete inventory of 276 postings preserved. No current publication
receipt was found for this retained cycle.

The installed normal, selected and late-Company-control preview APIs were
run against immutable native views with stable main files and journals.
All declined the six current plans. The first five inventories failed the
blocked-inventory gate. On Saronic, the normal path requires a complete
cursor, the selected path requires the Company operation in the verified
prefix, and the late-control path refused Job History ownership.
[Sanitized application preview](S5_RETAINED_NATIVE_PREFLIGHT_20261121.json)
· [Independent cycle snapshot](S5_RETAINED_CYCLE_NATIVE_SNAPSHOT_20261121.md).

Saronic's single Job History ownership discrepancy is operation 194,
outside the verified prefix. Its Company and Job Key match the materialized
local row. The operation's explicit expected-before Source Hash and all
eight other guarded values match the current row. Its proposed successor
hash differs. Exactly one retained inventory posting has the same key,
and recomputing the material hash matches that proposed successor.
Operation 195 contains the matching pending evidence for the proposed
version. The current hash has one local evidence row. The proposed hash
has yet to receive a local evidence row. Dates, job titles, URLs, raw keys
and row material remain private. This is a recorded candidate transition
between source versions. Neither preview authorizes a transition today.
[Independent exact-row reconstruction](S5_SARONIC_SOURCE_TRANSITION_INDEPENDENT_20261121.md).

The installed late-control validator expects each explicit proposed
Source Hash to already match the current row. The recorded transition
therefore remains held, even with the exact before guard present. Its
existing signed apply can stage a local hold only. The verified source
provides no compatible continuation from that hold to confirmed delivery
or terminal disposition. Ordinary cycle pause requires zero saved work.
Exact pause requires no unblocked inventory and full valid terminal-hold
manifests, including complete cursors and exact receipts for saved plans.
[Recovery prerequisites](S5_RETAINED_RECOVERY_PREREQUISITES_20261121.md).

The next decision is whether the retained plan must remain unfinished or
can receive a separate owner-reviewed recovery disposition. If recovery
is in scope, first review an exact one-row before-to-after contract with
both evidence bindings, current source authority, unchanged verified
prefix and all protected review/Opportunity guards. It would also need a
supported exact publisher or terminal hold for all retained work. No
signature or local gate change alone clears those obligations. The live
wrapper pilot separately needs a current owned failure and independent
qualification of the exact installed release.
