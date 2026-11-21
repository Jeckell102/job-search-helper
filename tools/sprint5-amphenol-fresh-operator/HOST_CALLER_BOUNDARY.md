# Operator successor Store boundary

`Store.reserve_operator_repair_successor(...)` is a local durable intake
transition.  It does not create an outcome, a delivery receipt, a task, a
lease, or a release.  It requires both stored coordinator evidence and
explicit pins for the stopped predecessor repair/task, then creates one normal
`HELD_FOR_REPAIR_TRIAGE` successor row for the existing review/promotion path.

Before calling it, the host must independently verify:

1. The retained `-04`/current observation is the approved exact successor of
   the preserved historical receipt, including the current source and request
   binding; the Store cannot inspect those host artifacts.
2. The candidate outcome came from the current settled operator request while
   the approved application owner leases are held, and the installed approved
   adapter is still the one measured by that observation.
3. The outcome was delivered and acknowledged through the ordinary bounded
   delivery path before reservation.  The Store verifies that durable fact but
   does not perform delivery itself.
4. The supplied predecessor task state digest is freshly read.  A successful
   call only creates a held repair: the host must use the existing separately
   reviewed promotion/owner handoff before any task or inference can launch.
