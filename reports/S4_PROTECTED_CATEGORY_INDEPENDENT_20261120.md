# Independent protected checkpoint diagnostics review

**ACCEPT for the staged source.** The entrypoint changes only the text a caller receives when a protected checkpoint raises `WitnessHold`.

| Reviewed file | SHA-256 |
| --- | --- |
| [Entrypoint](/tmp/jsh-s4-listener-observer.Zwv760tc/host_check_main.py) | `36407235f3d12df8db3070e6278c1090b8395c6a2b88b00953f3ea3faab1c8e7` |
| [Maintained entrypoint tests](/tmp/jsh-s4-listener-observer.Zwv760tc/test_host_check_main.py) | `77ed155641cb5bc8789bda721010e5404085ca6e892fc7487bcd0c67fa9e836e` |
| [Maintained protected state tests](/tmp/jsh-s4-listener-observer.Zwv760tc/test_protected_state.py) | `042074ae118ae3d19786065d5c30e759e3e70657756ea1660335c3a304c6e564` |
| [Independent entrypoint tests](/tmp/jsh-s4-protected-category-independent.Q2ml3ZsZ/test_entrypoint.py) | `bffd3117bb29198c00799deecdb909a75162a160ddabc113a68620a678fbe983` |

- The formatter takes exactly one plain string argument and uses it solely for an exact lookup into fixed category values. Other arguments use the fixed `UNCLASSIFIED` category. The formatter never renders the exception or its arguments. Non-witness exceptions keep their existing generic error. [Formatter and exception handlers](/tmp/jsh-s4-listener-observer.Zwv760tc/host_check_main.py:15)
- The imports, `main()` body, and generic exception handler match the baseline. Passing still requires a completed attestation and successful continuity finalization before the exact response reaches standard output. A protected failure still sends the fixed message through `SystemExit`, producing a failure status with no response. The controller continues to require zero exit status and an exact receipt with `verified` set to true. [Receipt emission](/tmp/jsh-s4-listener-observer.Zwv760tc/host_check_main.py:56) · [Controller checkpoint contract](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-listener/controller.py:505)
- The protected state module is unchanged. The added disposable SQLite test shows that a separate `mode=ro` connection can leave WAL/SHM files during the observation and that the existing database continuity guard holds the checkpoint. This fixture establishes the behavior without identifying the cause of any production failure. [Protected state guard](/tmp/jsh-s4-listener-observer.Zwv760tc/protected_state.py:95) · [Disposable SQLite test](/tmp/jsh-s4-listener-observer.Zwv760tc/test_protected_state.py:190)
- All 26 focused maintained tests passed. All nine independent tests passed against the actual entrypoint with disposable stubs. They verified exact output for approved categories, generic failures, private and non-string arguments, a failure during finalization, and the successful receipt. [Independent entrypoint tests](/tmp/jsh-s4-protected-category-independent.Q2ml3ZsZ/test_entrypoint.py)

The independent review did not execute the checker against production or change any staged source.
