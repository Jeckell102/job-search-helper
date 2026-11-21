# Saronic operation 194 ownership delta

**Verified local candidate transition. Installed recovery remains held.** At 10:16:53 UTC, the immutable State, Jobs and Inbox snapshot reproduced the guarded preflight’s one Job History ownership exception among 105 Job History operations. The 1-based operation 194 lies after saved cursor 67 of 208. Its unchanged Job Key and Company match the unique local row. Its explicit expected-before Source Hash equals that row’s current Source Hash, while its `values` declares a different Source Hash. The operation is marked append-if-missing, and its keyed target is already present. [Guarded preflight](/tmp/jsh-s5-retained-native-preflight.20261121/RESULT.json)

| Exact same-job evidence side | Durable local evidence rows | Matching retained plan operations |
| --- | ---: | --- |
| Current source | 1, same Company | 0 |
| Proposed source | 0 | 1, operation 195. Same Company and exact Job Key/Source Hash identity, append-if-missing, after cursor 67. |

The installed control-before-prefix route reads explicit ownership from `identity`, `on_insert` and `values`. The expected-before guard is outside that extraction. For each present Job History operation with explicit ownership, the validator requires the existing Job Key, Source Hash and Company to equal the explicit values. Operation 194 therefore fails with `control_before_prefix_job_ownership_mismatch` before candidate binding. The existing metadata-only derived guard is scoped to operations with no explicit owner and with append-if-missing false. [Explicit and metadata-only guards](/home/chris/job-search-helper_old/src/job_search_helper/exact_control_before_prefix_recovery.py:96) [Present-row validation](/home/chris/job-search-helper_old/src/job_search_helper/exact_control_before_prefix_recovery.py:145) [Binding order](/home/chris/job-search-helper_old/src/job_search_helper/exact_control_before_prefix_recovery.py:245)

The exact local old-value guard and adjacent paired evidence identify a coherent candidate source transition. Remote authority remains separately held. The existing successor is explicitly local-only, and the snapshot establishes neither workbook state nor continuity to the original documented conflict fingerprint. Salary has no role in the observed mismatch. [Installed successor authority fields](/home/chris/job-search-helper_old/src/job_search_helper/exact_control_before_prefix_recovery.py:302)

All three main file and journal identities stayed stable across SQLite immutable/query-only reads. Journals were empty or absent. No recovery route was invoked. The evidence contains only counts, booleans, positions and hashes. [Sanitized delta](/tmp/jsh-s5-saronic-194-independent.95rXbu8O/DELTA.json)
