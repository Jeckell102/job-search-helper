# Final Amphenol one-shot existing-store and canary recheck

**ACCEPT** the corrected staged source and both exact disposable canaries.

| Evidence | SHA-256 |
| --- | --- |
| Final one-shot | `8af5c70848baec3b8da53df209ff260aaeff3940b4d48c4c3a4552440e5432c6` |
| Coordinator | `db41607834c42a90f742d048c3df5a9e68ac8c9f75deb1414cc4d554c0d9caec` |
| Coordinator Store | `4b09a063fd657be2f4febaddaa23f2d283987e18604f6a8d20d97b0910d423b2` |
| Independent 11-case test output | `9563844f1ab94a8576ea90f91858b495ab67195a2d5c45e15c5e44340d3e35f2` |
| First-activation canary | `ae1dbb4c8e9d27363aece045d45d84779e09ce215a36a1140fc08b7cfd1c8058` |
| Interrupted-recovery canary | `4ab34f7c38a16f43467191bba835d80bb84cb94982c44b17d5c673b4c6f42ec8` |
| Independent immutable canary readback | `832ee3bdbfd717dc78c7ce45150bcfa7f74ed42e3577b3244af24657f7159959` |

All 11 independent cases passed. The original held-controls case preserves the exact current-mode DELETE database bytes. Direct existing attachment preserves a legacy schema without adding columns or changing journal mode. Missing files before or after attachment remain absent. The ordinary default Coordinator still creates the expected schema and WAL database. With existing-only attachment, an actual Coordinator receipt-v1 completion and replay change only the expected intake, receipt and retry lineage ledgers, preserve unrelated task/inference/settings records, and leave schema and DELETE mode intact. Pure default-off, wrong approval, both lock contention paths, and ownership of both actual flocks through terminal delivery remain verified.

The intermediate source `bdbe97c4…` returned idle for a syntactically valid task record missing status. The exact source and red output `98dd1aee…` are preserved here. The final source now holds incomplete status. The earlier bootstrapping rejection remains preserved at `/tmp/jsh-amphenol-one-shot-independent.0sWDXWuj/INITIAL_QA.md` SHA `43c95410908ee5558bf4719b52dcbf0c45e36db2c30a434f417fa53da2a99616`.

Both current canaries contain byte-identical copies of the three reviewed files. The first-activation driver attests no prior journal or queued request, runs the retained operator selection and real installed verifier, and verifies identical historical synthetic task and inference receipt after completion and replay. Independent immutable readback confirmed the persisted `PAUSED_ERROR` task and its sole `COMPLETED` W1 inference, and the actual installed verification receipt digest `794ae79c72a2d886f7c783e063dcce219c3a29b8c7d7c31bd1eed63cf55ae3c1`. The resumed fixture owns no tasks or inference. Each independently has two matching sender/receiver receipt pairs, one `VALIDATED_COMPLETE` event, one `SYNC_CONFIRMED` publication and one fixture job and batch. Their drivers verify stable replay.

The outer maintenance exclusion was supplied by fixture callbacks. Actual native authority and host-exclusion packaging remain separate. This lane used staged copies and disposable stores only, with no native operations or network.
