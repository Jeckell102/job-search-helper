# Exact local durability contract for compact-v1 recovery

Date: 2026-11-19

Status: implementation design only. No source, test, production, lock, queue,
Google Sheets, or live job data was changed while producing this report.

## Critical cursor and writer finding

The installed/live `sync_plans.cursor` is a **local SQLite apply cursor**. Its
operations are LocalPipeline/repository operations, not Google batch
operations. The eight retained live plans have legacy/minimal operation keys
and nonzero or end cursors because prefixes were already applied locally.
Sending any of those operations directly to Google, or reinterpreting their
cursor as a Google acknowledgement cursor, is categorically unsafe.

There are also 34 unblocked inventories with no plan. They are the clean path
for the version-2 contract below. The eight legacy plans require the separate
migration/readback contract in this report. Neither population may be
silently converted into the other.

## Decision

Newly planned compact-v1 inventories must use a two-phase local/remote plan.
The immutable inbox plan must contain both the complete local operations and
the compact Google projection before either repository is mutated. The full
local operations are then applied and read back through an exact journal in
the existing job SQLite database. Only after that proof exists may the
existing publication receipt be created in `LOCAL_COMMITTED`. Remote delivery
must then use a new exact-scoped `SheetsSynchronizer` path over only the
selected local rows and dirty fields. The frozen remote projection is a
required equality check on that scoped synchronizer plan; it is not permission
to feed legacy LocalPipeline operations to `GoogleRepository.commit`.

This is not safely implemented by calling `SheetsSynchronizer.publish_batch`
or `SheetsSynchronizer.once`. Those APIs discover work from the global
`dirty` table, may prune global compact delivery flags, and the latter also
pulls workbook-wide state. Their field-level acknowledgement algorithm is
useful and should be extracted into a narrow helper, but their discovery,
pull, and retry orchestration must not be reused by exact-cycle recovery. A
new exact-scoped entry point should reuse its row/field planning and
acknowledgement semantics while adding immutable intent and no-replay
journaling.

## Current gap

The current feature candidate's `exact_cycle_planner._freeze` correctly
simulates the complete LocalPipeline result in memory. Its `_seal_plan`,
however, replaces `plan['operations']` with the compact remote projection and
retains only digests of the complete local operations. The full local
operations cannot therefore be applied or reconstructed after a restart.
This candidate behavior is distinct from the eight pre-existing live plans,
whose operations and cursor retain their legacy local-apply meaning.

For a new full-profile plan, `InventoryInbox.save_plan(..., receipt)` stores
the plan and creates a `LOCAL_COMMITTED` publication receipt atomically in the
inbox. Under compact-v1, that would be false: no transaction has committed the
local-only evidence, source hashes, scan controls, or other full local record
changes. The current explicit hold
`compact_exact_plan_requires_durable_local_commit_journal` is therefore the
correct fail-closed behavior until this contract is implemented.

The normal local path has valuable primitives but a different scope:

- `SQLiteRepository.commit` atomically applies operations, preserves protected
  manual decisions, and marks compact-visible changed fields dirty.
- `SheetsSynchronizer._operations(row_scope=...)` can restrict discovery, but
  it still derives a new plan from mutable current records and the shared
  dirty queue. It is not the frozen exact plan.
- `SheetsSynchronizer.publish_batch(row_scope=...)` records delivery attempts,
  writes Google, then acknowledges matching fields. A timeout raises with no
  immutable per-chunk no-replay boundary, so calling it again may issue an
  ambiguous write again.
- `InventoryInbox` already provides immutable plans, exact chunk journals,
  cursors, and publication receipts, but it does not prove a compact plan's
  full local application.

## Required invariants

1. One explicit `(cycle_id, company_id)` selects all work. No API scans the
   inbox, `dirty`, delivery attempts, outbox, or another company for work.
2. The immutable plan is durable before the first local mutation and contains
   the complete local operations as well as the exact remote projection.
3. `LOCAL_COMMITTED` means the complete local operations were atomically
   committed and exact local readback matched the frozen result. Merely saving
   an inbox plan never earns this state.
