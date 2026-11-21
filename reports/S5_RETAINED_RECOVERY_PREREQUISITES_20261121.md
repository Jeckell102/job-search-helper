# Existing retained-cycle disposition prerequisites — read-only source verdict

Verdict: no existing supported disposition permits the reported Saronic legacy plan to remain at cursor 67/208 and simultaneously removes cycle CYC-B639C6D864EC from unfinished ownership. Leaving it retained and untouched requires no provenance decision, but does not permit the guarded source-install/release gate. A signature or manually setting a blocked flag cannot substitute for missing source ownership or publication proof.

Scope: production Python source reads only. No application CLI, SQLite database, provider, Google, model, service, lock, queue, or writer was invoked. Cursor 67/208 and the genuine source conflict are the coordinator's supplied current facts, not a fresh data observation by this reviewer. No application source changed.

## Exact alternatives and first prerequisites

| Existing route | First prerequisite / source | Consequence for retained Saronic |
|---|---|---|
| Ordinary interrupted-cycle pause | `runner.py:1124–1152`: exact assessed inactive cycle must be the only unfinished cycle, with **zero saved inventories and zero saved plans**. `runner.py:1479–1493` exposes its read-only status command. | Saved work fails `SAVED_WORK_MUST_BE_PUBLISHED_OR_RECONCILED`. This is not an archive/discard route. |
| Exact terminal hold manifest | `exact_recovery_terminal.py:55–116`: explicit exact Company IDs; State stage `blocked`/`unsupported`; Inbox blocked inventory; any frozen plan must have cursor equal to operation count and its exact matching durable `SYNC_CONFIRMED` receipt. A receipt with no plan is also refused. | 67/208 fails `frozen_plan_not_complete`, even if all earlier stage/blocked conditions were met. The API is read-only qualification, not a command that creates a terminal hold. |
| Exact recovery pause journal/executor | `exact_recovery_pause.py:121–175`: unfinished exact cycle, no unblocked saved work, freshly revalidated manifests exactly covering all blocked Inbox companies, plus at least one queued/inventory pause candidate. `freeze_exact_pause_journal` is at line 190; `exact_recovery_pause_executor.py:272` exposes `execute_exact_recovery_pause`. | Cannot bypass incomplete saved-plan qualification. The executor then changes named Company controls, State, and Scan Cycles through durable intent/readback; it is not a no-write way to declare unfinished work complete. These are library APIs, not a normal runner CLI switch. |
| Completed legacy plan migration | `exact_legacy_migration.py:31–40`: local cursor must equal all operations, followed by operation ownership/control/readback checks. `exact_legacy_migration_runner.py:82–117` builds preview with readonly stores. | The completed-plan migration route is inapplicable at 67/208. |
| Selected partially applied legacy recovery | `selected_recovery_runner.py:30–66` builds readonly candidate; `exact_selected_legacy_recovery.py:229–288` requires a Company operation already in verified prefix, exact inventory/control binding, all operation ownership, stable local snapshot, and local Source Hash guards. Lines 77–129 validate Job Key/Source Hash/Company and evidence identity. | Can adopt an actually proved prefix without replay, preserving original evidence; cannot resolve a genuine mismatching source hash by authorization. Apply requires an exact signed envelope, under-lock rebuild, then local commit and separate successor/publication gates (`selected_recovery_runner.py:69–156`). |
| Late Company-control / control-before-prefix variant | `control_before_prefix_runner.py:23–56` supplies readonly preview. `exact_control_before_prefix_recovery.py:67–78,96–180,245–278` requires the Company operation after the cursor, exact current controls, valid missing-append suffix manifest, source/Company ownership, and stable snapshot. Present non-append metadata operations may derive a guard only when existing expected ownership agrees. | It cannot erase explicit Source Hash conflict. Even a successfully signed candidate only creates a durable local hold; the module explicitly provides no generic apply/release fallback (`control_before_prefix_runner.py:1–6,58–93`). No command-line `main` is exposed. |
| Cancel selected recovery | `selected_recovery_runner.py:164–176`: a sealed exact selected successor in untouched `FROZEN` state is required. | Cancels that successor only; cannot cancel the original partially applied legacy plan or make the original cycle terminal. |

## Authoritative first commands / APIs (templates only; not executed)

For a read-only explanation of the cycle-wide ordinary recovery gate:

```text
./job-search-scraper recover-interrupted-cycle-status --cycle-id CYC-B639C6D864EC
```

For a selected *partial* recovery candidate, when its Company-control operation is already in the verified prefix (CLI declared in `selected_recovery_runner.py:206–216`):

```text
python -m job_search_helper.selected_recovery_runner preview --inventory <exact inventories.sqlite3> --local-db <exact jobs.sqlite3> --cycle CYC-B639C6D864EC --company <exact Saronic Company ID> --expires-at <fresh UTC expiry>
```

