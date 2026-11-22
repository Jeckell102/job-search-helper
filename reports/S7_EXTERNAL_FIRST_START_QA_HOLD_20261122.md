# Independent first-Start review hold

November 22, 2026, Eastern. Initial source candidate `378a7a7480386d89506fe8ccff73bf6d10e0e0605b474d316ba9172778e18915` is held.
Six copied-runtime checks passed, but review found three ordinary behavior
gaps with direct production counterparts.

- A distinct Company ID could reuse a name from normal Sheets rename
  history. A known external row and the selected new row could also use
  the same normalized name. The current engine uses the name to select
  some saved job history. Reject ambiguous, current or historical
  ownership before import and recheck under the existing transaction.
- The source-revision eligibility helper treats blank Company status as
  Active. The ordinary admission command requires explicit Active.
  Importing the blank status could leave a durable retry that ordinary
  admission cannot run. Match the existing admission predicate before
  creating the event.
- The first preliminary read requested noninteractive credentials before
  the established manual command's interactive recovery. Preserve
  interactive authentication on the first read. Under-lock rereads
  remain noninteractive. Scope and identity errors still hold.

Root owns repairs in the private source copy. Independent QA retains
review ownership. Rerun the existing public-shell fixture and the
three changed boundaries. No production source, job records, workbook,
service or Jetson was changed.
