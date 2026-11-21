# Independent AcquireTM typed diagnostic QA — 2026-11-21

**ACCEPT the exact source-only typed pagination observation.** No blocking
finding in step 1 of the automatic-launch disposition. This does not accept
a generated wrapper, a qualified terminal repair outcome, deployment or launch.

Frozen author tree: `/tmp/jsh-s5-acquiretm-typed-pagination.DH7aHdwu`.
Independent source copy and probes: `/tmp/jsh-s5-acquiretm-typed-independent.c189s4w5`.

| Reviewed file | SHA-256 |
| --- | --- |
| `src/job_search_helper/acquiretm.py` | `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61` |
| `src/job_search_helper/ats.py` | `111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e` |
| `tests/test_acquiretm.py` | `dca8d436b5c7840beecba2c14b6ffc01d4d279adab3a5fb5083d681713d891f1` |

The producer retains the original click and premature-wait behavior. It
considers evidence only on the first advertised page-two transition, with
the exact pre-click and premature rows and total unchanged. One bounded
observation of that same click then requires nonempty disjoint same-board
IDs, unchanged total, a combined count within that total and completion
within the 12-second observation budget. It performs no second click,
navigation or detail request in this branch. Exact board URL and parsed
posting identity remain required. See `acquiretm.py:74-149`.

The result deliberately remains `partial` with zero jobs, carrying the
bounded closed failure envelope. The full normal-dispatch immediate-refresh
case still completes through details and final reread without this type.
Neither 39 nor 25 is hardcoded as current provider membership.

## Independent verification

- **56 maintained tests passed**, independently rerun against the frozen
  copy: AcquireTM, outcomes and scrape-outcome producer (0.889 seconds).
- **Four new independent tests passed**, with subcases (0.181 seconds).
  Positive normal dispatch records exactly listing, one click, original wait,
  membership observation and close, while staying partial with zero jobs.
  Malformed or empty refreshed listing, overlapping IDs, excess membership,
  rate-limit content, changed board scope, deadline overrun and a transport
  exception produce no typed proof. Foreign Company ID or label does not
  enable the diagnostic.
- Readback rejects extra fields, wrong page, boolean/nonsensical counts,
  negative or excessive timing, mismatched premature digest and an unchanged
  refreshed digest. Returned evidence is copied without mutating its input.
  Existing access-denied and temporary-transport envelopes retain their exact
  grammar. See `ats.py:123-179` and the independent probe file.
- The generic outcome producer still interprets this new envelope as
  `unknown`, verified directly. Typed source evidence cannot itself promote
  or launch a repair. The next owned-attempt settlement remains separate.

System Python 3.11 executed disposable unittest fixtures with bytecode off
and socket connection/DNS helpers blocked. Playwright behavior was simulated;
the tests do not prove a live employer transition or actual browser timing.
No production checkout/state/service, task, Jetson, provider, Sheets, release
or GitHub was accessed. The author source was not modified. The independent
test is `tests/test_independent_typed_pagination.py`; copied source pins are
recorded in `SOURCE_PINS.json`.

Further generated-wrapper/recipe and owned-settlement work needs its own
independent acceptance. Preserve this diagnostic report as distinct evidence.
