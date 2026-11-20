# Sprint 4 ordinary Company-event exact plan binding

Staged in `/tmp/jsh-s4-ordinary-plan.Zn9E6xCO`. The ordinary plan uses the existing compact exact-v2 sealer and Inbox plan persistence. Ordinary binding is explicit. Legacy, default compact and selected-retry receipt bytes and IDs are covered by compatibility tests.

## API and durable shape

1. Under the existing scraper and writer leases, call `load_ordinary_event_plan_context(local_reader, state_reader, runtime, cycle_id=..., request_sha256=...)`. It calls the durable ordinary observation loader. That verifies the exact admission archive, bridge receipt, acknowledged SQLite outbox event, State/mirror and runtime, then verifies the saved provider observation and source. The context is detached and read-only. On restart, rebuild it from the same durable identity.
2. Call `ordinary_event_plan_payload(context)` to get the deterministic Inbox projection. It sets `inventory_status` from the original returned status, leaving typed failure and positive-zero evidence in the separate frozen observation. The exact planner requires nonempty complete/partial inventory. Complete observations with unfinished browser work hold before planning. The owner verifies fresh source and Inbox ownership before saving the exact payload; the planner reads that saved payload and compares it to the observation. It does not insert or replace inventory.
3. Pass `ordinary_event_context=context` to `freeze_exact_cycle_plans` with the one Company and the existing bounded workbook Company guard. The planner checks the canonical State/Jobs/Inbox, compact profile, workbook identity, current runtime, admitted Company and latest event revision. It repeats the currentness/ownership check after the read-only workbook guard. It freezes the v2 plan/marker only. Jobs and the State checkpoint are unchanged at this boundary, and no publication receipt is inserted yet. The Company finisher may update ordinary scan control fields. The five protected identity and source fields are carried without mutation. Equivalent status/ATS values are omitted and any actual Company ID, name, status, board or ATS change holds before plan creation.
4. Pass the same verified context to `derive_receipt(..., ordinary_event_context=context)` at each ordinary-event receipt derivation. Leave `request_id` absent or pass the exact archived `company-event:<CEV>` string. The function verifies the v2 plan seal, payload, remote fingerprint stream, protected Company fields, exact scope and marker. The ordinary schedule uses the original queue materialization timestamp. It describes the safe request slot and adds no idle/busy measurement claim. [Context and derivation](/tmp/jsh-s4-ordinary-plan.Zn9E6xCO/src/job_search_helper/exact_cycle_receipt.py:35) · [Planner](/tmp/jsh-s4-ordinary-plan.Zn9E6xCO/src/job_search_helper/exact_cycle_planner.py:788)

`plan['ordinary_company_event']` is exactly the object returned as `receipt['binding']`:

- `authority='ordinary-company-event-exact-v2'`
- `cycle_id`, `request_id`, `request_sha256`, `request_fingerprint`
- `company_event_id`, `company_id`, `source_revision`
- `bridge_receipt_sha256`, `observation_sha256`, `provider_inventory_sha256`, `workbook_id_sha256`
- `release_id`, `release_binding_sha256`

`provider_inventory_sha256` refers to the original full provider observation inventory. `plan['inventory_payload_digest']` separately refers to the projected Inbox payload. The plan seal covers the entire marker. The existing public receipt ID function uses request/Company/source/release and the full runtime-binding digest. The stored receipt additionally compares the entire immutable binding, record fingerprints, and schedule. None of these new fields are inserted into the old receipt types.

## Coordinator wiring and one guard gap