4. The remote plan is a deterministic projection of the frozen local plan
   through the frozen compact schema. After local application, exact scoped
   dirty-cell planning must equal that projection. A mismatch holds; current
   dirty state never silently replaces the frozen projection.
5. Each bounded LocalPipeline application chunk and its `APPLIED` journal row
   occur in one SQLite transaction. A crash yields either neither or both.
6. Remote-visible baselines and dirty cells are acknowledged only after exact
   Google readback for those records and fields. A newer local value remains
   dirty.
7. Local-only data is durable locally but is never represented as remotely
   acknowledged. In particular, source hashes and evidence excluded by
   compact-v1 are not copied into a remote baseline as if Google stored them.
8. Manual Yes/No, review locks, identity guards, source-hash guards, and the
   salary fallback rule remain authoritative. A changed guard holds the item;
   recovery does not weaken or silently replan it.
9. The local apply cursor and remote publication cursor are separate named
   fields/tables. Neither can ever be inferred from the other.
10. Once a remote attempt is durably marked pending, recovery does readback
   only. A mismatch is a hold, never permission to replay an ambiguous write.
11. State finalization and inventory deletion occur last. A crash before them
    is cleanup-only recovery from the confirmed receipt and exact journals.

## Immutable plan version 2

Keep `sync_plans.payload` as the durable authority, but introduce a versioned
shape. Do not overload the current `operations` name with two meanings.

```json
{
  "exact_plan_version": 2,
  "cycle_id": "CYC-...",
  "company_id": "COMP-...",
  "inventory_payload_digest": "sha256",
  "requested_url": "https://...",
  "control_evidence": {},
  "control_evidence_version": 1,
  "control_evidence_digest": "sha256",
  "publication_profile": "compact-v1",
  "publication_schema": {"Job History": ["..."], "Companies": ["..."]},
  "publication_schema_digest": "sha256",
  "local_operations": [],
  "local_operations_digest": "sha256",
  "local_expected_records": {},
  "local_expected_records_digest": "sha256",
  "remote_projection": [],
  "remote_projection_digest": "sha256",
  "remote_records": {},
  "remote_records_digest": "sha256",
  "local_finalization": {},
  "local_finalization_digest": "sha256",
  "final": {},
  "final_projection": {},
  "final_projection_digest": "sha256",
  "plan_digest": "sha256"
}
```

`publication_schema` must be stored, not only hashed, so later validation can
prove exactly which fields were visible when the plan was frozen. A change of
profile or schema before delivery is a hold; it does not trigger reprojection.

`local_operations` must already contain deterministic inserted identities.
Most importantly, a new Opportunity ID must be assigned during the in-memory
planning pass and included in both local and projected operations. No UUID may
be generated for the first time during durable application. Duplicate target
identities or two operations that require an atomic group unsupported by the
exact publisher must fail before plan persistence.

`local_expected_records` fingerprints only the identities and owned fields
produced by the complete local operations. It is not a whole-database hash.
The fingerprint function must understand append-notes and final identities in
the same way as `publication_receipts.record_fingerprints`.

`remote_projection` is the expected output of exact scoped dirty-cell
planning after local application. It is not a second interpretation of
`sync_plans.cursor` and it is never used to send a legacy plan directly.

For compatibility, existing legacy plans retain their local-apply meaning.
Their `sync_plans.cursor` is never a remote cursor. A legacy compact plan must
follow the migration/readback contract below; it must never be silently
upgraded merely because its operations can be made to resemble Google
operations.

## Additive schemas

### Inventory database

Add a table rather than changing the semantics of existing receipt states:

