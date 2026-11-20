# Operator retained post-settlement recovery — independent QA

## Verdict: REJECT

The operator provenance identifier is consistently derived as
`operator:<request_id>`, archive payloads round-trip through the canonical
request parser, repair provenance is rejected, mixed provenance is rejected by
that parser, and the retained admission/publication records bind request,
provenance ID, exception cycle, company, manifest, and evidence digests.  The
existing archive/unlink/receipt crash recovery and newer-request preservation
also remain intact.

## Must fix — recovery ignores the durable operator request receipt

For an operator request, the original receipt is the durable evidence that the
operator-owned one-company request was actually queued.  The initial retained
preflight reads it and freezes its digest into `event_receipt_digest`.  But
`_recover_settled_consumption()` only validates the archived request’s
self-consistency and then its admission/publication rows; it neither reads the
operator receipt nor compares its canonical content/digest with the frozen
payload ([retained_company_event.py:111-190](../../src/job_search_helper/retained_company_event.py)).

Direct adversarial checks prove the gap:

```
operator_source_receipt_exists= False
recovery_without_operator_source_receipt= FIRST_PASS_RELEASED_CONSUMED
recovery_with_invalid_operator_source_receipt= FIRST_PASS_RELEASED_CONSUMED
```

Thus a missing or forged operator source receipt is silently accepted after
archive/unlink, despite the recovered admission claiming a receipt digest.  It
also means a fully self-consistent forged operator archive/admission can avoid
the external operator-origin evidence during recovery.

Require the expected operator receipt path
`operator-company-requests/receipts/<digest({request_id})>.json`, validate its
schema, request ID, company ID, source revision and `request_sha256` against
the archived request, and require `digest(receipt)` to equal the frozen
admission payload’s `event_receipt_digest`.  Missing, malformed, or changed
receipt must hold without writing the consumption receipt.  Add tests for all
three, plus forged operator request ID/source/company and forged
admission/publication provenance.

## Evidence

The strict retained-adjacent production-wrapper suite passed:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_retained_company_event tests.test_retained_work_runner tests.test_retained_work_exception tests.test_retained_work_orchestrator tests.test_retained_work_publication tests.test_selected_recovery_integration
Ran 96 tests ... OK
```

Those tests omit the missing/invalid operator-source-receipt boundary above.

## Superseding re-review — ACCEPT

This supersedes the rejection above.  Recovery now re-reads the exact original
source receipt before trusting frozen admission data.  It uses the canonical
operator receipt path derived from `request_id`, or the canonical Company-event
receipt path derived from `event_id`; it requires the exact schema and field
set, correct request/company/source/revision bindings, allowed written state,
and the archived request hash.  Its digest must equal the frozen admission
payload’s `event_receipt_digest`.

Independent direct checks now hold closed for both provenance types:

```
operator missing held= retained_event_consumption_provenance_receipt_missing
operator forged held= retained_event_consumption_provenance_receipt_changed
event missing held= retained_event_consumption_provenance_receipt_missing
event forged held= retained_event_consumption_provenance_receipt_changed
publication_forgery_held= retained_event_consumption_release_changed
```

The canonical request parser rejects mixed provenance, malformed event
revision, and repair retries before recovery authority is read.  Existing
archive/unlink crash convergence and preservation of a different newer request
remain covered; operator provenance reaches both admission and publication via
the exact `operator:<request_id>` identity.

Strict production-wrapper retained-adjacent suite:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_retained_company_event tests.test_retained_work_runner tests.test_retained_work_exception tests.test_retained_work_orchestrator tests.test_retained_work_publication tests.test_selected_recovery_integration
Ran 96 tests ... OK
```

No release blocker remains for the requested operator/event post-settlement
recovery scope.
