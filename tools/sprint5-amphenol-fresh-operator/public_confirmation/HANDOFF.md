# Amphenol confirmation observer safety abort

The private evaluator now ends the qualification run at the first actual detail HTTP 429. It latches before returning that response to the unmodified AcquireTM client, retains a sanitized UTC observation and bounded Retry-After evidence, and raises a dedicated observer hold that passes through the client's ordinary Exception retry handlers. The outer evaluator emits `held_provider_rate_limit` and exits 1. No second request, body read, successful dispatch, or qualification follows that response.

| Evidence | SHA-256 |
| --- | --- |
| Updated evaluator | `6053756023435c7c82cbcfe56cabfde863e0397052537b393f9307105fe9e191` |
| Updated tests | `fc5320a4e02c96f0c853bef67da018b007e8984c61f50979730188295061f67f` |
| Offline test runner | `e47108feb281fd9fd52ae834d874ff3da37704fe3c7251e69676075034dbf13a` |
| Test result | `9ba3b609b01928bf21efd9377872d501c54b627081cf61c1d883c002be9376c0` |
| Source comparison | `e6dee3eef44b78fd45d44e031c3720f655a155b2dab9e35ed1a58d73c6d8f807` |
| Preserved actual provider hold log | `cd579326897e966e002e825f0bd4bf7b2d2b51ebef01b757097e965a805880cd` |

The actual prior log has 30 observed details, one 429 followed by two retry 429 responses, Retry-After values 3600, 3589 and 3577 seconds, and a blocked dispatch. It remains unchanged. The updated observer derives an uncapped UTC lower bound for parsed delays within the existing evidence bound. An absent, unreadable, or out-of-bound delay still holds and supplies no exact resumption time. No automatic retry is part of this tool.

All 22 offline tests passed. The tests use the actual pinned AcquireTM client's retry code with a fake request, show one outbound call on 429, and show unchanged ordinary 503 retry/cache handling and timeout retries. The evaluator-level fixture records a terminal hold and neither success nor qualification. AST comparison confirms the prior main source, detail/cohort, and verifier logic is identical apart from the held branch. The prior Retry-After parser is unchanged and the candidate adapter retains exact `895ec36e…` bytes. Neither the candidate nor installed adapter changed.

This is staged observer-only work for independent review and any separately approved future observation. No network, browser, production, or Jetson operation was performed.
