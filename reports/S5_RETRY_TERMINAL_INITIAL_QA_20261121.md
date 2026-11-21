# Independent terminal repair-retry outcome QA

**REJECT the current terminal authority.** Honest completion and replay pass, but two public writer boundaries accept outcomes outside their exact proof.

| Reviewed file | SHA-256 |
| --- | --- |
| `exact_cycle_receipt.py` | `f977e1410e20816af95ab72f9b84fb23e957fcd786768448b2c5c0df4b985dc6` |
| `scrape_outcome_producer.py` | `a88c2f970950992ca376bc58eb17710b851e5c042e231baa7e1d9eafa7bac181` |
| `sqlite_repository.py` | `e5df00fe024d4eb44023cd498b5684673157d4e6dd0f1760d20bf412d2fdf77f` |
| `runner.py` | `482c202b123d0f57ef2d9e0297532e25bc9f2c1ee6aac613879946517bd85188` |
| `check_existing_scope.py` | `0a16b8ee36270df05073fd01cb5091e8039892159199c91f91a1825ba6ccecce` |

1. The generic writer allows a new `COMPLETE` record for the actual released-retry cycle under an alternate unprefixed request when the caller retains the actual attempt and omits the remaining release lineage. The independent probe replaced the scratch Jobs acknowledgement with a foreign value before calling the generic writer. The writer accepted the record as `COMPLETE`. The durable cycle ownership must reserve this positive outcome path alongside the recognized caller identity fields. [Generic writer](/tmp/jsh-s5-confirmed-retry-outcome.20261121/src/job_search_helper/sqlite_repository.py:856)
2. The dedicated writer accepts a Jobs database at a different physical application directory when it contains a copy of the exact ack and uses the same workbook identifier. The State and Inbox were kept in the original scratch root. The writer returned `COMPLETE` from the different Jobs path. It checks State-to-Inbox co-location and workbook identity. It needs to verify the Jobs store belongs to that same application authority. [Dedicated writer](/tmp/jsh-s5-confirmed-retry-outcome.20261121/src/job_search_helper/sqlite_repository.py:879)

The supplied harness failed on the baseline because removing the ack still allowed a positive outcome. The candidate passed it and replayed one immutable COMPLETE with one receiver `VALIDATED_COMPLETE` lifecycle event. Direct independent cases held a caller-provided Complete cycle with durable `In Progress` State, a foreign acknowledgement ID, and an Inbox with a different destination. The generic writer also held a caller-supplied full retry lineage under an alternate request. The two rejection cases above remain reproducible on the same source pins.

All checks used copies of the completed disposable fixture and denied outbound transport. No production runtime, remote workbook, or resolver was accessed.