```sql
CREATE TABLE exact_plan_local_state (
  cycle TEXT NOT NULL,
  company TEXT NOT NULL,
  plan_digest TEXT NOT NULL,
  local_operations_digest TEXT NOT NULL,
  remote_projection_digest TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN
    ('FROZEN','LOCAL_APPLIED','LOCAL_VERIFIED')),
  local_apply_id TEXT,
  local_records_digest TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(cycle, company),
  FOREIGN KEY(cycle, company) REFERENCES sync_plans(cycle, company)
);

CREATE TABLE exact_legacy_plan_migrations (
  cycle TEXT NOT NULL,
  company TEXT NOT NULL,
  legacy_plan_digest TEXT NOT NULL,
  inventory_payload_digest TEXT NOT NULL,
  operation_count INTEGER NOT NULL,
  original_local_cursor INTEGER NOT NULL,
  verified_local_cursor INTEGER NOT NULL DEFAULT 0,
  row_scope TEXT,
  remote_projection TEXT,
  remote_projection_digest TEXT,
  state TEXT NOT NULL CHECK(state IN
    ('FROZEN','PREFIX_VERIFIED','LOCAL_COMPLETE','REMOTE_PLAN_FROZEN')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(cycle, company),
  FOREIGN KEY(cycle, company) REFERENCES sync_plans(cycle, company)
);

CREATE TABLE exact_remote_plans (
  cycle TEXT NOT NULL,
  company TEXT NOT NULL,
  local_plan_digest TEXT NOT NULL,
  projection TEXT NOT NULL,
  projection_digest TEXT NOT NULL,
  remote_cursor INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL CHECK(state IN
    ('FROZEN','SYNC_PENDING','SYNC_CONFIRMED','LOCAL_ACKNOWLEDGED')),
  acknowledgement_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(cycle, company)
);
```

`InventoryInbox.save_exact_plan` inserts `sync_plans` and the `FROZEN` row in
one inbox transaction. It does **not** call
`publication_receipts.local_committed`. Repeated insertion must compare the
entire canonical plan and all digests; it cannot replace the plan.

`LOCAL_APPLIED` and `LOCAL_VERIFIED` here are mirrors used for orchestration,
not the authority for the local commit. The job database journal below is the
authority. Cross-database crashes are repaired by comparing the immutable
plan digest and local journal; no distributed transaction is assumed.

`exact_remote_plans.remote_cursor` is the only aggregate Google publication
cursor. It advances only after a matching `exact_sync_chunks` row is confirmed
by exact readback. It is never copied to or from `sync_plans.cursor`.

### Job SQLite database

Add an exact journal in the existing `SQLiteRepository` schema:

```sql
CREATE TABLE exact_local_applications (
  apply_id TEXT PRIMARY KEY,
  cycle TEXT NOT NULL,
  company TEXT NOT NULL,
  plan_digest TEXT NOT NULL UNIQUE,
  inventory_payload_digest TEXT NOT NULL,
  local_operations_digest TEXT NOT NULL,
  remote_projection_digest TEXT NOT NULL,
  row_scope TEXT NOT NULL,
  created_at TEXT NOT NULL,
  verified_at TEXT,
  state TEXT NOT NULL CHECK(state IN ('APPLYING','VERIFIED'))
);
CREATE UNIQUE INDEX exact_local_application_company
  ON exact_local_applications(cycle, company);

CREATE TABLE exact_local_apply_chunks (
  apply_id TEXT NOT NULL,
  start_cursor INTEGER NOT NULL,
  operation_count INTEGER NOT NULL,
  operations_digest TEXT NOT NULL,
  before_records TEXT NOT NULL,
  expected_records TEXT NOT NULL,
  expected_records_digest TEXT NOT NULL,
  dirty_before TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  verified_at TEXT,
  state TEXT NOT NULL CHECK(state IN ('APPLIED','VERIFIED')),
  PRIMARY KEY(apply_id, start_cursor),
  FOREIGN KEY(apply_id) REFERENCES exact_local_applications(apply_id)
);

CREATE TABLE exact_local_acknowledgements (
  apply_id TEXT NOT NULL,
  receipt_id TEXT NOT NULL,
  acknowledgement_id TEXT NOT NULL,
  selected_fields_digest TEXT NOT NULL,
  acknowledged_at TEXT NOT NULL,
  PRIMARY KEY(apply_id, receipt_id),
  FOREIGN KEY(apply_id) REFERENCES exact_local_applications(apply_id)
);
```

Each chunk row is written in the same `BEGIN IMMEDIATE` transaction that calls
`SQLiteRepository._commit_in_transaction(local_operations[start:end])`.
`before_records` and `dirty_before` are bounded to the exact resolved
rows/fields. They are audit and conflict evidence, not a rollback instruction.
Recovery must not roll back legitimate later edits.

