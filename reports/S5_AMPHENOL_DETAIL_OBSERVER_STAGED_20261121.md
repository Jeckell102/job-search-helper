# Amphenol detail response observation

**PASS source and offline.** The staged observer wraps only the detail
transport responses already returned to the approved normal dispatcher.
It records integer HTTP statuses, finite nonnegative Retry-After delays
through 24 hours (numeric or HTTP date), and a boolean for longer delays.
It does not retain raw headers or responses. It forwards the existing
calls, returns and exceptions and leaves the adapter's timing, retries,
source freeze, completeness and prior full-inventory comparisons intact.

- Evaluator SHA-256 `fb80eef5e864c3ee277a249c40e02aa0b78bad9ef4e6359c7609762bc26cf22c`
- Tests SHA-256 `8cd9ccfb2fcdd35151cfb64e598db895e9d607fc3c355db19906c0e3a9713507`
- Fourteen maintained offline tests and separate Playwright wrapper proof.
- Independent QA SHA-256 `826e1a5bac0e23366fd5e23750230f742fce076cc696d0286d6efa056586a97e`

The earlier RESULT_INITIAL.md describes the superseded narrower report
bound. The corrected observer has made no live request. The existing
zero-detail provider hold remains in force.
