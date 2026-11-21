# Atomic Machines uncertain intake and future append design

Independent read-only source review, 2026-11-20. No application run, production database/service access, append, restoration, or code edit was performed. Public Google documentation was read. Root supplied the actual absent remote/local observation and decision to run rollback; this reviewer did not independently read live data.

## Current attempt

The existing claim must remain uncertain and spent. Exact remote readback could have continued the same claim with no new append; an absent row deliberately refuses at `atomic_machines_intake.py:301–302`. The helper spends and fsyncs the claim before its sole append at lines 89–98 and 295–300. It never retries a claimed absent row. The maintained tests explicitly separate successful recovery after a lost acknowledgement from absent-row refusal (`test_atomic_machines_intake.py:118–140`).

No audit-grade definitive no-commit receipt exists in this helper. `_claim_bytes` (lines 57–66) contains intended workbook/table/headers/row and local DB identity, not a server response or outcome. The repository write boundary wraps every exception as `UncertainWriteError` and does not durably persist a server status (`repository.py:644–688` in the inspected `/tmp/jsh-s5-issuance-enrollment.OSygejTK` source). The original exception is chained in memory with `from exc`; that is not durable evidence after a caller discards it. Current absence cannot distinguish never committed, still uncertain, or later removed data. Do not reset this claim, change the Company ID/custody path to evade it, or infer noncommit from a retryable-looking error class.

The installed private release has only these reviewed alternate-checkout restoration routes:

| Terminal source | Required restoration evidence |
|---|---|
| INSTALLED | Exact completed retained pilot, confirmed publication, canonical COMPLETE/no-repair outcome, and matching sender/receiver delivery |
| ROLLED_BACK | Exact original protected-state proof and no admitted pilot selection |

Evidence: native `pilot_restore_command.py:188–208`, `pilot_restoration.py:21–28`, and `retained_pilot_terminal.py:25–108`. There is no installed/no-pilot selection. `Controller.restoration_terminal` holds the joint leases and checks the exact terminal release but does not itself reopen alternate checkouts (`controller.py:1120–1137`). `HostExchange.restore` accepts only a terminal callback proved by its reviewed caller (`host_exchange.py:439–459`); supplying a new permissive callback would bypass that acceptance contract.

Therefore rollback followed by the existing pre-pilot rollback observe/independently approved restore is the smallest already-supported way to reopen alternate checkout routes without completing this pilot. It still requires fresh original protected evidence; rollback does not erase or resolve the uncertain remote append.

Native source pins read:

- `controller.py`: `927063a9797c121a8c6e4b73011a79ea2874d72427c64387e969355503b092eb`
- `pilot_restore_command.py`: `396b5f391b96642f9e9defc1be6832b6489232079c31efde30aaba2d77562816`
- `pilot_restoration.py`: `3533483bb041714a41bb33e8d84f514cd2a4b99ae54313a8ed9b552d32f5ea2e`
- Intake helper: `4127e7c6e7b26fc0b5a9a87cc6df0856b4e59bb4d962bcdaffd7dc58563dd73b`

## Future fresh enrollments

Recommendation: design a separate versioned intake using one frozen developer-metadata ID and exact claim digest, created in the same batch as one native-table append. Do not retrofit it onto the uncertain legacy claim.

