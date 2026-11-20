# Independent recheck of exact terminal journal evidence

2026-11-20 16:46 EST

**ACCEPT for staged source.** The required exact-journal follow-up is satisfied.

The terminal context calls `load(canonical=True)` while retaining the existing leases. The loader parses the bytes from one journal read and checks that the encoding of the parsed object exactly equals those bytes before returning the object. As the subsequent verification uses the record without changing it, the evidence digest is the digest of the verified file bytes. The ordinary controller entry point retains the default load mode. `controller.py:532-560`, `controller.py:989-1007`, `controller.py:1018-1028`.

The revised disposable test still compares the evidence digest to the original file bytes. It then appends JSON whitespace, asserts rejection before evidence is yielded, and restores the fixture bytes. I reviewed the revised assertions. The coordinator owns the fixture rerun and I performed no additional test execution or live action. `test_combined_release.py:611-652`.
