# S5 pre-install qualification review — 2026-11-20

Decision: add a narrow automated-release entry point immediately before `release_controller.release_and_schedule`. Preserve the existing installer, post-install verification, rollback journal and reviewed/manual callers. A saved-capture success is not release qualification. The first disposable slice should prove rejection of all existing offline evidence without enabling a real release.

## Observed boundaries

- `/tmp/jsh-s5-ordinary-current-tools.0HAtnw3z/src/job_search_helper/release_controller.py:22–29` calls the installer before scheduling a retry. This is the smallest composition boundary.
- The same tree's `integration_release.py:277–343` validates source/dependencies before and inside the scraper lease, then creates the rollback record at 316, writes PREPARED at 324, replaces files at 330, and invokes `verify` only at 337. Rejecting offline evidence in `verify` is too late for the requested no-install-side-effect guarantee.
- `ordinary_verifier_handoff.py:297–328` reopens the owner-selected physical slot and emits `mode=offline_saved_captures` and `application_authority=False`. Its positive disposition is `VERIFIED_MISMATCH`, not a successful real candidate qualification. Preserve both enclosing mode and nested receipt provenance during composition.
- `/tmp/jsh-m5-live-authority-repair.jMbESo7E/dev/pre_release_validation/validate_candidate.py:24–30,352–372` distinguishes `synthetic_fixture/FIXTURE_PASS` from `captured_public/PUBLIC_EVIDENCE_ACCEPTED`; public evidence explicitly has `release_qualification=False`. Synthetic receipts need not contain that field, so absence must reject too. These schemas currently provide no live-qualified producer.
- The current tools slice has no installer/controller tests. Reuse current production tests, not the older mirror copy: `/home/chris/job-search-helper_old/tests/test_release_controller.py:68–77` includes the second Company revision read inside admission; the mirror test omits it. No tests were executed in this review.

## Minimal interface and evidence

Add `src/job_search_helper/automated_release.py` with one coordinator-only operation that first obtains an immutable qualification from an owner-provisioned evidence reader. The operation must not accept a free receipt dictionary, arbitrary receipt path, caller checksum, or caller-set `qualified=True` as authority. Reuse the existing owner-slot custody pattern; do not duplicate its physical identity checks.

Before the controller is called, require:

1. A recognized, independently accepted live-candidate receipt schema and producer identity, read from its assigned owner record. Require explicit live collection mode and explicit release eligibility, with no offline/fixture/public-only provenance in the bound chain. Unknown, missing, contradictory or false fields hold. A caller changing the disposition or recomputing hashes cannot upgrade evidence.
2. The exact failed request, Company ID/source revision, qualified repair capability, dispatch/publication identity and candidate/release scope. The mapping-mismatch receipt explains why repair is needed; it cannot substitute for candidate validation.
3. Exact candidate source/configuration/dependency vector, reviewed verifier and measurement tool pins, complete scoped release files, and the canonical validation receipt digest named by the release manifest. Independently remeasure the selected candidate before entry. Verify current source/claim eligibility and policy freshness, including one original deadline/budget and no replacement attempt.
4. Bounded real collection provenance with independent employer authority, complete stable listing/detail evidence, full descriptions, required regression control and explicit zero evidence where relevant. Existing saved public corpus results remain useful regression evidence only.

The wrapper supplies the existing `verify(project_root, manifest)` callback from the accepted qualification. That callback measures the installed source/configuration/dependencies and checks its exact semantic evidence against the frozen pre-install receipt. It may return the canonical pre-approved evidence only after those checks succeed; it must not be a constant receipt-returning callback. Keep `validation_receipt_sha256` stable: volatile post-install timestamps/paths belong in separate measurement evidence, not a new incompatible receipt digest. Any installed mismatch retains the current nonterminal journal and produces no retry.

Long collection/replay stays outside scraper and writer leases. If eligibility can be withdrawn between qualification and admission, a short optional admission recheck must be forwarded through the controller to the installer and run under its existing lease before `_prepare_record`. Existing callers retain the default behavior. Do not acquire the same lease in the wrapper or run the verifier under it. A prototype that only proves early offline rejection can defer this hook; it cannot claim live release readiness without closing this race.

Completed-release replay must reopen the same durable qualification and the existing completed release receipt, then reuse the same retry attempt. It must not recollect or manufacture a new attempt/deadline. Exact completed release identity and installed bytes remain checked by the existing installer.

## Disposable implementation and ownership

| Owner | Exclusive files | Scope |
| --- | --- | --- |
| Implementation | New `src/job_search_helper/automated_release.py`; new `tests/test_automated_release.py` | Qualification adapter, early refusal and post-install adapter. No production wiring or live producer in first slice. |
| Coordinator | Candidate baseline/hashes and, only if needed, `release_controller.py` plus `integration_release.py` | Preserve compatibility; optional short admission callback after independent review. No worker edits these shared files. |
| Independent QA | Separate disposable probe file and report | Adversarial composition, forbidden-call spies and before/after filesystem snapshot. No source fixes. |

Freeze a source-only disposable copy of the measured current tools tree, plus the current production release tests and their fixture dependencies. Avoid copying `.state`, `.venv`, job data, captures or unrelated temporary results. Run only new gate tests plus current installer/controller regressions; widen only for a changed seam.

## Required test cuts

- Parameterize `offline_saved_captures`, `FIXTURE_PASS`, `PUBLIC_EVIDENCE_ACCEPTED`, unknown/missing mode, false/missing eligibility, pending/failed/timed-out result and genuine `VERIFIED_MISMATCH`. Refuse before `release_and_schedule`, `activate_release`, writer-lock acquisition, `_prepare_record`, journal write, copy, retry bridge or verifier start. Assert no new record directory, release journal or request, and unchanged pre-existing artifacts.
- Preserve negative evidence through nesting/wrapping. Relabeled PASS, recomputed digest, substituted Company/source/request/candidate/producer, and a caller-supplied path must not pass custody or qualification checks.
- Drift candidate source/config/dependencies, current Company/claim, policy, receipt or physical owner record after qualification. Reject before backup; test admission-time drift separately if the hook is implemented.
- One accepted synthetic authority fixture exercises call order only: qualification precedes controller; actual disposable installation precedes installed measurement; exact verification precedes one retry. Label this fixture evidence, not production live qualification.
- Installed measurement failure leaves the existing nonterminal journal and no retry. Existing rollback restores only recorded files. Preserve crash-after-activation replay and existing pending-request waiting behavior.
- On repeat, no reinstall, recollection, new budget, receipt or retry attempt. A changed qualification cannot replace the already-bound one.

Acceptance of this slice proves an automated gate rejects unqualified evidence before installation and preserves existing release behavior. It does not qualify any current candidate or deploy anything. No tool check was flagged. This review changed only this report; no source, live application, network or job data was modified.
