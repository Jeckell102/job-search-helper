# Sprint 4 selected retry terminal settlement independent recheck

**ACCEPT all four original repairs. HOLD source integration for a remaining Lever source-scope mismatch.**

## Remaining blocker

The selected retry compares recognized Lever URLs by adapter name and board slug alone. It discards the regional API root and the adapter's effective location filter. With the official workbook/Company URL pinned to the EU board for Berlin, the actual terminal decision accepted a typed failure from each of three alternate returned URLs under the same board slug. These changed only the API region, changed only the location to Boston, or omitted the location. All three returned the same HELD_TEMPORARY_RETRY_CAP decision as the correctly scoped control. This was a direct disposable probe of the terminal decision. Source inspection shows the fetch-side return check uses the same identity helper, so it also cannot distinguish the mismatches.

Include the resolved regional API root and normalized effective location in the selected Lever source identity. Keep matching public-board and API representations equivalent when they resolve to the same region and filter. Verify that wrong-region, wrong-location and omitted-location returns cannot settle the selected cycle or produce a terminal outcome. [Selected provider comparison](/tmp/jsh-s4-terminal-recheck.6zqm1rTp/src/job_search_helper/selected_temporary_retry_execution.py:26) · [Fetch-side use](/tmp/jsh-s4-terminal-recheck.6zqm1rTp/src/job_search_helper/selected_temporary_retry_execution.py:119) · [Terminal decision](/tmp/jsh-s4-terminal-recheck.6zqm1rTp/src/job_search_helper/selected_retry_terminal.py:118) · [Lever scope parser](/tmp/jsh-s4-terminal-recheck.6zqm1rTp/src/job_search_helper/ats.py:537)

## Accepted boundaries

- A supplied malformed failure with an otherwise valid Samtec zero marker was rejected during snapshot creation. The provider was called once, the fetch remained claimed, publication produced no successor outcome or receipt, and replay refused another fetch.
- Recognized Greenhouse public/API source proof still works for the pinned board. An unrelated host with that board slug and a claimed Greenhouse adapter no longer passes.
- Frozen file corruption injected after the fake workbook read was detected before a Jobs write. Receipt and successor outcome stayed absent, and State stayed queued. A local retry veto introduced during the read was also rejected.
- A historical canonical outcome with an aliased request and the exact successor cycle was rejected before workbook access. The alias and queued State were preserved, and no second outcome or receipt was created.
- The focused suite still covers Jobs rollback, both sides of the final State checkpoint, and signed nonempty exact publication. The independent valid cap probe verified one terminal outcome and durable receipt, identical replay, preservation of unrelated data, one fixture provider call, and zero workbook write batches.

## Evidence

The supplied source snapshot was /tmp/jsh-s4-terminal-recheck.6zqm1rTp. Its 766 source, test and dev files matched the disposable copy by path, mode and SHA-256. The inventory digest was 2da9e2a0781b97e78c581033d8d60490475b0141b1aeed318f842d5354c5ac1e. All 153 regressions passed in 56.83 seconds. Ten independent fixture cases ran, including the four inverted regressions and the three remaining Lever reproductions. The earlier HOLD report remains intact. No production, live Sheets, services, Jetson, credentials or GitHub operations occurred. [Independent fixture](/tmp/test_jsh_s4_terminal_recheck_diYARL0M.py) · [Original QA report](/tmp/jsh-s4-terminal-settlement-independent-qa.md)
