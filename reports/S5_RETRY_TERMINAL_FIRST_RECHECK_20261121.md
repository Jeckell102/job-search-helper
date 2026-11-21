# Corrected terminal outcome authority recheck

**REJECT this revision for the complete authority contract.** The original two rejection cases now hold. The generic writer still accepts two variants of a `COMPLETE` alias for a known released retry cycle.

| Reviewed file | SHA-256 |
| --- | --- |
| `sqlite_repository.py` | `350b5886fb543848137c06c178c0f5a54ffd6a86d5fa36ac6ba2634530bd97f6` |
| `exact_cycle_receipt.py` | `f977e1410e20816af95ab72f9b84fb23e957fcd786768448b2c5c0df4b985dc6` |
| `scrape_outcome_producer.py` | `a88c2f970950992ca376bc58eb17710b851e5c042e231baa7e1d9eafa7bac181` |
| `runner.py` | `482c202b123d0f57ef2d9e0297532e25bc9f2c1ee6aac613879946517bd85188` |
| `check_existing_scope.py` | `0a16b8ee36270df05073fd01cb5091e8039892159199c91f91a1825ba6ccecce` |

The honest default fixture passed the unchanged harness and replayed one COMPLETE and one receiver `VALIDATED_COMPLETE` event. The prior alternate request retaining the real retry attempt held. In the default layout the generic writer also held a no-lineage alias for the same retry cycle and Company, including a casefolded complete status. The dedicated writer held Jobs clones both in a different directory and with a different filename alongside State. Honest dedicated completion succeeded for an explicitly configured split Jobs/State layout.

1. That same explicitly configured split layout still accepts a new generic `COMPLETE` under a different request for the known retry cycle with all retry fields omitted. The independent test changed the scratch Jobs acknowledgement to a foreign value before invoking the generic writer. The dedicated writer checks the configured State path, while `_source_configuration_evidence` used by the generic guard only checks fixed sibling `state.db`. [Generic and dedicated authority checks](/tmp/jsh-s5-confirmed-retry-outcome.20261121/src/job_search_helper/sqlite_repository.py:856)
2. In the default layout, changing the generic alias to another Company also allowed a new `COMPLETE` for the known retry cycle. The generic lookup asks for evidence for the caller's Company, and the true sole-owner cycle has no such item. A positive generic write cannot use a known released-retry cycle even if its caller supplies an unrelated Company. [Current ownership read](/tmp/jsh-s5-confirmed-retry-outcome.20261121/src/job_search_helper/sqlite_repository.py:974)

An exact owned-cycle lookup can use the configured State association where valid, fall back to the supported fixed sibling layout, and recognize released-retry ownership before inspecting the caller's Company. The original report remains separate. All probe writes were in copies of the disposable archives. No native or remote operations occurred.
