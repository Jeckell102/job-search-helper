# Independent manual-start gate review

**Confirmed gap.** The private test passed against the installed `runner.main`. Bare `start` returned 1 for a genuine, current, eligible Company event before bridging. The real bridge then wrote and acknowledged that one request. A second bare `start` still returned 1; it preserved the exact queued bytes and created no cycle. The private fixture would fail on broad workflow or Google access.

Use one pre-broad bare-`start` branch in `runner.main`, after stable bootstrap has acquired the scraper lease. For compatible SQLite bare starts, carry the bootstrap’s existing co-located State and Jobs identity in the inherited admission so the branch can reuse `_retained_operator_admission()` once. Select just the exact current ordinary request. For a uniquely eligible unbridged event, reuse `CompanyEventBridge.process_pending(limit=1, writer_lock_held=True)` under verified inherited scraper ownership, after ensuring the bridge’s next event is the selected eligible event. For an existing ordinary queue, use the existing exact request and acknowledgement checks. Feed the canonical JSON request digest to the measured `execute_ordinary_event('admit-fetch', ...)`, and use its exact cycle and the existing publication and crash continuation. Keep the lease across this dispatch and let the exact operation take the writer lease in its normal order. A nested bootstrapped process would try to take the scraper lock that `start` already owns.

Leave the broad `start` guard in place for all other start modes. Ambiguous or foreign, stale, retained, or already adopted work holds or reports its exact continuation. The manual branch should leave the durable auto-intake controls alone. This review reproduced the gap and traced the proposed composition through installed source. It did not implement or run the new route, access live state, fetch provider data or open Sheets.

| Artifact | SHA-256 |
| --- | --- |
| Reproducer | `414d199f141dece18a2d05bbd4586d98b5be9070ae6cef931a156c6cbe53dbe2` |
| Independent result | `c8195e475881a53aa3b3b955f23e19b19838d952648311a45cd875e464ca9720` |
| `job-search-scraper` | `8fb9939560f004a213ca94724cdada7734996072c31194679017fea492841f72` |
| `release_admission_bootstrap.py` | `1258ac47b647d61361fa84ccdda14816a184e6c15cd4c6e7c78e6b27cd228d45` |
| `runner.py` | `de3c0f5045e1ad07d0b1e2e8b1da8b8dbce2acd3767182ddf9d1c7dbbaefb87b` |
| `ordinary_company_event_command.py` | `f8765638f4a437a1a619bfe20161987f63b3f42bf508169850140ef9de0a1d9d` |
| `company_events.py` | `0c82c1091b413622f0fc4a727225efcd3792598e527d0731e78d3d427b5d265b` |
