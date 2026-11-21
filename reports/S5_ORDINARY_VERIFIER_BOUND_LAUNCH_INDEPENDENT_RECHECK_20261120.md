# Sprint 5 owner-bound offline verifier launch independent recheck

**ACCEPT for the pinned disposable supervisor and worker launch boundary.** Both initial findings are closed. The assigned job now uses an owner-required schema inside its exact byte pin, and the supervisor rechecks owner authority under the private mutex after reading the pinned inputs and prior records. The check happens before first reservation or receipt reuse. The worker repeats the same assigned-root, slot, and owner-manifest checks before creating its budget. [Initial HOLD](/tmp/jsh-s5-ordinary-verifier-bound-launch-independent.md) · [Owner schema at stage](/tmp/jsh-s5-bound-verifier-qa-final-pin.yVFvzyA1/src/job_search_helper/ordinary_verifier_handoff.py:181) · [Pre-mutex owner check](/tmp/jsh-s5-bound-verifier-qa-final-pin.yVFvzyA1/dev/ordinary_rippling_verifier.py:384) · [Under-mutex recheck](/tmp/jsh-s5-bound-verifier-qa-final-pin.yVFvzyA1/dev/ordinary_rippling_verifier.py:436) · [Worker recheck](/tmp/jsh-s5-bound-verifier-qa-final-pin.yVFvzyA1/dev/ordinary_rippling_verifier.py:285)

- An identical directory copy at the assigned pathname, an absent sibling owner record, and omitted assigned-job token each refused before any supervisor lock, reservation or receipt was created. The omitted-token cases also refused with the in-slot manifest removed and when the exact assigned input files were copied to an otherwise empty standalone directory.
- A cut that removed the sibling owner record during the last input read refused before the first budget reservation or child stub. Direct worker admission with the matching private pipe but a missing sibling refused with zero requests.
- A separate fixture with the genuine legacy, unbound job schema remained available. It returned `NEW` and then `REUSED`, with exactly one synthetic child invocation. The receipt flow remains offline-only. [Independent fixtures](/tmp/jsh-s5-bound-verifier-qa-probes.Dva6Cruq/test_independent_bound_launch_recheck.py) · [Existing handoff boundary](/tmp/jsh-s5-ordinary-verifier-handoff-independent-recheck.md)

**18 cases passed** on `/tmp/jsh-s5-bound-verifier-qa-final-pin.yVFvzyA1`, comprising ten maintained handoff fixtures and eight independent invocation checks. The runs used Python 3.11.18 and SQLite 3.37.2 via the user's 3.11 interpreter, `PYTHONPATH=src:tests`, disposable SQLite and a synthetic offline child. No real provider, workbook, live application, or verifier child subprocess ran in this lane. The coordinator’s saved-corpus subprocess composition is a separate verification. This acceptance does not authorize production deployment or application writes from a verifier receipt.

| Frozen file | SHA-256 |
| --- | --- |
| `dev/ordinary_rippling_verifier.py` | `f218ed98eb0991e72c78b7ddaaf67dcde41f48b6a3d472e171cc5e26b2de1164` |
| `ordinary_verifier_handoff.py` | `fa68986f80e3cb5201cd94847f616089a0beedae91287aac5017df201ee4bb91` |
| `test_s5_ordinary_verifier_handoff.py` | `9fcbe7838537deb20b3426fd3843df3973e1e269eb240bbcaf5081296c976246` |
| `qa_s5_ordinary_verifier_subprocess.py` | `ce7113576822da2da4082ef09f650fadbcd42c45bca2c72bac78a71f691df424` |
| `test_independent_bound_launch_recheck.py` | `f3cb64b0d3b0b5fdbb7f213ed6ea9d710bfb6e9403cae33385057083e78be8a7` |
