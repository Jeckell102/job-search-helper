# Corrected estimate preservation QA

**ACCEPT for the corrected disposable sequence.** The earlier HOLD applies to the original fixture with unsupported fields and remains preserved in `INDEPENDENT_QA.md`.

| Corrected artifact | SHA-256 |
| --- | --- |
| `prove_sequence.py` | `24a604dc396291d4403595438b772c4d6193de7f0399a426baa2a4a66b838fc7` |
| `RESULT.json` | `b919145e9081476bba0340f6c7bbdb8802eacfa9f040203ba23302b535ce149f` |
| `fixture-workbook.private.json` | `65d13fda039bb5aa3b3f58c684a68955dc368d881bb934114cb6ca926a1ad8c7` |

The corrected driver populates seven canonical fields in the unrelated manual Job History row and verifies the literal nonempty `Salary / Range` in both stores before the first event. It compares the entire protected row against that seed after the first event and against that checkpoint after the second. The sequence, receipt, and terminal replay assertions are preserved. [Seed assertions](/tmp/jsh-s6-sequential-composed-estimate.20261121/prove_sequence.py:41), [protected row comparisons](/tmp/jsh-s6-sequential-composed-estimate.20261121/prove_sequence.py:131)

Independent direct readback from a private copy of the corrected runtime and the exact raw workbook fixture confirmed all seven manual row fields, including the literal estimate. The workbook retains one exact publication batch and the corrected result retains 18 matching jobs with one publication receipt. Native publication and deployment were outside this fixture verification.
