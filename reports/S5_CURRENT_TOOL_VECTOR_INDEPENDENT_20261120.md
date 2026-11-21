# Sprint 5 current-control tool vector independent QA

**ACCEPT for the pinned offline owner-bound composition.** The subprocess replay accepted both exact reviewed PDW display labels under their own row pins and refused stale reviewed code before any metered read. The old and new verifier/source vectors remain separate. Offline receipts still carry no application authority. [QA plan](/tmp/jsh-s5-current-tool-vector-qa-plan.md) · [Current-control acceptance](/tmp/jsh-s5-current-control-identity-independent.md) · [Previous launch acceptance](/tmp/jsh-s5-ordinary-verifier-bound-launch-independent-recheck.md)

## Evidence

- Independently recomputed the physical old and new verifier source hashes and both sorted canonical reviewed-tool vectors from disk. In the verifier only the reviewed validator file SHA changed. In the application handoff only the expected verifier source and full tool-vector hashes changed. The reviewed public-authority and capture-parser files retained their previous hashes, and `--candidate` remained the same approved candidate with a distinct reviewed-tools directory. [New tool table](/tmp/jsh-s5-current-tool-vector-qa-expanded-pin.CmQWDYF1/dev/ordinary_rippling_verifier.py:34) · [Exact tool reads](/tmp/jsh-s5-current-tool-vector-qa-expanded-pin.CmQWDYF1/dev/ordinary_rippling_verifier.py:197) · [Owner pins](/tmp/jsh-s5-current-tool-vector-qa-expanded-pin.CmQWDYF1/src/job_search_helper/ordinary_verifier_handoff.py:24)
- The actual saved-corpus subprocess recorded `VERIFIED_MISMATCH` with 114 metered reads for each of `PDW` and `Performance Drone Works (PDW)`, followed by an identical `REUSED` receipt. The source/tool, replay-capture and candidate-vector pins matched. The same positive evidence retained the fixed PDW regression inventory digest. Using the previous tools for a newly pinned job returned `CHANGED_INPUT` / `reviewed_verifier_source_changed`, zero reads and no evidence, followed by the same reused terminal receipt under the original single allowance. Readback retained `application_authority=False` and byte-identical serialized State, Jobs and Inbox. [Real offline subprocess fixtures](/tmp/jsh-s5-current-tool-vector-qa-expanded-pin.CmQWDYF1/tests/qa_s5_ordinary_verifier_subprocess.py:38)
- Independent local probes rejected the old verifier against a new assigned slot and the new verifier against an old assigned slot before mutex, reservation or receipt creation. A completed old exact receipt stayed readable by its old verifier and old owner pins. Current restage/readback refused it without changing its bytes. Independent substitutions of the old validator and a changed capture parser both stopped before any evidence charge. [Independent cases](/tmp/jsh-s5-current-tool-vector-qa-probes.Ijcl2iv3/test_current_tool_vector_independent.py)

The initial frozen test pin passed **13 maintained cases**. The expanded frozen pin `/tmp/jsh-s5-current-tool-vector-qa-expanded-pin.CmQWDYF1` passed **14 maintained and 6 independent cases** using Python 3.11.18, SQLite 3.37.2 and fresh `/tmp` fixtures. The original candidate was unchanged. The tests used saved responses, blocked provider sockets in the application fixture, and used an in-memory workbook. No live provider, production store, real workbook, queue or Jetson was accessed. This verifies the offline repin only. Candidate qualification, live collection, and any application-writing finisher remain separate.

| Frozen source or test | SHA-256 |
| --- | --- |
| `dev/ordinary_rippling_verifier.py` | `ae39cb34ab229eee22b66f34dbe2d1486d2f08f0e1de0acc43970a8d15bbff14` |
| `validate_candidate.py` | `e1e5cfb34c01694f9722169343d9fe19417c16623758de79cb74c17685aca25e` |
| `rippling_public_authority.py` | `5297cf4832bb287c91fac89f498729ec6c2d1c1dff9dc23008a6949568ac3e57` |
| `rippling_capture.py` | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| Current reviewed-tool vector | `86723e7fdc0e4e8acdae2dbdc9516c93f0e4557c60ef3b75d17f20869bd3eac0` |
| Prior reviewed-tool vector | `1715233f4e8988c08d69cf9c00674d29add135efe22b5e232eb3fff2f842b866` |
| `ordinary_verifier_handoff.py` | `7caa48484c2cd8c22e71e7fe576d3e6a1b247c7833a704e3a423b6a747e34bf2` |
| `test_s5_ordinary_verifier_handoff.py` | `34f19051bafae058ad0d0140937cc4a767c018373ba4263a9a28dcfabaa64888` |
| `qa_s5_ordinary_verifier_subprocess.py` | `3f100c1580d568df15d0a03b6eaacbd3577cc74890702156e9a8cbb65f18c103` |
| `test_current_tool_vector_independent.py` | `5f5e61e9bd9e2684cad349b0feeb0127b1d6c85b901f5019a46fe10423a47ece` |
