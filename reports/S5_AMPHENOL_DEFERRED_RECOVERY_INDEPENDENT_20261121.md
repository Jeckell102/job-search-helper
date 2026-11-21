# Deferred released-repair checkpoint: independent QA

Date: 2026-11-21. Verdict: **ACCEPT for this narrow source-only repair.** No concrete gate failure found. This does not accept deployment, remote publication, or the sibling Inbox-binding change.

Reviewed candidate: `/tmp/jsh-s5-deferred-v2-recovery.au1gV3DJ`. Tests ran on a private copy of its `composed/src` plus its maintained tests at `/tmp/jsh-s5-deferred-recovery-independent.mabta1eo`. No production/model/provider/Google operations; network connection and DNS audit events denied. System `/usr/bin/python3.11 -I -S -B`, pytest plugin autoload and bytecode disabled. The copied pytest support and system dist-packages were explicit test dependencies.

## Frozen inputs

- `src/job_search_helper/exact_cycle_recovery.py`: `0985fe2b73f7d6859dbdadb7d0586d920c38d776c4f7cb6879cfb77d57e33645`.
- `tests/test_deferred_repair_exact_recovery.py`: `ec4a38e0351bf58bcaa7cf66c516d0c4984d60b6ce7fe4b66f28a653990695e2`.
- Composed `exact_cycle_receipt.py`: `f44d1ea8c52e829a3fb7bbe6b4f6c809c53c44690949173217e5e7b4bde8d334`.
- Composed `publication_receipts.py`: `920865c13b2cf1acab6ed799bdd440ad13ee234b576f40424ceb528b9651933c`.
- Independent `test_independent_deferred_gate.py`: `9e6696c7876661e3d26f7b8b85f9dfd1071ddb8c2ad0e191e2248078bcb2284b`.

The requested source and maintained-test pins were rechecked after execution and match both the candidate and the private copy. A complete copied-source pin record is `COMPOSED_SOURCE_PINS.json`.

## Findings and evidence

1. Admission is the ordinary one-company released repair's actual `inventory`, durable, unprocessed checkpoint. Source lines 64–80 require exactly one company, In Progress, all=False, compact local storage, no locally_processed/jobs keys, no foreign event/operator/selected/temporary/retained scope, exact unprocessed Inbox payload, and matching saved payload metadata.
2. Source lines 82–109 require the exact canonical last request and fingerprint, matching retry/activation identity, current COMPLETE runtime release, release-journal assertion, and the exact current eligible unclaimed Company/revision/active cycle. A foreign frozen plan cannot supply lost repair lineage (lines 129–140).
3. Source lines 149–190 apply and verify local chunks, advance the exact cursor, verify the complete application, and verify the LOCAL_VERIFIED mirror/application/records identity. Only afterward, lines 192–201 reread the original State and all deferred guards before advancing the checkpoint. The repair receipt is checked before and after the local phase (141–144, 209–216).
4. Maintained fresh-path fixture uses the actual RepairRetryBridge, requested_scan, and defer-sync Engine checkpoint against disposable SQLite. It verifies one local Job History row and the exact request/release receipt before stopping at a substituted publisher. It refetches neither on fresh recovery nor replay. No Sheet publication is claimed.
5. Maintained state-cut fixture reaches verified local application while the State save fails, preserves the deferred State, and then resumes without calling apply_exact_local_plan again. This is the relevant verified-local/app-checkpoint crash cut.
6. Maintained negative cases hold altered request time, inactive release, payload drift, and a foreign frozen plan before publication; affected cases also assert no local jobs. Existing exact-cycle recovery cases remain passing.
7. Two independent cuts additionally prove that failed local verification leaves State untouched and its mirror FROZEN, and a State change after local application/verification is held without overwriting that change or setting locally_processed. The latter retains the exact LOCAL_VERIFIED local proof for later reconciliation. Neither reaches remote commit.

## Execution

- `tests/test_deferred_repair_exact_recovery.py` + `tests/test_exact_cycle_recovery.py`: **29 passed in 5.24s**.
- Independent `test_independent_deferred_gate.py`: **2 passed in 0.93s**.

No candidate edits were made. The sibling Inbox-binding work was neither reviewed nor accepted. This verdict establishes the checkpoint repair with the supplied composed receipt dependencies; genuine remote publication and native release remain separate acceptance gates.