`row_scope` is a canonical mapping of stable local row identities to only the
remote-visible fields owned by `remote_projection`. Persist row IDs as local
implementation hints, but always revalidate the stable identity before using
them. This prevents an unrelated row from being acknowledged if local storage
was repaired or migrated.

## State machine and ordering

### A. Freeze without mutation

1. Under the normal scraper lock, validate the exact cycle, company, durable
   inventory, compact profile, current local controls, and narrow current
   Google Company controls.
2. Run `_freeze` against `PlanningRepository` only.
3. Apply deterministic identity assignment and salary/manual/source-control
   normalization while the before snapshot is still available.
4. Freeze `local_operations`, project `remote_projection`, compute expected
   fingerprints and every digest, then compute `plan_digest` over all sealed
   fields.
5. Atomically insert `sync_plans` and `exact_plan_local_state=FROZEN`. Do not
   create a publication receipt and do not update State yet.

Crash result: a frozen plan exists, local records are unchanged, and recovery
starts at B. No state is mislabeled `LOCAL_COMMITTED`.

### B. Exact local application

1. Revalidate plan, payload, profile/schema, controls, and absence/identity of
   any journal with another digest.
2. Apply through the exact selected-company LocalPipeline/repository boundary,
   never through Google. Starting at the local `sync_plans.cursor`, select a
   bounded immutable chunk. In one job-database transaction, resolve only its
   frozen identities; capture bounded before records, baselines,
   manual-choice rows, and selected dirty cells; call
   `_commit_in_transaction(chunk)`; read the affected rows; compare plan-owned
   fields with the chunk's expected records; and insert its `APPLIED` row.
3. Commit. SQLite guarantees that a crash during a chunk leaves neither its
   mutations nor journal row, or leaves both.
4. Outside that write transaction, read the exact identities again. If the
   fingerprints still match, transition that chunk to `VERIFIED`, then
   advance the inbox local cursor with an expected-old-cursor compare. If they
   do not, retain `APPLIED` and hold; never reapply the chunk. A crash after
   chunk verification but before cursor advance is repaired from the chunk
   journal and readback.
5. Repeat only for the next local chunk. When the local cursor equals the
   frozen operation count, verify the complete local fingerprint and mark the
   parent local application `VERIFIED`. Mirror `LOCAL_APPLIED`, then
   `LOCAL_VERIFIED`, into the inbox by comparing
   `apply_id`, `plan_digest`, and record digest. Each transition is monotonic.
6. Only now derive and insert the existing publication receipt using
   `InventoryInbox.ensure_receipt`, producing `LOCAL_COMMITTED`.
7. Save the recoverable State `inventory` checkpoint second.

Recovery rules:

- FROZEN with no local journal: start B at local cursor zero.
- FROZEN with a matching APPLIED/VERIFIED chunk: never call local commit for
  that chunk again; read back and advance the local cursor/mirrors.
- Inbox mirror behind local journal: repair the mirror from the journal.
- Inbox mirror ahead of a missing/mismatched local journal: hold as corruption.
- `LOCAL_COMMITTED` receipt without a matching VERIFIED local journal: hold as
  corruption. It cannot authorize Google delivery.

### C. Exact scoped dirty-cell publication

1. Require plan v2, matching `LOCAL_VERIFIED` evidence, and a matching
   `LOCAL_COMMITTED` receipt before considering a remote write.
2. Revalidate Company controls and profile/schema. Construct a
   `SheetsSynchronizer` but invoke only a new `publish_exact_scope` API with
   the frozen row/field scope. That API may internally reuse/refactor
   `_operations(row_scope=...)`; it must never enumerate or act on candidates
   outside the supplied scope. Its canonical planned operations must exactly
   equal `remote_projection` before any remote intent is journaled.
3. `publish_exact_scope` owns the Google repository write and the scoped
   baseline/dirty acknowledgement. `exact_cycle_sync` orchestrates its durable
   intent/readback states; it must not pass legacy local operations directly
   to `GoogleRepository.commit`.
