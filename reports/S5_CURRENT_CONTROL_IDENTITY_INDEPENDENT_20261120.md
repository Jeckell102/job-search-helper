# Sprint 5 current PDW control identity independent QA

**ACCEPT for the pinned offline validation tool.** The PDW control still requires the regression role, Company ID `COMP-0178`, its reviewed authority and board, and an exact row hash and source revision. The only added display label is `Performance Drone Works (PDW)`. The original exact `PDW` label stays accepted under its own matching pin. A label-only change leaves the source revision stable but changes the Company row hash, so the old row pin cannot certify the full name. [Reviewed scope](/tmp/jsh-s5-control-identity-independent-pin.jOtih2US/dev/pre_release_validation/validate_candidate.py:33) · [Pin validation](/tmp/jsh-s5-control-identity-independent-pin.jOtih2US/dev/pre_release_validation/validate_candidate.py:82) · [Raw row binding](/tmp/jsh-s5-control-identity-independent-pin.jOtih2US/dev/pre_release_validation/validate_candidate.py:204)

The exact pinned full label passed the synthetic check and the saved public employer and provider replay. The old pin and a name-only repin refused. A wrong source revision also refused. Matched but substituted Company name, Company ID, role, and board each refused before PDW board replay. The public-authority check independently refused a replacement employer URL even after updating both the saved Company and scope pin consistently. Candidate source/configuration/dependency measurements were equal before and after the passing replay. [Independent fixtures](/tmp/jsh-s5-control-identity-independent-probes.lLbSp5s8/test_control_identity_independent.py) · [Maintained public replay](/tmp/jsh-s5-control-identity-independent-pin.jOtih2US/tests/test_live_employer_authority.py:217) · [Public authority allowlist](/tmp/jsh-s5-control-identity-independent-pin.jOtih2US/dev/pre_release_validation/rippling_public_authority.py:159)

**86 maintained and 9 independent cases passed** under Python 3.11.18. The saved public corpus manifest matched its reviewed SHA-256 `4b724ffead928ea1678e594eddfb4d934ee4139279e661e783ed7aa3397e55ce`. The original candidate source was untouched, and the tests did not access a production store, workbook or live network. The stated current MuleLab label is coordinator input to this offline source review. Public replay remains `PUBLIC_EVIDENCE_ACCEPTED` with `release_qualification=False`.

| Frozen file or vector | SHA-256 |
| --- | --- |
| `validate_candidate.py` | `e1e5cfb34c01694f9722169343d9fe19417c16623758de79cb74c17685aca25e` |
| `rippling_public_authority.py` | `5297cf4832bb287c91fac89f498729ec6c2d1c1dff9dc23008a6949568ac3e57` |
| `rippling_capture.py` | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| New combined reviewed-tools vector | `86723e7fdc0e4e8acdae2dbdc9516c93f0e4557c60ef3b75d17f20869bd3eac0` |
| `test_pre_release_candidate_validation.py` | `c4e2506d97ba44b94d03bbb43b29f6dacf964e64e7e978379c450d5babc4b320` |
| `test_live_employer_authority.py` | `f16cf63b25d83bccedabac55fb00743c3fca1f5d641240ad5f868bb8d9d1670f` |
| `test_control_identity_independent.py` | `777315b3695e237ae0074e014a72e28912051766b11e6a443e083243e650b51c` |

The newer tool vector has its own acceptance. Any verifier still carrying the previous reviewed-tools vector needs separately staged integration and replay with the exact new source and pins. [Previous bound verifier acceptance](/tmp/jsh-s5-ordinary-verifier-bound-launch-independent-recheck.md)
