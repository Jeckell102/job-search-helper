# Sprint 4 retained Company-event outcome composition

The disposable signed event command now verifies the exact retained
publication, records one immutable outcome through the owned SQLite writer,
and then consumes the exact request. When a process stops before the writer,
the original request remains held. When it stops after the writer, replay
reuses the exact outcome and then consumes the original request. The event
identity uses the dedicated retained reservation digest; it does not enter
the coordinator's repaired release lineage. The selected receipt-v1 test
reached the actual disposable coordinator store, matched the complete sender
and receiver receipt payload, and recorded no repair task for a success.
The sender holds retained outcomes whose exact source revision is superseded.
The generic writer rejects fabricated ordinary-cycle outcomes for a real
durable Company event, and the sealed writer verifies exclusive ownership
inside its SQLite transaction.

A returned failed or partial fetch has a distinct outcome settlement with
bounded machine evidence. An interruption with no returned evidence remains
ambiguous and cannot refetch. A temporary response yields TEMPORARY, access
denial yields BLOCKED, and unknown capability remains held. Partial jobs stay
as evidence without selected publication or changes to job records. An
employer-verified zero has its own no-record settlement, creates no writable
Sheets client or review batch, and is distinct from ambiguous empty data.
Greenhouse recognizes an explicit numeric total of zero. The Samtec
Jobvite parser requires both an explicit no-openings indication and an
internally consistent zero listing on the bound board.

Independent recheck passed 81 focused tests and kept live use held. It
reproduced a generic-writer substitution and a crash after Sheets
confirmation before local acknowledgement. The first guard now has a local
regression. The terminal-only continuation remains in a separate worker
copy. A separate targeted test proves that an expired original signed claim
can be read back, that a forged signature cannot open Sheets, and that no
unclaimed suffix can be dispatched once approval expires. These tests and
the earlier 299-test combined run used disposable stores and no live
credentials or network.
