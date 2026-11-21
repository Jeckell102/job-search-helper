# Amphenol normal-runtime Retry-After gap

The independent qualification observer stopped immediately on the actual
HTTP 429 and preserved the one-hour Retry-After. Earlier, the same
candidate's stock detail client received three actual 429 responses within
23 seconds, despite Retry-After starting at one hour. The observer
deliberately prevents those stock retries during public qualification.

Root exercised the exact generated candidate `895ec36e…` offline through
its `_DetailClient.get_body`. A fake response returned HTTP 429 and
`Retry-After: 3600` for every request. An injected recorder replaced sleep.
The client requested three responses and its longest requested sleep was
eight seconds before giving the correct final `blocked` classification.
No provider calls were made. This is an operational cooldown gap in the
normal client, separate from the repaired pagination regression.

Preserve the current candidate and its model/build provenance. Before the
normal automatic retry policy is accepted, verify that a provider-imposed
hold cannot cause another immediate request or a repair dispatch. The
existing company-specific hold should carry the server deadline through
the normal outcome and retry boundary. Prefer the smallest maintained
transport correction over another identical live qualification attempt.
Any source change requires a new exact scope and version evidence. This
finding does not give the fresh wrapper installation authority.

[Current independent 429 capture](S5_AMPHENOL_FRESH_PUBLIC_INDEPENDENT_QA_20261121.md)
· [Earlier three-response evidence](S5_AMPHENOL_PUBLIC_429_HOLD_20261121.md).
