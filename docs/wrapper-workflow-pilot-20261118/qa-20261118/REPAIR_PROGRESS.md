# Coordinator QA repair progress

Goal started: 2026-11-18 19:05:23 UTC. Goal remains ACTIVE until independent final QA passes and reviewed changes are backed up.

Production controls remain OFF; no integration campaign or Jetson inference started during repairs. Jetson remains one inference lane. All work and evidence stay on MuleLab.

## Accepted finding 1

Campaign membership, individual pause/exclusion, selection and claim isolation are accepted in staging. Independent reviewer: 16 campaign tests passed. Full host suite: 161 tests passed. Exact legacy 102-task migration tested on a disposable database copy: dry run unchanged, first apply 102, second apply zero, identical post-apply bytes, integrity OK, controls OFF, shortened cohort rejected. Production migration is deferred until combined deployment.

GitHub backup: `backup/wrapper-pilot-20261118`, commit `cf7a227` (push succeeded).

## Accepted finding 2

Atomic pilot/campaign/queue transitions accepted after the terminal-status bypass was fixed. Independent transition tests12/12 and full host suite174/174 passed. GitHub backup `4ef6dde` pushed successfully.

## Accepted finding 3

Canonical identity and company registry implemented. Exact102-member identity migration passed on a disposable database: dry run unchanged; first apply102; second apply0 and byte-identical; old budgets, statuses and history preserved; integrity OK; controls OFF. Independent testing caught an activation-fields mutation bypass after the initial188-test pass; post-update validation now rolls it back. Final independent full suite190/190 and focused45/45 passed. Roadmap accepted. Group4 exact edit scope and independent acceptance assertions now in progress. Group3 GitHub backup b71c399 pushed.

## Current remaining work

6. Durable campaign completion and truthful reporting (final boundary regressions).
7. Scheduler ownership, baseline inputs, reproducible deployment.

Then: independent final QA using fresh reviewers. Any failure creates a new report and fresh repair/verification lanes; the goal remains active until re-QA passes. Live scraper validation and installing generated wrappers remain separate gates.

## Finding4 verification in progress

Exact edit scopes, audited operator scope expansion, pinned original test/config/fixture bundles, and separate acceptance sandbox implemented. CLI supports reviewed approval JSON and structured status. Real OS sandbox rehearsal passed: editable stub passed, immutable assertion failed on broken source, then passed on correct source. Legacy102 identity/scope/baseline migration rehearse remained idempotent. Direct shared-checkout versus imported frozen-checkout baseline regression fixed. Independent verifier is completing receipt-scope binding checks; full combined suite running. Production stays unchanged and paused.

Roadmap review found the raw host mutation tool treated a missing scope context as unrestricted. The coordinator path was scoped, but this default could permit a future bypass. Group4 remains open until missing context rejects mutations; the authenticated manual shared-checkout route will provide explicit request-scoped authority. Scope digest/version also must be retained in independent acceptance receipts.

Group4 ACCEPTED after all corrections: independent13/13, combined35/35, full214/214, actual OS-sandbox check PASS. Group5 now active with fresh inference-reservation implementation lane and independent verifier. No production changes.

## Finding5 independent verification

Atomic inference reservations, a serialized worker-session lease, exactly-once usage reconciliation and durable redacted model receipts implemented. Uncertain requests globally block later companies and re-enabling scheduling, including after restart. Independent13/13 and combined84/84 passed; corrected concurrent session double-count race. Legacy migrations reject unresolved inference; exact102 rehearsals still pass. Final full suite running. Group4 backup3289365 pushed.

Group5 ACCEPTED: final full231/231 and roadmap highest-risk5/5 passed. Group6 durable reconciliation/reporting now active.

## Finding6 rehearsal and ongoing checks

Two-company offline rehearsal passed using actual guarded edits, Git workspaces and OS-sandbox tests with simulated web/model responses: 15 steps, 4 model callbacks. Company1 failed its initial assertion, was repaired, then passed editable and immutable acceptance; company2 stopped blocked. Context/workspace isolation, pause/restart counter/receipt preservation, terminal exception accounting and repeated status stability passed. This is host-workflow evidence, not live Jetson or scraper certification. Independent reviewers found additional late-result control-generation and in-flight quiescence cases; Group6 stays open until those fixes and final verification pass. GitHub Group5 backup f950f3c pushed successfully.

Group6 final review: independent13/13, combined59/59, full250/250 and real two-company rehearsal passed before two additional boundary findings. Status was implicitly sealing a partial pre-start batch roster; also an old drained campaign could disable a separately started generic queue on a later status read. Group6 remains IN PROGRESS pending explicit activation sealing, atomic late-import rejection, observational terminal status, and new regression/full checks. Group7 remains waiting.

Group6 ACCEPTED IN STAGING after final boundary fixes: independent15/15, campaign-focused39/39, implementation/control focused62/62, final frozen full254/254 (22.010s), and actual OS-sandbox two-company rehearsal PASS. Exact historical live receipt compatibility independently verified against both original pilots. Group7 is next; production remains paused and unchanged.