4. Require the local `sync_plans.cursor` to equal the count of local
   operations before remote planning. Never advance that cursor for a Google
   acknowledgement. Retain the exact chunk protocol on a separate remote
   cursor/journal: exact readback first, immutable
   pending chunk before commit, exact readback after commit, then cursor
   advance. After any crash with a pending receipt/chunk, perform readback
   only. A mismatch is an explicit hold.
5. After all remote record fingerprints match, transition the receipt to
   `SYNC_CONFIRMED` with the exact readback acknowledgement.

### D. Exact local acknowledgement and cleanup

1. From the verified local journal, reload only `row_scope` identities and
   the exact Google rows already used to confirm the remote receipt.
2. In one local transaction, for each selected remote-visible field:
   - update that field in `baseline` to the confirmed Google value;
   - delete its dirty row only when the current local value still equals the
     frozen sent value;
   - retain dirty when a newer local edit exists;
   - delete only that row's exact delivery-attempt fields, if the exact path
     created any; do not delete unrelated attempts;
   - leave every nonselected baseline key and dirty row untouched.
3. Record `REMOTE_ACKNOWLEDGED` in a separate exact acknowledgement table or
   additive journal columns, bound to receipt ID and acknowledgement ID.
4. Save the final cycle checkpoint. Then acknowledge or block only this exact
   inventory and plan.

If a crash occurs after `SYNC_CONFIRMED`, recovery does no Google write. It
repeats only the idempotent scoped local acknowledgement, State save, and
inbox cleanup.

## Migration/readback contract for the eight legacy plans

The existing plans are evidence of partially or fully completed local
application. Preserve their payload and cursor byte-for-byte.

1. Add an immutable `exact_legacy_plan_migrations` row keyed by cycle/company
   containing the canonical legacy plan hash, inventory payload hash, original
   local cursor, operation count, and classification `LOCAL_APPLY_LEGACY`.
   Creating this envelope has no local or remote side effect.
2. Treat operations before `sync_plans.cursor` as an asserted locally applied
   prefix. Read back their exact stable identities and plan-owned fields from
   SQLite. If the prefix cannot be proven, hold; never reset the cursor and
   never send the prefix to Google.
3. Resume only the unapplied tail through the exact scoped LocalPipeline/local
   repository commit boundary. After each local commit, read back that chunk
   and advance the existing local cursor. A crash before cursor advance is
   reconciled by local readback, not blind replay.
4. When the local cursor reaches the operation count, derive an exact local
   row/field scope from the migration envelope, the legacy operations, and the
   verified local rows. Run scoped dirty-cell planning and freeze its compact
   Google projection in a new additive remote-delivery record. This remote
   record has its own cursor starting at zero.
5. Require the frozen scoped projection to match current selected dirty cells
   and compact schema. Any unexplained selected dirty field, missing expected
   field, identity ambiguity, manual/source/salary conflict, or unrelated row
   is a hold.
6. Publish only through `SheetsSynchronizer.publish_exact_scope`, then perform
   scoped acknowledgement and cleanup. The legacy local cursor is never
   changed by a Google acknowledgement.

This contract is intentionally stricter than the version-2 path because a
legacy plan did not freeze a compact remote projection before its local
prefix was applied. Readback and an additive migration receipt are the only
safe bridge; no claimed pre-mutation remote intent is fabricated after the
fact.

## The 34 no-plan inventories

Each of the 34 no-plan inventories is eligible only through version 2:

1. freeze full LocalPipeline operations and compact projection before local
   mutation;
2. save plan plus FROZEN state with no `LOCAL_COMMITTED` receipt;
3. apply/read back locally through the exact LocalPipeline journal;
4. require exact scoped dirty-cell planning to equal the frozen projection;
5. publish/acknowledge through the scoped Sheets synchronizer with a separate
   remote cursor; and
6. finalize only that company.

Batch discovery is forbidden. The caller must continue naming at most the
bounded explicit company set, and one held item must not authorize another.

## Salary, manual-choice, and source controls

The freeze/apply boundary must retain the current repository policies rather
than treating compact projection as permission to discard them.

- Manual choice: retain `_normalize_history_guards`; revalidate the current
  `manual_choices` row and `Added to Opportunities?` before local application
  and remote publication. `SQLiteRepository._commit_in_transaction` remains
  the enforcement point that strips or rejects protected automated review
  mutations. A changed choice holds or causes the guarded operation to no-op;
  it never gets overwritten.
