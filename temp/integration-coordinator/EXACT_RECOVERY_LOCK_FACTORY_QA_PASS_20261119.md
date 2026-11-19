# Exact recovery lock-owned lazy factory — independent QA pass

Date: 2026-11-19

Accepted source hash:
`915465b3d4bad56a8c8d719ead18ae6c6cfa5107cd06bcf7811f93ac2bd14d00`

Accepted test hash:
`985c020c19d914ecd7921597e616b0a7dcb7ba80aa0b4de3aa5bff5b020365cc`

## Result

PASS. This replaces, rather than repairs, the rejected escaping-capability
candidate documented in `EXACT_RECOVERY_LOCK_CONTEXT_QA_FAILURE_20261119.md`.

All public capability, registry, and ContextVar machinery was removed. The new
lazy dependency-context factory API validates the exact request, requires a
callable factory, canonicalizes a present regular State database, and acquires
the real normal scraper lock before invoking the factory exactly once. The
factory's context entry, dependency use, recovery, and context exit all occur
inside that lock. The yielded Engine's canonical State path must exactly match
the locked path before State, inbox, or remote access.

Independent tests prove invalid requests, invalid factories, missing or
nonregular State, actual normal-lock contention, and wrong Engine paths invoke
neither the factory nor protected access. Context cleanup finishes before lock
release on both success and exceptions. The existing direct recovery API keeps
its real-lock, explicit-selection, crash, and isolation behavior. No assertion
callback or reusable capability exists.

Independent focused and adjacent verification passed 120 tests in 6.75
seconds; compilation and `git diff --check` passed. No runner or live data was
changed.

