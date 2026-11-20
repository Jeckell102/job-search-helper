# Independent QA for closure acknowledgment

2026-11-20 16:40 EST

**ACCEPT for staged source.** No required source repair found within the acknowledgment review. No host deployment was reviewed or performed.

- New closure persists the completed `closed` record and waits for the control directory sync before publishing `closed-acknowledged`. The acknowledgment therefore attests to the earlier closure sync. An interruption during the second directory sync can leave an observable acknowledgment of the first sync. The acknowledgment record's own persistence remains uncertain until its sync succeeds. `host_exchange.py:334-343`, `host_exchange.py:424-437`.
- The parser accepts legacy `closed` with all pairs completed and no proof, but witness and new restoration require acknowledgment. An explicit close replay syncs the control directory, verifies the completed placements and publishes acknowledgment when needed, without swapping the completed pairs. Restore rejects unacknowledged closure before asking the terminal verifier, and existing restoration replay still requires the matching terminal digest and verifier. `host_exchange.py:345-357`, `host_exchange.py:396-437`, `host_exchange.py:439-469`.
- Independently ran the two existing sync-interruption cases. Both passed in 0.23 seconds in a fresh `/tmp` pytest directory. The first failure leaves visible `closed`, which witness and restore refuse. The second failure leaves visible acknowledgment after the successful first sync, which witness accepts. Both close replays preserve the completed placements without another swap. The coordinator separately reported 84 passing tests. `test_alternate_exchange_witness.py:80-122`.

The new reader can carry forward an older complete closure via explicit replay. A rollback to the earlier reader while an acknowledged record is present would leave that record unrecognized. Actual host use still depends on verified continuous exclusive control of the approved paths and policy from closure through the release and authenticated restoration decision.
