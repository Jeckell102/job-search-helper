# Independent QA: owned Amphenol choice-input readback

2026-11-21. **ACCEPT for the narrow source-only reader.** No concrete implementation gap found. The accepted pure projection was treated as an existing dependency. No native execution, model/provider/Google call, scheduler start, or candidate modification occurred.

Candidate: `/tmp/jsh-s5-owned-choice-readback.PpzW7IwU`.

- `dev/wrapper-coder/tools/amphenol_recipe_choice_input.py`: `d39cb05301361be828df8a4e81b2937e3012f9cffb7971e9183edd9516f21b5b`.
- `tests/test_amphenol_receipt_choice_input.py`: `a1cb063b4ec0f5495d70abff776344356b2263b9ed3297446c2144390ea00621`.

Both pins match the original candidate and the private test copy after execution.

The new extraction uses the actual Inbox destination, then the read-only Jobs constructor verifies its saved workbook identity. It does not select a workbook from the environment. It reads exactly the selected sender delivery row, uses existing OutcomeDelivery preflight for canonical record/receipt and acknowledgement integrity, verifies current ordinary settlement, reads the exact admitted frozen observation, and obtains the current Company repair snapshot. The receiver receipt, exact intake, and held repair view share one read-only SQLite transaction; the receiver receipt must equal the sender's acknowledged receipt. The accepted projection then pins the exact Company, request, release-independent ordinary-event identity, frozen observation and witness, held status, and absence of a promoted task.

`read_owned_choice_input` returns None unless explicitly enabled with the boolean True and a valid selected outcome ID. Missing, stale, inconsistent or unavailable owner evidence is caught and held; enabling does not convert a mismatch into input. It returns a proposed one-call review input only. It never invokes the model, creates a task, schedules, promotes or resumes work.

## Offline verification

Ran from `/tmp/jsh-s5-owned-choice-independent.bnvqa0l4`, using explicit system Python 3.11 with isolated source/test paths, no bytecode or plugin autoload, and an audit hook denying network/DNS operations.

- Maintained composed ordinary-event/Coordinator delivery test: **1 passed in 0.91s**. This supplies actual disposable State, Jobs, Inbox, frozen observation and sender/receiver ledgers; verifies the positive exact input; holds foreign receiver/mismatched receipt/current source drift; and checks no model call, no tasks and no scheduler thread.
- Independent `test_independent_owned_choice.py`: **3 passed in 1.21s**. Disabled and invalid-selection paths cannot call the extraction. Enabled legitimate extraction succeeds while every SQLite open is required to use mode=ro and SQL data/schema writes are denied by an authorizer. Corrupting the actual sender receipt hash or changing the actual Inbox workbook ID each produces None with enabled=True and leaves the task table empty.

One initial independent assertion used the maintained test's intentionally blocked Store.connect convenience method; the assertion was changed to a direct read-only count in this QA fixture. The candidate was unchanged and both negative dispositions already held before that fixture-only assertion correction.

The caller must still provide the trusted owner paths and hold the normal application leases, as documented by the helper. The helper neither acquires those leases nor grants live-call authority. This review establishes logical read-only behavior under that existing contract, not a new cross-database snapshot or native launch contract. Root's separate genuine-public fixture readback was not modified or rerun by this reviewer.
