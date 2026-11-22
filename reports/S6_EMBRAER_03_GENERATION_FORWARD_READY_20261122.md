# Embraer next guarded wrapper forward

The proposed wrapper-only retry now accounts for the observed normal
shutdown behavior. An orderly successful restart must advance control
generation exactly once. A compensated two-restart attempt must advance
it exactly twice. The protected logical DB rows, scheduling controls,
held parent, original receipts, app release and paired outcome must
otherwise remain unchanged. The supervisor heartbeat is checked for
healthy active state separately. The empty continuation table is
expected from the earlier compensated attempt and must remain empty.

Five focused disposable cases passed using the real Store shutdown
control update, including exact +1 and +2 transitions and refusal of
an extra advance or protected control change. Independent QA reviewed
the generation-aware native composition and the exact sealed -16 intent
and receipt bindings. Fresh MuleLab read-only validation accepted the
restored lineage and reached the required fresh administrator observer.
No source update, restart, model action or live acceptance credit changes
occurred during this verification.

| Source | SHA-256 |
| --- | --- |
| Forward adapter | `fcb67f16c7ef33876b6450c1fed6cc55e6fa94496f7c040220f3972c54806c91` |
| Logical custody measurement | `dd5aa6ce904e867edb62255f4401e3848578038abab365be46408cb4d57a51e5` |
| Native inspection | `4e34e6eb82e67bfa1ee6c7a30e81bd62764bf81aa19bc5d81dccb08d327597df` |
| Native source-only apply | `01dbeae60c2ed06d724176251c5cb24f0ff93188397630aeb83c85667576aa40` |
| Native observer starter | `7e3735fd96f997744f03e988184cd1dd8722b161c198b020ac6fbbfef9acf621` |
| Separate exact-child approval reader | `350f5631597003a0623d7edbcb3599f323a60d4acaeafce30dcb2adc817388ca` |

The staged next window is under `/tmp/jsh-embraer-03-generation-forward/`.
Use its fresh -17 observer and do not replay the sealed -16 transaction.
Only the wrapper source packet may be installed in that window. The
owner still approves the exact one-call child separately after a verified
successful source forward.
