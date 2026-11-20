# Sprint 4 selected outcome delivery checkpoint

The coordinator staged one receipt-v1 delivery route in
`/tmp/jsh-s4-receipt-candidate.i8gYgB0N`. SQLite reads only the requested
outcome when an exact ID is supplied. Receipt reservation, durable receiver
acknowledgement, stale suppression and restart behavior still use the
existing implementation.

The staged host accepts an explicit selected outcome only when it matches
its configured single-outcome scope. The ordinary startup catch-up and
unscoped drain leave the backlog held without opening a sender. Delivery
uses the existing local writer lock, checks for a retained lifecycle hold,
and records the receiver's exact receipt. It cannot promote or start a
repair task. The legacy in-process and fixture APIs are unchanged.

The coordinator ran 46 focused tests across sender, receiver, host bridge
and coordinator resilience. They cover an unchanged unrelated pending
outcome, exact replay, disabled or wrong scope, stale suppression and a
lost receiver acknowledgement. Production host source and configuration
are unchanged. No outcome was delivered in the live environment.

The application still needs a trusted Company-event producer and a composed
safe intake/consumption gate. The intake worker owns its isolated fixture.
The outcome worker owns the isolated producer and classification modules
and their tests. The coordinator owns the shared runner, SQLite and wrapper
integration. Independent QA remains separate. Keep the S3 Samtec run and
its historical record checks separate from these Sprint 4 source changes.
