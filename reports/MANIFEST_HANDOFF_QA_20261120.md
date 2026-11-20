# Independent QA — private manifest handoff — 2026-11-20

## Verdict

**ACCEPT for the hardened source boundary.** This is not acceptance of a
signed activation or a live Samtec run.

## Evidence

- Independent QA ran 91 retained/operator/handoff checks and 74
  normal-isolation checks successfully.
- Signer input is private: a mode-0700 directory, mode-0600
  content-addressed artifact, exact-content idempotence, no overwrite, and
  rejection of symlinked directories or artifacts.
- Wrong-key and expired-approval rejection assertions are executable.
- Valid activation proves call order: `verify -> lock -> revalidate -> verify`.
  Malformed approval fails before lock/store mutation.
- Source inspection found no Google, remote, normal-start, or global-sync
  construction in the activation boundary.

## Still required before live work

Generate a fresh private manifest/claims artifact, obtain a configured trusted
Ed25519 public key and matching unexpired external envelope, then recheck the
Samtec request, retained historical evidence, locks, and source/provider
disjointness. Only then may the single bounded private preflight run.