- Source hash: keep source hash and evidence changes in `local_operations` and
  local fingerprints even though compact-v1 does not expose them. Preserve a
  source-hash expected guard in the local operation. Omit it only from the
  remote projection when the compact schema excludes it. A source change
  between freeze and apply/publication is a hold, not a replan.
- Estimated salary: if the posting has a real extracted salary, its frozen
  value may update the selected salary field subject to the existing expected
  guard. If extraction is blank or the known empty scraper envelope and the
  current local/baseline value contains a plausible user estimate, normalize
  the local operation to preserve that estimate and omit any remote salary
  mutation. If the remote salary changed after freeze, its expected-value
  guard must fail; recovery must not overwrite it. This is the exact-path
  counterpart of `_missing_extracted_salary` and `_plausible_salary_estimate`
  in `sheets_sync.py`.
- Notes: preserve append-only note semantics. Fingerprint the suffix and
  confirm its presence rather than replacing an entire user-owned notes cell.
- Identity: preserve legacy job-key guards and permanent Opportunity IDs.
  Never fall back to row number as identity.

## API and file ownership plan

The implementation should be divided so the existing single writer and lock
boundaries remain visible.

### `exact_cycle_planner.py`

- Introduce plan v2 and retain both `local_operations` and
  `remote_projection`.
- Make deterministic inserted IDs part of planning.
- Add pure canonical local/remote fingerprint and salary-normalization helpers.
- Remove the compact hold only after the local journal APIs below exist.
- Do not apply local records here.

### `inbox.py`

- Add the `exact_plan_local_state` migration and exact methods:
  `save_exact_plan`, `exact_local_state`, and monotonic
  `mark_exact_local_applied/verified`.
- Keep `save_plan` compatibility for legacy plans.
- Ensure `acknowledge` deletes the exact-plan local-state row only in the same
  selected-company cleanup transaction.
- Do not insert `LOCAL_COMMITTED` from `save_exact_plan`.

### `sqlite_repository.py`

- Add `exact_local_applications` and optionally an
  `exact_local_acknowledgements` table.
- Add `apply_exact_local_plan(...)` that performs authoritative fresh identity
  resolution, `_commit_in_transaction`, exact readback, and APPLIED journal
  insertion in one transaction.
- Add `verify_exact_local_plan(...)` and
  `acknowledge_exact_remote_fields(...)`.
- These methods accept explicit plan, identities, fields, and receipt binding;
  none discovers work from `dirty` or another queue.

### `exact_cycle_recovery.py`

- Orchestrate A through D while holding the existing normal scraper lock.
- Require both local and remote dependencies created under that lock.
- Preflight every selected company locally before the first remote access.
- Never invoke a global synchronizer or startup hook.

### `exact_cycle_sync.py`

- Treat every existing `sync_plans.cursor` as local apply progress.
- Read `remote_projection` only from v2 or an accepted legacy migration
  record; never reinterpret legacy operations as Google operations.
- Require matching local VERIFIED evidence before receipt creation/delivery.
- Return confirmed readback material or acknowledgement ID to the local scoped
  acknowledgement step instead of discarding it.
- Retain existing no-replay pending receipt/chunk behavior using a separate
  remote cursor/journal.

### `sheets_sync.py`

- Do not call `pull`, `once`, or global `publish_batch` from exact recovery.
- Add `plan_exact_scope(row_scope, frozen_projection)` and
  `publish_exact_scope(...)`. The former may reuse `_operations` only with a
  mandatory explicit scope and must equality-check the frozen projection.
- Extract a pure/scoped acknowledgement primitive if doing so avoids
  duplicating the baseline/dirty comparison. The helper must accept explicit
  `(tab, stable identity, fields, frozen sent row, actual row)` records and
  must never query the global dirty candidate set.

Ownership during implementation should be nonoverlapping: one lane owns
planner/inbox/schema and local apply APIs; a second owns exact publisher and
recovery orchestration; independent QA owns tests/review only until fixes are
assigned. `sheets_sync.py` should have one named owner if refactored.

