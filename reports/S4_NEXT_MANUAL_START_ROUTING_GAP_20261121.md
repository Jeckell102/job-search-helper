# Next manual start and Company-event routing

The current installed public `runner.main(['start'])` held a durable
eligible Company event in a private fixture. A real SQLite Company import
created the event in its repository transaction. Before bridging, the
entry reported that it was waiting for a bridged request. The existing
bridge then wrote and acknowledged the exact one-Company request. A
second ordinary start still exited with a hold for the queued event. It
preserved the queue bytes. Both invocations stayed outside the broad
scrape pipeline and workbook factory. Neither created a cycle.

| Source or fixture | SHA-256 |
| --- | --- |
| Installed `runner.py` | `de3c0f5045e1ad07d0b1e2e8b1da8b8dbce2acd3767182ddf9d1c7dbbaefb87b` |
| Installed `ordinary_company_event_command.py` | `f8765638f4a437a1a619bfe20161987f63b3f42bf508169850140ef9de0a1d9d` |
| Installed `company_intake_dispatcher.py` | `4f7181b4f701fefbb05db3803c53cd1c148832a73cbf6fc415773f9de6f57f85` |
| Installed `release_admission_bootstrap.py` | `1258ac47b647d61361fa84ccdda14816a184e6c15cd4c6e7c78e6b27cd228d45` |
| Private genuine-event fixture | `414d199f141dece18a2d05bbd4586d98b5be9070ae6cef931a156c6cbe53dbe2` |

This establishes an implementation gap in the ordinary next manual start
gate. The genuine Freeform event demonstrated the selected retained-cycle
route. The supervised dispatcher can claim a bridged request and launch
the exact ordinary event path under its own authority. Generic start
already owns its inherited scraper lock. Calling that dispatcher under
the lock would fail its own lock probe. A supported manual-start change
needs to route one exact ordinary request into the existing admitted
event fetch and publication path, before opening broad workflow factories.
Keep default-off supervised controls, existing operator requests, exact
source revision and all runtime proof requirements in force.

No production request was added. The installed local queue status said
“no pending request” at this checkpoint. Implement and verify the missing
navigation path in a private fixture before requesting live eligibility.

## Corrected routing stage, 15:47 Eastern

The private candidate at `/tmp/jsh-ordinary-start-gate-repro.20261121/candidate`
now adapts the measured bootstrap and the plain manual `start` entry. It
adopts one eligible event through the real existing bridge, or verifies
the already bridged request, while retaining the inherited scraper lease.
It invokes the existing exact admit/fetch and publish actions in the same
process, with their normal writer lease. When no matching event exists,
the existing startup route keeps its original ownership. Ambiguous inputs
hold without creating a request. Automatic intake settings are unchanged.

Independent QA initially reproduced a backend drift defect. Selection
could reach a backend-switching repository factory before the startup
layout was rechecked. The corrected source reads only the canonical
local SQLite Jobs store for selection and holds on backend drift. The
exact final stage passed seven independent tests, including a true private
Company event, the inherited admission, a real existing verified-zero
settlement, and a zero workbook-writer check. No live case was attempted.
[Independent candidate QA](S4_NEXT_MANUAL_START_CANDIDATE_INDEPENDENT_20261121.md).

The old startup suite was compared with the deployed and staged bootstrap
under the production Python 3.11 interpreter. Both had the same two
outdated fixture failures. The private fixture now supplies the valid
terminal receipt and measured inherited runtime expected by the existing
checks. All ten startup tests then passed against both bootstrap versions.
The old test inputs and their two failing test names remain in the
private reference directory. No production tests were changed.

| Updated staged input | SHA-256 |
| --- | --- |
| `release_admission_bootstrap.py` | `9cafc1f6b283d77e769640134756df7e67d81702789ada5e5b2381f427cef152` |
| `runner.py` | `4abc4fd6d7713294e0029fb770c3a5ffd57968569386ffaffd44f468cfcf2dd0` |
| `manual_company_start.py` | `8b9c0806968f40baa977d78fefe1f92899e1b7a558f2a74c0e8b02053e307b17` |
| `test_manual_company_start.py` | `7243e9e830deff0f0a053b45754abace72221813d09e0c322db0bfe89af8cbb8` |
| Private corrected startup fixture | `e13e64b3d0ff287ab6bbc33e4c9fb28320cec89e10534fc3272a623fcfc6c7cf` |

This source changes files that the separate -05 two-tool installer
expects to remain at their current versions. Keep the two native scopes
separate and remeasure the later installer and release binding before
considering a guarded manual-route deployment. The actual next-manual-run
gate still needs a genuine eligible live Company event, including
the interrupted and busy-to-next-manual evidence required by the roadmap.