Google documents that an explicitly supplied metadata ID already in use makes creation fail; keys alone are not unique. [Metadata guide](https://developers.google.com/workspace/sheets/api/guides/metadata). It also documents atomic application of batch subrequests, with no changes when a request is invalid. [Batch guide](https://developers.google.com/workspace/sheets/api/guides/batch).

**Design inference:** under those guarantees, retaining the unique metadata object makes an exact repeated batch fail before producing a second append. This closes a lost acknowledgement without needing to infer a negative commit from HTTP status. It is not a claim of unconditional exactly-once behavior under arbitrary metadata deletion or replacement.

Minimum protocol:

1. Before any write, freeze a new versioned immutable intent: independently approved workbook, table and ordered-header pins, literal row, Company identity, stable positive metadata ID, metadata key/value convention, and exact request bytes/digest. Compute the claim digest from the inner immutable intent; put the request digest outside it to avoid a self-referential hash.
2. Send exactly one `spreadsheets.batchUpdate` containing `createDeveloperMetadata` and `appendCells(tableId=...)`. Never split them into separate requests. Keep the existing one-row literal `userEnteredValue` scope. Native table appends account for free rows and footers. [Tables guide](https://developers.google.com/workspace/sheets/api/guides/tables).
3. Associate metadata with the spreadsheet, not the unknown appended row. Freeze visibility and require the same permitted reader context. The metadata value contains a digest, not private row text or credentials. Metadata IDs are spreadsheet-scoped; metadata associated with a deleted object disappears. [Metadata resource](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.developerMetadata).
4. Reconcile by reading the exact metadata ID and checking ID/key/value/location/visibility plus the current unique literal Company row through the existing native-table reader. Matching metadata alone does not confirm the current Company. Only both exact proofs allow the existing atomic local row/baseline/revision/event/receipt transaction.
5. A missing marker after uncertainty permits an exact bounded repeat only under an independently established marker-retention/structure contract. The same original ID and exact body must be reused. If the earlier request commits late, duplicate-ID failure becomes the successful fence; reread evidence. Existing foreign metadata, changed digest, partial/missing row with a matching marker, ambiguous permissions, or marker custody loss holds. Never delete a marker to recover an attempt or allocate a replacement ID after dispatch.
6. Keep local terminal enrollment/confirmation immutable. Once acknowledged/confirmed, missing remote evidence cannot reopen append permission. Preserve the marker for the supported replay lifetime. No automatic marker cleanup may invalidate an uncertain attempt's duplicate guard.

**Required limitation:** Sheets collaboration can alter the resulting document even though the batch itself is atomic. [batchUpdate reference](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate). If a first batch commits, its acknowledgement is lost, and a collaborator deletes its marker before readback, a same-ID retry may append again. Spreadsheet-level location prevents routine row deletion from removing the marker, but explicit metadata deletion remains possible. Project visibility is not a security boundary. Without retention authority, continue the current fail-closed absent-marker behavior; do not claim this design solves arbitrary collaborator tampering.

## Alternatives and exact tests

A frozen named-range ID has a comparable duplicate-ID rule, but introduces a visible range object/location and supplies no simpler claim-value record. [AddNamedRangeRequest](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request#AddNamedRangeRequest). Numeric-cell updates, values.append, a local lock, or a second plain append do not provide this server duplicate fence. A new Apps Script endpoint would expand deployment and authority substantially. Metadata is the smallest promising future change; retaining the present no-replay hold is smaller if recovery is not required.

Required disposable tests before a separate bounded real acceptance run:

- One successful atomic batch gives exactly one metadata object, Company row, revision 1 event, and local receipt.
- Commit then lose acknowledgement: readback confirms once; repeated same batch creates no second row.
- Fail before commit: neither marker nor row exists; bounded exact replay creates one of each.
- Two concurrent/in-flight same-ID batches and a delayed first commit: at most one append.
- Invalid append after metadata creation request: atomic rollback leaves neither object. Existing foreign metadata ID: no append and no new-ID fallback.
- Wrong workbook/table/header/digest/visibility, metadata-only/row-only, duplicate alias, footer, literal-to-formula change, and local collision all hold without local event creation.
- Crash before dispatch, after remote commit, during local transaction, and after local commit preserve one exact enrollment and never reset a spent attempt.
- Marker deletion after lost acknowledgement demonstrates the retention limitation; no acceptance claim may conceal it.
- Legacy version-1 uncertain claims stay readback-only and cannot enter the new retry path.

Persist only allowlisted audit facts: attempt ID/sequence, frozen request digest, bounded time, error category, and numeric HTTP status when actually observed. Record unknown explicitly. Never log exception strings, response/request bodies, full headers, OAuth material, or credential paths. Capture safe status before redaction; status alone must not authorize a changed append. This review implemented none of the proposal and did not rerun the old attempt.
