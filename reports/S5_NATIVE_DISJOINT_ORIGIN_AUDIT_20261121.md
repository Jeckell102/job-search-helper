# Native disjoint pilot and terminal-plan readiness

**HOLD. Zero usable owned origins and zero of the five terminal plans qualify.** At 2026-11-21 10:23:49 UTC, an immutable local read found 19 raw unfinished State scopes containing 801 distinct Companies. The only effective unfinished State cycle was `CYC-B639C6D864EC`. Its exact Jobs mirror and State both showed `In Progress`. The bridge outbox had one latest durable eligible event, already acknowledged by the exact bridge consumer. There were zero latest pending events of any kind. [Installed latest-event predicate](/home/chris/job-search-helper_old/src/job_search_helper/company_events.py:155) [Installed all-raw membership gate](/home/chris/job-search-helper_old/src/job_search_helper/retained_operator_scope.py:22)

| Reviewed matrix role | Active local Companies | Raw unfinished memberships per Company | Disjoint |
|---|---|---:|---:|
| Three incomplete completion cases | Forterra COMP-0066, Allen COMP-0164, Amphenol COMP-0490 | 19 | 0 |
| External/source holds and regression | GA-ASI COMP-0072, goTenna COMP-0110, PDW COMP-0178 | 19 | 0 |
| Proposed case held outside completion cohort | Draper COMP-0024 | 19 | 0 |
| Known-good baseline | Samtec COMP-0739 | 1 | 0 |

Each named control or case has one active local Company and a configured source. The matrix retains GA-ASI and goTenna as holds, PDW as the shared Rippling regression, and Samtec as the known-good control. Draper remains a held proposal. These source and test roles confer no new execution or completion eligibility. [Maintained matrix](/tmp/job-search-helper-integration-automation/temp/integration-coordinator/S6_SEQUENTIAL_MATRIX_AMENDMENT_20261121.md:13)

| Other at-end Companies | State and Inbox status | Saved legacy cursor | Exact publication receipts |
|---|---|---:|---:|
| COMP-0002, COMP-0008, COMP-0016 | Blocked, Inbox blocked bit true | 1/1 each | 0 |
| COMP-0040, COMP-0045 | Unsupported, Inbox blocked bit true | 1/1 each | 0 |

Each frozen plan holds exactly one Companies operation. Installed terminal qualification requires the exact plan-bound durable `SYNC_CONFIRMED` receipt once a plan exists, with the binding, records, and schedule all matching. The maintained test explicitly exercises the 1/1 cursor with a missing receipt. Both the exact selected planner and legacy migration intake reject the blocked inventory earlier. A legacy terminal label, local cursor, or unavailable provider cannot supply the required independently attributable selected-row confirmation. The pause gate also separately requires no unblocked saved work and a freshly revalidated manifest for every blocked saved inventory. [Terminal qualification](/home/chris/job-search-helper_old/src/job_search_helper/exact_recovery_terminal.py:55) [Maintained receipt test](/home/chris/job-search-helper_old/tests/test_exact_recovery_terminal.py:50) [Exact selected planner](/home/chris/job-search-helper_old/src/job_search_helper/exact_cycle_planner.py:834) [Legacy migration gate](/home/chris/job-search-helper_old/src/job_search_helper/exact_legacy_migration_runner.py:49) [Exact pause](/home/chris/job-search-helper_old/src/job_search_helper/exact_recovery_pause.py:137)

The minimum new data for the retained pilot is a genuine current eligible, unacknowledged Company event for an independently supported Company absent from all raw scopes. The current matrix cannot supply that event while held unchanged. Retained authorization and qualified normal-dispatch failure evidence remain separate admissions. For any of the five terminal plans, the missing prerequisite is the exact owner-bound receipt from an approved selected confirmation path. No such receipt or current eligible plan was observed.

All three local stores were read using SQLite `mode=ro&immutable=1` and `query_only` with empty or absent journals. Main and journal file identities and metadata matched afterward. No CLI, live API, provider, Google or writer was opened. [Sanitized snapshot](/tmp/jsh-s5-disjoint-origin-audit.OVgrH3CE/DISJOINT_SNAPSHOT.json)