## Can existing `SheetsSynchronizer` helpers be reused?

Safe with extraction or direct narrow reuse:

- `identity_for`, `_equivalent`, compact profile schema helpers, and canonical
  projection rules.
- The acknowledgement rule from the final transaction in `publish_batch`:
  baseline only from actual readback, and clear dirty only if current still
  equals sent. It must be extracted into an explicit-row helper.
- The salary classification helpers, after moving them to a shared policy
  module or importing a pure helper without constructing a synchronizer.

Not safe for the exact path:

- `once` and `pull`: workbook/global side effects.
- Unchecked `_operations`, even with `row_scope`: it replans from mutable dirty
  state and can create conflicts as a side effect. It is usable only behind a
  new exact API that accepts a mandatory frozen scope and requires canonical
  equality with the sealed projection before intent.
- `publish_batch`: it discovers via dirty, can add related Opportunity guards,
  uses a delivery-attempt table shared with the global writer, and does not
  provide the exact pending-chunk no-replay contract.
- `prune_local_only_delivery`: global dirty-table mutation.

Therefore the remote writer must be an exact-scoped Sheets synchronizer path,
not direct publication of legacy plan operations. Reuse should be limited to
explicit-scope planning, pure policy/identity functions, durable no-replay
journaling, and scoped acknowledgement.

## Failure matrix

| Boundary/failure | Durable evidence | Required recovery | Forbidden action |
|---|---|---|---|
| Before plan insert | inventory only | freeze again from unchanged inputs | mutate local/remote |
| After plan/FROZEN insert | immutable v2 plan | apply exact local plan | replace/reproject plan |
| During local transaction | SQLite rolls back | retry local transaction after no journal | infer partial commit |
| After local APPLIED commit | local journal + records | exact local readback, then verify | call local commit again |
| After local VERIFIED, before inbox mirror | verified journal | repair mirror by digest | create alternate plan |
| After inbox VERIFIED, before receipt | both proofs | insert derived LOCAL_COMMITTED receipt | publish without journal check |
| After receipt, before State checkpoint | plan + verified local + receipt | repair State checkpoint | redo local commit |
| Before remote pending journal | remote readback mismatch, no pending | one authorized first attempt | issue an unjournaled write |
| After pending journal, before/during commit | pending receipt/chunk | readback only | replay on mismatch/timeout |
| After remote write, before cursor | exact readback can prove chunk | confirm and advance | blindly resend chunk |
| After cursor, before full confirmation | confirmed prefix | re-read prefix and next chunk | overwrite changed prefix |
| After SYNC_CONFIRMED, before local ack | confirmed receipt/readback | scoped local ack only | write Google again |
| During scoped local ack | SQLite rolls back | retry same selected ack | clear global dirty/baselines |
| After local ack, before State | ack journal | finalize State | republish |
| After State, before inbox cleanup | terminal checkpoint + confirmed receipt | exact cleanup only | replan/refetch |
| Profile/schema drift | frozen schema digest differs | hold for operator migration | reproject silently |
| Manual/source/salary guard drift | exact mismatch/conflict | hold, preserve both versions | weaken expected guards |
| Journal digest mismatch | contradictory authority | corruption hold and report | choose one heuristically |
| Legacy nonzero/end cursor | local applied-prefix claim | migrate + exact SQLite readback | send operations to Google |
| Legacy local cursor at end | local work complete only | freeze scoped dirty projection | call it remote-confirmed |

## Required tests

### Plan and schema tests

1. A new compact inventory freezes full local operations and compact remote
   projection before any local or remote mutation.
2. Stored schema/profile and all local/remote/final digests are deterministic
   and tamper-evident.
3. Full local operations survive process restart and are not reconstructable
   from mutable repository state.
4. Inserted Opportunity IDs are frozen and identical in local and remote
   identities.
5. Unknown profile, removed identity, empty remote projection, duplicate
   identity, and changed controls fail before plan persistence.
6. Legacy compact plans preserve their cursor as local progress; migration
   readback proves every applied prefix and never emits those operations to
   Google.

### Local durability tests

7. Fault injection immediately before, during, and after the local transaction
   proves all-or-nothing local records plus APPLIED journal.
