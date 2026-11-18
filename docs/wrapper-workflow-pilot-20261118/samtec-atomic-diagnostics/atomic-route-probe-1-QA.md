# Atomic route proposal independent QA

Result: **FAIL_BOUNDED_PROPOSAL**. Seven of12 offline routing cases passed;5 failed. No proposal was applied.

The response supplied exactly one code_edit with the current SHA256 and a unique original substring. The proposed complete file compiles. However:

- It tests `host == 'samtec'`; the actual host is `jobs.jobvite.com`. Consequently both Samtec jobs/search URLs still normalize to `/samtec/jobs`.
- Valid Samtec and other-employer detail URLs now raise ValueError instead of retaining posting IDs.
- An empty board path raises IndexError because parts[0] is accessed before the original emptiness guard.

Tests executed only an isolated in-memory routing subset after inspecting the proposal. Source hashes before/after are identical. Exact cases and response hash are in the adjacent JSON. This failed proposal is not an integration result.