If the Company-control operation is late, the existing read-only API is instead:

```text
control_before_prefix_runner.preview_control_before_prefix_recovery(
    inventory_path, local_path, cycle_id, company_id, expires_at=expiry)
```

For a *completed* legacy cursor only, the normal runner command exists (`runner.py:1492–1517`):

```text
./job-search-scraper legacy-migration-preview --cycle-id CYC-B639C6D864EC --company-id <exact Company ID>
```

Do not use this completed-plan command as though it repairs a partial cursor. Do not invent an exact-terminal CLI: `qualify_terminal_holds(state, inbox, cycle_id, company_ids)` is the actual read-only library entry point.

## Smallest first recovery requirement

Obtain an authoritative, exact comparison for the disputed Saronic operation: original immutable operation and inventory identity, current Job Key/Company/Source Hash ownership, current Company controls, and whether the Company operation lies before or after cursor 67. The corresponding readonly preview can then produce either a valid candidate and approval claims or its precise rejection. A valid candidate is the prerequisite for signed adoption; approval alone cannot override mismatched ownership. Until that evidence agrees, preserve the original plan, cursor, inventories, and disputed rows. There is no supported terminal-hold manifest for this incomplete plan in the inspected source.

This review adds no new architecture and does not authorize or claim execution of any recovery, publication, or deployment.


## Addendum: current guarded observation at 05:15:24 EST

Read the coordinator's exact saved RESULT.json, not live stores. Saronic is COMP-0054. Its normal preview is held for incomplete cursor; selected preview is held because the Company operation is outside the verified prefix; control-before-prefix preview is held by Job History ownership. Exactly one reported operation (number 194, outside prefix) has stable Job Key and Company, proposed source different from current, and an explicit expected-before Source Hash equal to current. Current has one matching stored Job Evidence row; proposed has one matching scoped legacy evidence operation and no stored row. The observation reports unchanged stores.

This is positive evidence of a recorded guarded before-to-after source-version transition. It is more specific than unexplained source disagreement, and may remove the need to ask the owner to arbitrarily choose between two hashes. It is not yet proof that the proposed content is authoritative, and does not pass installed recovery.

Installed `exact_control_before_prefix_recovery.py:150–156` requires the materialized row's source to equal the operation's proposed explicit source. It does not recognize the explicit expected-before source as a supported transition. Its derived-current-guard branch at lines 112–128 is only for present, non-append metadata operations, whereas this operation has append_if_missing true and explicit source ownership. The ordinary selected validator likewise requires proposed/current source equality (`exact_selected_legacy_recovery.py:101–107`), in addition to its earlier Company-prefix prerequisite. Completed legacy migration fails earlier at the incomplete cursor. No installed alternate observed here permits this transition through terminal publication.

Smallest independent review before changing this protection:

1. Inspect the exact immutable op194 plus its associated proposed evidence operation/inventory content and the current exact Job History/Job Evidence pair. Verify authoritative current expected-before values, stable Job Key/Company, unverified-suffix location, and that proposed Source Hash actually identifies the scoped proposed source content. Counts and hashed identifiers alone do not establish that last fact.
2. Review a narrowly typed **unverified-suffix source transition** in the late-control candidate, preserving original operation/cursor and old evidence, with exact before/after binding and under-lock current-value recheck. Trace that the successor retains the old-source compare guard until the actual transition and that its receipt fingerprints bind the intended new source. Do not replace proposed source with current, treat evidence absence as confirmation, or relax general ownership equality.
3. Independently prove this one recorded positive transition and refusal of wrong expected-before/source evidence/Company or a transition in the settled prefix; prove changed current state between preview and application is held and a crash/replay cannot apply twice or lose the old evidence. This is additional supported behavior requiring review, not an existing recovery command.

Even acceptance of that new narrow source proof would first produce the existing late-control local hold. `control_before_prefix_runner.py:1–6,58–93` still has no generic commit/publication/release fallback. Keep that separate missing continuation explicit rather than treating accepted source transition proof as finished recovery.

Input and installed source pins:

- RESULT.json: a5f71ec101ecf400af5334b4ea9b307f599858f4477b40be8263d77d0299e692
- exact_control_before_prefix_recovery.py: e1009026dcbb44cb507033c4ebdf92ec08a846fb2e374e57c96aea657a5419a8
- control_before_prefix_runner.py: 594a7f0b459ad175776b2654e72d86772943db5bc4aded5223b576a32c77f47f
- exact_selected_legacy_recovery.py: 95903b3554edd9eafeef85b248c8c52df95e12f0590d43d76676455e9f08c97f
- exact_recovery_terminal.py: 00ee18274ce81aa7453a5a09f80184f162e5d17847c2a6d6348fce9551569d52
- exact_recovery_pause.py: e4c71f08f7c443b254ec300dd433845b81872f0e0c8ae19b03c7b000002dfa68
