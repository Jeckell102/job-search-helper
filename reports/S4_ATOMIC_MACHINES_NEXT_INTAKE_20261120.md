# Atomic Machines: next intake handoff

2026-11-20. Independent read-only review. No live read, network request, source change, job-data change or coordinator-card update was performed.

**The next data gap is final workbook/table enrollment plus a real new Company ID and its one eligible event.** The accepted source exists, but the saved preview did not create those inputs. Source installation alone does not settle intake.

## Existing evidence and reusable reader

- `/tmp/job-search-helper-integration-automation/temp/integration-coordinator/S4_ATOMIC_MACHINES_WORKBOOK_READBACK_20261120.md` records the actual working workbook check at 18:15 Eastern: one native Companies table, 17 compact columns, no selected name/board collision, no official-domain match remotely or locally, and completed local external baseline. It recorded four workbook reads, zero writes, no new Company row, no event and no enrolled dispatch ID. These are historical observations requiring refresh, not present-state proof.
- `/tmp/jsh-s4-company-intake.R5s9VWJ6/atomic_machines_intake.py:147` contains `_remote_view(remote, scope, row)`, the reusable read-only Companies-grid probe. It checks the exact sheet/table, bounds, ordered literal headers and selected identity in one response, returning `(headers, matching_row_or_None)`. Calling `intake()` is a separate write operation and is not the probe.
- No standalone saved workbook-probe script was found in that worktree or the coordinator report/source tree. The memo preserves results, not the raw spreadsheet/sheet/table enrollment values. Reuse the reader through the reviewed installed main-workbook client; do not invent a command or infer the missing IDs from the memo.
- The intake source and supplied tests still match the independently accepted pins: `4127e7c6e7b26fc0b5a9a87cc6df0856b4e59bb4d962bcdaffd7dc58563dd73b` and `77a44f7066231d43df0f06675d3aea22a29128a36f5631a06ca1914f417c91c9` respectively. The earlier 19-case acceptance is recorded in `S4_ATOMIC_MACHINES_INTAKE_INDEPENDENT_QA_20261120.md`; tests were not rerun in this data handoff.

## Prepare these exact inputs after source installation

| Input | Required value or fresh observation |
| --- | --- |
| Working workbook | The actual main workbook from installed configuration, matching the local Jobs workbook. Use compact-v1 with `evidence_archives=False`; exclude the backup workbook. Record its exact ID and digest in the private execution inputs. |
| Companies layout | Current numeric sheet ID, unique native table ID, table bounds beginning at A1, and the actual ordered 17 literal headers plus their digest. Do not substitute the unordered schema set for header order. Verify the selected row will be in the table body, not a footer. |
| New Company ID | A fresh `COMP-` plus 12 uppercase hexadecimal characters, absent remotely and locally, with no prior local revision/intake history. No official ID was assigned by the 18:15 preview. |
| Exact selected row | `Company=Atomic Machines`; that new Company ID; `Company Status=Active`; `Official Careers URL=https://job-boards.greenhouse.io/atomicmachines`; `ATS / Source=Greenhouse`; the approved ISO `Date Added`. Preserve unrelated fields and rows. |
| Employer/source evidence | Refresh the relationship between `https://www.atomicmachines.com/join` and the exact Greenhouse board. Recheck normalized name, exact ID, provider-board aliases/rich links and `atomicmachines.com` across the workbook and local Companies. The official-domain check is separate from `_remote_view`. |
| Local baseline | Local ready state, compact profile and completed external Company baseline (`company_event_external_baseline=yes`); no pre-existing selected Company, source history or conflicting ownership. |
| Selected pilot scope | Freshly confirm this exact Company/name/source/board is outside the preserved `CYC-B639C6D864EC` membership. The saved provisional check used no actual Company ID. Keep the historical record unchanged. |

The fixed intake row intentionally stores the Greenhouse board in Official Careers URL. Keep the separate employer-site link as selection evidence; silently substituting that URL would change the reviewed row and its source revision.

## Execution order and expected output

1. After the reviewed installation is verified, repeat the bounded read-only workbook/local checks above and save the exact final input set. Arrange the bounded intake window so the Companies table layout remains stable through the one-row append.
2. Use only the accepted selected intake helper for the one Company. Do not use a broad pull, general Company-ID assignment or a normal backlog start to manufacture its inputs.
3. Read back the exact literal remote row and the corresponding local Company/baseline. The successful local result must contain exactly one numeric revision **1**, one `company.eligible` outbox event, the matching canonical Company fact/source revision, and origin **`sheets-reconciliation`**. Keep the actual returned `event_id`, `company_id` and `source_revision` as the next stage's inputs. A matching row created by another importer is not equivalent provenance.
4. Feed that real event through the approved retained historical-blocked route. Bind the resulting exact request and event delivery to the same Company/revision. Do not fabricate event/request data from the prospective Company row or use the ordinary idle route while the historical cycle remains unfinished.
5. During the pilot record its fresh fetched count and ordinary filtering result. The old sample of **36** postings is selection history, not an expected acceptance count. Verify exact publication, immutable outcome and both delivery receipts independently before calling the selected chain complete.

If the append result is uncertain, the same attempt may only be read back and reconciled; do not append another row. Missing, duplicate, partial or changed selected data remains held for exact inspection. Keep broad backlog, automatic retry dispatch and automatic releases disabled. This pilot proves only its selected historical-blocked chain; ordinary idle and actively busy acceptance remain separate roadmap work.

Sources: `S4_ATOMIC_MACHINES_INTAKE_STAGED_20261120.md`, `S4_ATOMIC_MACHINES_WORKBOOK_READBACK_20261120.md`, `S4_ATOMIC_MACHINES_PILOT_PREFLIGHT_20261120.md`, `S4_ATOMIC_MACHINES_INTAKE_INDEPENDENT_QA_20261120.md`; accepted helper `IntakeScope.row():27-56`, `_remote_view():147-214`, `_require_event():226-250`, `_confirm_local():260-289`, and `intake():307-327`.
