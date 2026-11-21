# Sprint 6 concrete sequential gate and preserved partial execution

2026-11-21. This lane identified and began one substantive gate: a typed external access hold followed by an unrelated successful ordinary event, using one disposable State/Jobs/Inbox set, one coordinator receiver, true two-sided delivery receipts, and the normal exact publisher. No application implementation change is needed for this gate.

Current result: **first event verified; second event publication not completed in this lane.** Root owns the remaining composed run in a separate copy and explicitly directed this lane to stop reruns. Both original private runtime attempts here remain preserved. No deployment acceptance is claimed.

## Exact reuse and actual versus substituted work

Source snapshot copied from `/tmp/jsh-s5-amphenol-host-trigger.gn2qvpsd`; every copied application/test pin is recorded in `SOURCE_PINS.json` and rechecked unchanged. Existing APIs are used directly: `SQLiteRepository.mutate_company_with_event`, `CompanyEventBridge.process_pending`, `ordinary_company_event_command.execute_ordinary_event`, `ordinary_event_outcome_settled`, and `ManualReceiptV1HostBridge.manual_drain`. Receiver storage is the real Coordinator/Store. The command holds real disposable scraper/writer file locks and the provider callback checks that exactly one application cycle owns the selected Company.

Existing proving fixtures are `tests/test_ordinary_event_no_publication.py:173` (typed block -> terminal local-only settlement), `tests/test_ordinary_company_event_publication.py:41` (exact publication and terminal replay), and `tests/test_ordinary_company_event_command.py:89` (actual command under admission lease). The existing coordinator FIFO test at `dev/wrapper-coder/tools/test_coordinator_queue.py:150` substitutes Coordinator.step and proves scheduler ordering only; it does not establish this event-to-storage join.

The access-denied response is deliberately simulated using the existing typed Inventory contract. The second Company's input is the previously captured, digest-verified Amphenol 39-posting inventory (`94250320f27fbf987f417405599f609de6ea965feb41f1b6297cfee57dba5fa8`). The workbook is RangeSheets through GoogleRepository, not Google. Runtime binding is explicitly the existing NO_RELEASE fixture binding, not native release measurement. There is no model or repair need for either BLOCKED or COMPLETE; the coordinator model rejects calls and no scheduler thread starts. This gate would prove application continuation around an external hold, not fresh live provider availability, three qualified repair structures, inference context reset, cumulative inference budgets, automatic deployment or installed Sprint 6 acceptance.

## Verified checkpoint

`runtime-corrected` contains one exact blocked cycle, terminal Complete with exceptions, and one BLOCKED outcome. The actual sender and receiver receipt bytes agree and report RECORDED_NO_REPAIR. There are zero repair intake rows and zero tasks. The second Company's eligible event was retained by the normal bridge while the first cycle was unfinished; the bridge returned WAITING_FOR_UNFINISHED_CYCLE with the actual first cycle ID, and no next-scan request was created. This is the correct one-owner policy. Original unrelated fixture job/opportunity inputs remain in the private stores; full after-second-event preservation is not claimed here.

`CHECKPOINT_RESULT.json` is a sanitized independent final readback of this first-event checkpoint. No provider network, Google, native process/service, Jetson, credentials, or production data was accessed. Copied application and test sources remain unchanged.

## Preserved driver corrections, not application defects

1. `runtime` and `first_driver_preserved.py`: first driver expected the second request file immediately. The actual bridge correctly held the second event in its outbox while the first cycle was active. The stopped run is preserved; the corrected driver checks that real policy instead.
2. `runtime-corrected` and `prove_sequence.py`: the first hold settled and actual delivery completed, then the driver asserted the wrong expected sink label OBSERVED_HELD. Existing ordinary BLOCKED delivery correctly returns RECORDED_NO_REPAIR, with no repair row/task. Root independently observed the same disposition and owns its corrected continuation. The application was not altered and this lane did not perform another replay.

Smallest remaining action in root's copy: keep the first terminal hold and receipts exact; let CompanyEventBridge bridge the same second event once; admit/freeze/publish that unrelated exact scope; deliver its outcome; prove 18 matching unique local/workbook keys, one write batch, one exact publication receipt, unchanged first outcome/receipt/cycle and unrelated manual rows, and terminal replay without provider/workbook access. Record the successful whole sequence separately if it passes. A real blocker should retain this minimal state rather than starting a broad fallback.

The latest roadmap still requires Sprint 5's genuine production origin and qualified installed chain, three distinct unfinished qualified companies, current cumulative-budget/restart/supervision observations and independent deployed QA. The accepted Sprint 2 single-lane interruption evidence and the 103/114 maintained source tests remain reusable evidence; neither closes those deployed sequential gates.
