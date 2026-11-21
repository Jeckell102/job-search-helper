# Independent operator enrollment bridge QA

REJECT the reviewed initial bridge. No production, network, Sheets, Jetson, service, or candidate edits were performed.

## Exact reviewed pins

- `host_server.py`: `efc81759eefa82c27582f15590a1936b01f91d887c5a1b08508934114788fd7e`
- `amphenol_recipe_choice_input.py`: `38344002ebb9f57019e59cbb7f0b7e3d1aeb499466a534bddcb2ece91a52bd5c`
- `test_amphenol_operator_enrollment.py`: `6cd8d9125f872fb38865cccbe182e040deb23bcfcfb111ff81ae24fb118d3abf`
- Existing compiler `amphenol_recipe_candidate.py`: `126b2d4c29e4aa7a26acd0f7f00d813031475bfb7fe07bb30920513c0daf67ae`

Candidate root: `/tmp/jsh-operator-owned-bridge.xu59ooer`. Initial bridge files copied to `rejected-source/` before author repair.

## Must fix

1. Genuine Company input cannot proceed. `prepare_operator_choice_input` (line182) demands `ats_source == 'AcquireTM'`. Actual `current_company_repair_snapshot(repository, company_id)` has the correct call signature but returns canonical lowercase `acquiretm` (`company_events.py` lines45,103). The event projector already uses lowercase. A real typed partial, completed settlement and genuine two-sided outcome receipts still yield `None`. The four authored bridge tests manually use uppercase and substitute both receipt validation and typed outcome recognition, concealing this integration failure.

2. Terminal source evidence is not reread exactly before delivery or promotion. `OperatorAmphenolRecipeEnrollment.settled` (host lines465–479) checks the stored settlement and digest grammar only. `read_operator_owned_choice_input` (choice lines126–132) obtains the actual owner and observation but omits equality to the receipt's terminal State/mirror digests and request fingerprint. Independent reproduction changed the actual persisted State Company's stage from `partial` to `queued`, making its digest unequal to the saved terminal digest. The host still returned settled=True. After compensating only the first finding's capitalization mismatch at the snapshot boundary, the actual owned reader still returned the identical prompt. No receipt or witness verifier was replaced in this proof.

The narrow repair is a shared read-only verifier used by both `.settled()` and the owned choice reader, checking the exact admitted terminal cycle, mirror, request fingerprint, observation and no matching pending request before sender delivery and again before promotion/continuation. Preserve initial and promoted receiver custody checks and hold on disagreement. This review does not require new release authority.

## Evidence and positive observations

`python3 -B /tmp/jsh-operator-bridge-qa.9Ox0aYS7/run.py`: 8 passed in 0.95s. Includes four authored cases, two independent cases, and two parametrizations of the imported existing adapter fixture. The passing independent negative asserts the current erroneous acceptance; it is a rejection proof, not acceptance.

The fixture uses actual disposable State/Jobs/Inbox, normal request admission, the typed AcquireTM adapter with fake page responses, real settlement with existing crash cuts, and `OutcomeDelivery` plus `Store.ingest_scrape_outcome_delivery_v1`. Sockets and child-process launches are denied by a Python audit hook. Only the browser/provider page and workbook fixture are substituted. No inference or scheduler starts.

Default-empty environment returns no enrollment. Event, retry-approval and release-activation keys mixed with operator enrollment reject even when the extra value is empty. Initial source retains the event enrollment and calls its original implementation when no operator variable exists. Operator enrollment has no retry approval or release activation. Candidate compilation still delegates to existing `save_candidate` through the inherited owner reread. These source observations do not overcome the two blockers or establish deployment acceptance.

Evidence pins:

- `test_independent_bridge.py`: `bca9901ba98209f52bd50f63a049cd954f04932ec77232e3b979ae820a8fbda6`
- `run.py`: `3554ab95c77a5b3e272ba320a65369907b6f1b98a130dc3899979cecdbee532a`
- `RESULT.json`: `42e58cc31cb61cf4853fbda7e00a24fb7c99b04a5fdaa1fd322d1af72c70b69a`

No claim is made that duplicate/restart promotion or full host scheduling passes: the exact legitimate input currently fails earlier, and the terminal proof requires repair first.