8. Crash after APPLIED does not call `_commit_in_transaction` again; exact
   readback advances to VERIFIED.
9. Changed local record after APPLIED leaves it APPLIED/held and preserves the
   newer value.
10. A mismatched/missing journal can never produce `LOCAL_COMMITTED`.
11. `LOCAL_COMMITTED` appears only after exact local readback and persists
   across restart.
12. Another company's records, dirty cells, baseline, conflicts, delivery
   attempts, event outbox, and inventory remain byte-for-byte unchanged.

### Policy tests

13. Manual Yes and No before freeze, between freeze/apply, and between
   apply/publish are never overwritten.
14. Manual Review plus Source Hash guards are retained locally; compact remote
   projection omits unavailable Source Hash without weakening the local guard.
15. Blank/known-empty extracted salary preserves a plausible local/remote
   estimate and sends no salary mutation.
16. An explicit extracted salary updates only under the frozen expected guard;
   a concurrent spreadsheet salary edit causes a hold.
17. Append-only notes retain user text and acknowledge only the frozen suffix.

### Remote and acknowledgement tests

18. Every crash boundary in the failure matrix is injected, including timeout
   after a real synthetic remote mutation. A pending mismatch performs zero
   further commits.
19. Existing cursors 1/19/67 are tested as local applied-prefix positions,
   never remote positions; a separate remote chunk journal proves no replay.
20. Exact scoped Sheets planning equals the frozen compact projection before
   any remote intent; exact remote readback includes only selected identities
   and fields.
21. Scoped local acknowledgement updates only selected visible baseline
   fields, clears only unchanged selected dirty fields, and retains a newer
   local edit dirty.
22. Local-only evidence/source fields remain durable and are not falsely added
   to the remote baseline.
23. Crash after SYNC_CONFIRMED performs zero remote commits and completes only
   scoped acknowledgement/finalization.
24. State-save and inbox-cleanup split remains cleanup-only and idempotent.

### Isolation and integration tests

25. Seed unrelated dirty/outbox/delivery/conflict rows across every tab and a
   second company/cycle. Hash them before and after exact recovery; hashes must
   match.
26. Patch/spy on `SheetsSynchronizer.pull`, `once`, global `publish_batch`,
   `prune_local_only_delivery`, and global startup hooks; all must remain
   uncalled. If `_operations` is refactored underneath `plan_exact_scope`,
   assert it receives only the explicit frozen scope and that equality is
   checked before intent.
27. Verify the normal scraper lock covers dependency construction, local
   apply, remote readback/write, acknowledgement, State, and inbox cleanup.
28. Run the complete compact Sheets, durable inbox, exact planner, exact sync,
   recovery runner, salary policy, and restart suites together.
29. Independent QA must inspect the actual installed hashes and run a
   disposable compact-v1 database plus a synthetic interrupted remote write.
30. Only after all offline gates pass may a one-company guarded pilot run; it
   must prove local full records, compact Google rows, scoped baselines/dirty,
   terminal receipt, State, and unchanged unrelated queues.

## Acceptance evidence for implementation

Implementation is acceptable only when evidence shows, for the same selected
company and plan digest:

- immutable plan v2 existed before local mutation;
- all eight legacy cursors were treated only as local-apply cursors and their
  applied prefixes were proven from SQLite before any remote planning;
- each no-plan inventory used a version-2 pre-mutation freeze;
- the local APPLIED/VERIFIED journal and exact record fingerprints match;
- `LOCAL_COMMITTED` was created after local VERIFIED, not during plan save;
- Google received only the frozen, equality-checked exact scoped dirty-cell
  projection through `SheetsSynchronizer`, and exact readback confirmed it;
- only the selected remote-visible baselines/dirty fields were acknowledged;
- local-only evidence, source hash, protected manual decisions, and salary
  fallback remained correct;
- State and inventory cleanup reached their terminal selected-company state;
- unrelated company/cycle inventories and all global dirty/outbox data were
  unchanged; and
- restart/fault-injection QA proves no ambiguous remote write was replayed.

Until that evidence exists, the current compact hold must remain enabled and
the broad backlog and automatic release paths must remain disabled.
