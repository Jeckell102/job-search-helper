# Exact shutdown-generation accounting for the next source forward

Status: source and disposable composition only. No native entry wiring, source deployment, service action, database mutation outside a disposable fixture, or observer request. The -16 transaction and rollback closure remain separate and unchanged.

Files:
- `five_tool_forward.py` SHA256 `fcb67f16c7ef33876b6450c1fed6cc55e6fa94496f7c040220f3972c54806c91`.
- `test_five_tool_forward.py` SHA256 `037e3fd718656df2c26ffd573760988a82171c90f8f392051629d7c5be7f9299`.
- Root-owned dependency, not edited here: `measure_generation_custody.py` SHA256 `dd5aa6ce904e867edb62255f4401e3848578038abab365be46408cb4d57a51e5`.
- Original copied adapter remains unchanged at `/tmp/jsh-embraer-03-continuation-release/five_tool_forward.py`, SHA256 `6d0e16123ddee3e48e37ad0707a70b117e8770f0f49054187ed6cae860ff24f6`.

## Callable

The existing `apply_five_tool_forward` keyword interface gains only optional `snapshot_transition=None`. With no callback, original exact snapshot equality and receipt shape are retained.

Pass a measured callback:

`snapshot_transition(before, after, *, expected_generation_delta) -> nonempty verified proof dictionary`

The adapter invokes it after the real restart readback. A successful one-stop forward, or a one-stop explicit rollback, requires delta 1. A failed forward compensated through the second orderly stop/start requires delta 2. A different shutdown history is held; this is not an automatic repair of an interrupted earlier transaction.

The supplied `verify_generation_transition` requires an exact nonnegative integer `control_generation` at snapshot top level and exactly the requested increment. It compares canonical representations of every remaining snapshot field, rejects all other differences, and returns before/after generations, exact expected delta, both snapshot digests, and a common protected-evidence digest. It never writes or resets a generation.

The original approved snapshot is still checked before any write and retained unchanged in the durable intent. The final receipt additionally records `snapshot_verification` with actual original/final snapshot digests and the returned proof. Existing source scope, owner, historical receipt, before/after file, unrelated-sibling, rollback and replay gates are unchanged.

## Native integration boundary, not implemented here

Root's read-only `measure_generation_custody.measure()` hashes all original tables and raw rows, separates only the canonical generation row, validates current supervision, and permits only the empty continuation table. The native snapshot may remove only its `continuation_table_exists_and_empty` bookkeeping flag as before, while preserving that helper's validation.

If the complete native snapshot nests this measurement under `existing_coordinator`, use a pure comparison callback that copies each entire input snapshot, lifts only `existing_coordinator.control_generation` to the top-level `control_generation`, and calls `verify_generation_transition` on the two complete copied snapshots. Preserve every other field including task, receipts, owner, controls, source and schema evidence. Do not drop the settings table or normalize any other control. The adapter binds the unprojected original/final snapshot digests independently of the callback proof.

No new closure or native authority is introduced. Root still must finish the existing -16 restored-state closure before any separately approved forward.

## Focused disposable evidence

One parameterized source-transaction fixture reuses the exact accepted four old images, five candidate images, real atomic source helper and a private SQLite database. It calls the actual accepted old Store.configure_queue(False), with only its connect() method bound to the disposable database, to reproduce normal shutdown generation changes. No Store constructor or native state is opened.

Results:
- Callback enabled, normal install: exact 580→581, five after images, installed receipt, all other existing rows and controls unchanged.
- Callback enabled, injected restart refusal: exact 580→582, all four before images restored, added prompt absent, rollback receipt, original authorized snapshot intact.
- Both original strict no-callback cases still pass unchanged semantics.
- A generation increase of 3 and a changed unrelated queue control are rejected.
- Terminal replay remains refused; unrelated source sibling is unchanged.

Command: `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -B -m pytest -q -p no:cacheprovider /tmp/jsh-embraer-03-generation-forward/test_five_tool_forward.py`.

Result: `5 passed in 1.21s`.

Service/observer/route callbacks remain substitutes in this fixture. These results do not establish native installation, authorize a child, or consume an inference budget.
