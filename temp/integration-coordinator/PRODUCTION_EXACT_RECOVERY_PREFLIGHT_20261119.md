# Production exact-recovery preflight — 2026-11-19

## Decision

**HOLD — do not deploy or run the exact-cycle command yet.**

The production lock and release gates are clear and the three smallest
candidate Company identities agree between local authority and Google Sheets.
However, fresh live evidence exposed a compact-profile incompatibility in the
accepted publisher guard, and current production `runner.py` / `inbox.py`
contain newer behavior that must be reconciled rather than overwritten.

## Read-only live evidence

- The normal production lock `/home/chris/job-search-helper_old/.state/scraper.lock`
  was acquired nonblockingly and released normally.
- `assert_release_settled(.state)` succeeded and returned no pending release.
- The Google preflight issued five reads and **zero writes**.
- `COMP-0035`, `COMP-0052`, and `COMP-0054` each matched exactly once in the
  compact Sheet and local SQLite authority on Company ID, Active status,
  provider, and SHA-256 digest of Official Careers URL.
- Local claim owner and claim token are empty for all three Companies. All are
  bound to `CYC-B639C6D864EC`. Local Scan State is Complete for 0035 and 0052,
  and Queued for 0054.
- A second narrow Google check proved the `Scan Cycles` tab currently has zero
  data rows, not merely a displaced target row. It made three reads and zero
  writes. The local SQLite row exists as row 48 with status In Progress, scope
  800, complete 18, partial 8, blocked 5, and remaining 769. There are zero
  dirty `Scan Cycles` cells.

The count difference from the earlier State checkpoint is expected to remain
unresolved until reconciliation; it is not being normalized or rewritten by
this preflight.

## Newly exposed activation defect

Production uses the `compact-v1` Sheet profile. `Claimed By`, `Claim Token`,
`Scan State`, and `Active Cycle ID` are intentionally local-only Company
fields. The accepted `exact_cycle_sync._company_guard` currently requests
`Claimed By` and `Claim Token` from Google. A real command would therefore fail
closed before a write, but it cannot satisfy the roadmap in production.

The repair gate is:

1. read the fresh local authoritative Company controls while the exact command
   owns the real normal lock;
2. separately read only remote-visible Company ID, status, and careers URL;
3. require exact agreement on shared controls and no local claim/manual hold;
4. use the same composite six-field evidence for planning and every publisher
   restart/readback decision;
5. prove compact-profile success and adversarial drift/claim refusal with zero
   remote commit or receipt on failure.

This is not permission to trust a stored plan's old claim fields or to omit a
control check.

That Company-control repair has now passed independent review: root reproduced
54 focused checks and independent QA reproduced a 158-test adjacent matrix.
It remains undeployed while the separate plan-projection gate below is open.

Fresh read-only plan-shape inspection found that all three retained candidate
plans end with a Companies operation containing compact-local-only fields.
0035 is at cursor 19/19, 0052 at 1/1, and 0054 at 67/208. They are therefore
legacy full-profile plans, not evidence of compact compatibility. No nonzero-
cursor plan may be silently projected, resealed, or have its cursor remapped.

New planning is also held: adjacent testing proved a newly planned empty
inventory seals local-only Companies fields, which compact Google rejects.
The profile-aware planner repair must freeze a deterministic remote-publishable
projection while retaining the full local finalization evidence and all manual,
salary, source-hash, and identity protections. Existing incompatible plans
must receive an explicit hold reason.

The same live profile evidence also prevents activation of the accepted bulk
pause executor as written: it expects local-only Company controls and an
existing remote `Scan Cycles` row. A later compact-profile pause repair must
separate local authoritative updates from the remote-visible Company subset,
freeze both projections before either is applied, and define a verified empty-
tab cycle-row insertion/finalization contract. The current executor fails
before mutation and remains undeployed.

## Source reconciliation boundary

Accepted checkpoint: `c689ebba5ede3c8b5189e88691550cf8c2d3855c`.
Current production Git commit: `c9db537d76dcb4dc22ace5d6342adc35c1085688`
with protected uncommitted work.

The eight accepted exact source modules are absent in production. Production
and accepted hashes differ for:

- `src/job_search_helper/inbox.py`: production
  `482895c72900ddcdfda1089090a6277af494bea7941b1f1289ac8f2ae5cb23cd`,
  accepted `0822a445f6aa6a155fad9d35b71acf89bbc35514002e05afe70baade474ff574`;
- `src/job_search_helper/runner.py`: production
  `db88178ec6e0a07779ea7216f5158604422bb072a93c4d3dd3c8aca8d6643df3`,
  accepted `fbcc7c3ddc899c16799a3f8ea38394a65558db77f5a0c61d436d5568ba1210ba`;
- `tests/test_run_scoped_sync.py`: production
  `dfda161dfb0ed2723ba184c21b16dfbc5478e248ade4dd05c28e734d9f31cd50`,
  accepted `6600b520f649bad2b4d3454b12b5ff282f91ee3e0aadee0d105328d17bea4ca0`;
- `tests/test_runner_cycles.py`: production
  `c7ac4b9d5483ab14277d0016980677ce38a76b1abb7af16208cb16170f38d809`,
  accepted `c5fc581a722f89cd05c371cab9e41326a25cbf1b4ae9625f5ea2bfc7631d910a`.

Direct replacement is forbidden. A staging reconciliation lane owns the merge;
an independent lane owns acceptance review. Production remains unchanged.

## Gates before first live write

- compact-profile guard repair independently accepted;
- current-production runner/inbox reconciliation independently accepted;
- scoped rollback copy and before/after hash manifest saved outside job data;
- current-production focused and adjacent test matrices pass;
- exact command containment proves no global synchronizer, review hooks,
  cleanup, outcome producer, or broad backlog/release path;
- fresh lock, release, local control, and remote visible-field preflight still
  matches immediately before execution;
- first action is one explicit Company only, with readback and receipt evidence.

Broad backlog processing and unqualified automatic release remain disabled.
