# Sprint 5 offline verifier job handoff independent QA

**HOLD on the initial pin.** A dispatch whose verifier slot has already spent or reserved an allowance can receive a new allowance when its directory disappears from the still-identical pinned owner root. The in-place budget check and receipt settling worked in the other cases. This review exercised disposable application and channel fixtures. Real offline subprocess composition remains a separate check. [QA plan](/tmp/jsh-s5-verifier-handoff-qa-plan.md)

## Blocking repeat case

The independent fixture staged a 32-request job and read its exact durable fixture `TIMEOUT` receipt. It renamed only that dispatch slot within the same owner root. The root descriptor, app databases, archived capture and original verifier evidence were unchanged. A second `stage()` call with a limit of 64 and a different duration returned runnable pins for a new directory at the original name. The sole previous slot identity, deadline and budget lived in the now-missing slot. The new directory started without the previous supervisor reservation, so the handoff cannot prove that the original one-attempt allowance remains exhausted. No child or provider was run to reproduce this result. [First-stage decision](/tmp/jsh-s5-ordinary-verifier-handoff-qa-pin.lqGkIHMe/src/job_search_helper/ordinary_verifier_handoff.py:201) · [Independent case](/tmp/jsh-s5-ordinary-verifier-handoff-qa-probes.BtXOPfAO/test_independent_offline_handoff.py:13)

The smallest repair is a separately named, durable owner record keyed to the dispatch and storing the exact slot identity plus job pins before any launch ticket returns. Both `stage()` and `read_result()` must refuse missing or replaced slots when that record exists. A slot published before an interrupted owner-record commit may recover only as the same verified, unstarted slot. Prove one durable owner record after that cut, no new deadline or budget after loss of the pinned slot, and refusal of a receipt without the owner record. This can stay in the private owner directory and leave application databases untouched.

## Verified fixture results

- The positive maintained fixture walked real typed capture and exact publication on disposable State/Jobs/Inbox before staging. The handoff revalidated the owned publication and retained configured response, derived exact private input hashes, rejected a changed budget on in-place replay and returned a synthetic matching receipt with `application_authority=False`. The logical State, Jobs and Inbox images were identical across staging/readback. [Binding](/tmp/jsh-s5-ordinary-verifier-handoff-qa-pin.lqGkIHMe/src/job_search_helper/ordinary_verifier_handoff.py:92) · [Maintained fixture](/tmp/jsh-s5-ordinary-verifier-handoff-qa-pin.lqGkIHMe/tests/test_s5_ordinary_verifier_handoff.py:169)
- The maintained settling fixture held the supervisor’s private lock while a complete-looking receipt was already visible. The handoff returned pending without waiting. After release, the matching receipt read back. Mode, identity, candidate and replay-corpus drift refused even with a rebuilt checksum. Replacing the physical owner root refused. [Settling guard](/tmp/jsh-s5-ordinary-verifier-handoff-qa-pin.lqGkIHMe/src/job_search_helper/ordinary_verifier_handoff.py:58) · [Receipt fixture](/tmp/jsh-s5-ordinary-verifier-handoff-qa-pin.lqGkIHMe/tests/test_s5_ordinary_verifier_handoff.py:238)
- Three additional independent cases passed. A missing receipt with the existing owner slot and verifier reservation preserved exact job bytes and budget. A visible receipt without its reservation refused. An altered receipt checksum refused. The pinned accepted verifier source and its reviewed tool-vector digest matched this handoff’s constants. As documented by the accepted verifier contract, a privately supplied fixture receipt and checksum provide no qualified deployment authority or protection against a same-user writer trusted with the entire owner directory. [Result readback](/tmp/jsh-s5-ordinary-verifier-handoff-qa-pin.lqGkIHMe/src/job_search_helper/ordinary_verifier_handoff.py:253) · [Accepted offline contract](/tmp/jsh-s5-ordinary-verifier.povmDDEm/checkpoints/PENDING_CONTRACT.md:13)

## Pins and runs

Frozen snapshot `/tmp/jsh-s5-ordinary-verifier-handoff-qa-pin.lqGkIHMe`. **8 maintained cases passed; 3 independent cases passed and 1 failed** as described above. Python 3.11.18 and SQLite 3.37.2 with fresh `/tmp` directories and `PYTHONPATH=src:tests`. The fixture intercepted provider calls and used an in-memory workbook. No live provider, real workbook, production store, Jetson operation or verifier subprocess was used.

| Source or fixture | SHA-256 |
| --- | --- |
| `ordinary_verifier_handoff.py` | `fd881c32c4111a46f1a78cee2436c56ca988eaeba6e2ab9e7d18bca87e941002` |
| `test_s5_ordinary_verifier_handoff.py` | `7ec5b397ae9d633a0db84474645cb70ea8e34d725941f44bdc239e867b095471` |
| `test_independent_offline_handoff.py` | `919a9e8985e55f6775f3a074a1785b26e10588d3500c53d52e2ed35019fdc951` |
| Accepted offline verifier | `2925328cfae39a390cbac072a0834d10a580b0174555c1ef00fa9e418f7564c6` |
| Verifier’s reviewed-tool vector | `1715233f4e8988c08d69cf9c00674d29add135efe22b5e232eb3fff2f842b866` |