Thread the context through the ordinary-owned calls to exact planning, local-verified receipt derivation and publication/recovery. The current `exact_cycle_sync._fallback_receipt` overrides the request ID with the cycle ID for default exact-v2, and existing `exact_cycle_recovery` calls derive without a verified ordinary context. Those calls deliberately refuse the new ordinary plan until the scoped caller implements the explicit branch. Retain the original IDs in the Inbox completion archive and check the marker against archived event/observation evidence before existing cleanup. Owner command, exact publication guards, archival and settlement remain outside the two-module change. [Current default fallback](/tmp/jsh-s4-ordinary-plan.Zn9E6xCO/src/job_search_helper/exact_cycle_sync.py:33) · [Current local verifier caller](/tmp/jsh-s4-ordinary-plan.Zn9E6xCO/src/job_search_helper/exact_cycle_recovery.py:126)

**Pre-intent generic reconciliation needs an explicit ordinary-authority hold.** The existing generic checks look up an exact-local row with `binding['request_id']` as its cycle key. Here that is a real `company-event:…` request ID and the exact application uses the separate `binding['cycle_id']`. A receipt can exist after local verification and before the remote intent row exists. Close that window in the owning guard before enabling execution. Reject this ordinary authority unconditionally in compatibility reconciliation, or verify it from the durable stored receipt by its receipt ID and exact cycle key so stripping a metadata field from a supplied binding cannot downgrade it. The plain legacy/default/selected receipt identities keep their established derivation. [Inbox compatibility guard](/tmp/jsh-s4-ordinary-plan.Zn9E6xCO/src/job_search_helper/inbox.py:1750) · [Low-level compatibility guard](/tmp/jsh-s4-ordinary-plan.Zn9E6xCO/src/job_search_helper/publication_receipts.py:184)

## Test commands and results

**110 passed** in the disposable combined planner, exact sync, exact recovery, ordinary fetch and new binding suite. The cases cover real local admission/frozen observation, clean plan freeze/replay, private marker digest and archive bindings, unchanged State/Jobs, refusal of legacy or altered bindings and stale/ABA source, fresh guard drift, source-preserving finisher behavior, and receipt identity compatibility.

From `/tmp/jsh-s4-ordinary-plan.Zn9E6xCO`, set `TMPDIR` to its `test-work` directory, set `PYTHONPATH` to its `src` and root, and use `PYTHONDONTWRITEBYTECODE=1`. The final run used the workspace Python with the following script. The separate receipt candidate's title-list files were read as fixture policy because this minimal source copy lacks them.

~~~python
from pathlib import Path
from job_search_helper import efficiency
import pytest

rules = Path('/tmp/jsh-s4-receipt-candidate.i8gYgB0N')
efficiency.BLACKLIST_PATH = rules / 'title-blacklist.txt'
efficiency.REVIEW_LIST_PATH = rules / 'title-review-list.txt'
raise SystemExit(pytest.main([
    '-q', '-p', 'no:cacheprovider',
    '--basetemp=/tmp/jsh-s4-ordinary-plan.Zn9E6xCO/test-work/combined',
    '--tb=short', 'tests/test_ordinary_event_receipt_binding.py',
    'tests/test_ordinary_company_event_fetch.py', 'tests/test_exact_cycle_planner.py',
    'tests/test_exact_cycle_sync.py', 'tests/test_exact_cycle_recovery.py',
]))
~~~

Only the following source/test files were edited. The main candidate and production were untouched, and all tests used offline fixtures.

| File | Original SHA-256 | Staged SHA-256 |
| --- | --- | --- |
| src/job_search_helper/exact_cycle_receipt.py | `358d2b78c3976f751efb613f859c616eedc26e16c44e488eb7ad08fbc0f88de9` | `90abd2e37d59c96bd1f9705b16bec29f42e9f7f77cb286d70bc1fd8057cd8bbb` |
| src/job_search_helper/exact_cycle_planner.py | `62c4bf1aa2fc0ba5c2577f1675e7fd8256dc2ecd7982ed9687fce48655223fcb` | `b0aff54d63a97b77791f373ff622d56d3cba3caa573c31c2bc61981c11f8115c` |
| tests/test_ordinary_event_receipt_binding.py | `new` | `1e5cfd9a3a359d3db120f2d86693db995071f9a0eda4a21937aa311cacb8c0fe` |
