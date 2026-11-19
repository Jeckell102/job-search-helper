# Legacy migration approval provenance design — 2026-11-19

## Decision

Replace binding-only local JSON approval with a canonical signed envelope and
detached OpenPGP signature. This is a required gate before any future
Davidson/local adoption retry.

## Required mechanism

1. The approval envelope must be canonical UTF-8 JSON (sorted keys, compact
   separators, final newline) with no duplicate or extra keys. It carries an
   approval UUID, limited-purpose `legacy-local-adoption-only`, short expiry,
   signer fingerprint, exact cycle/company, full current binding, plan and
   remote-projection digests, operation counts, and protected-conflict count.
2. `/usr/bin/gpgv` verifies a detached signature using only
   `/etc/job-search-helper/legacy-migration-approvers.gpg`; status output must
   identify the same authorized fingerprint declared in the envelope.
3. Verification happens before writer work and the exact full authorization is
   revalidated against a newly computed preview under the writer lock before
   any first write.
4. The migration journal retains immutable approval ID, signer fingerprint,
   canonical-envelope SHA-256, and signature SHA-256. Recovery/retry must use
   the exact original authorization; legacy no-provenance rows cannot acquire
   a new mutation authorization.

## Planned owned surfaces

- New `legacy_migration_approval.py`: strict parse/canonicalize, detached
  verifier, fingerprint/scope/expiry checks, immutable audit projection.
- `runner.py`: require signature alongside approval file and verify before
  writer work.
- `exact_legacy_migration_runner.py` and migration journal: recheck all signed
  pins under lock and persist immutable authorization evidence.
- Focused approval, runner, and restart/no-mutation test coverage plus an
  operator document.

## Deployment prerequisite and limit

An owner-reviewed signing key must remain off MuleLab. Only its public key may
be installed in root-owned `/etc/job-search-helper/legacy-migration-approvers.gpg`
(root:root, directory 0755, file 0644), with the authorized fingerprint pinned
in protected runtime configuration. Do not create a private key in the repo,
MuleLab, a backup, or test evidence.

Current project source and state are writable by the local user. Therefore the
mechanism enforces the supported CLI against self-authored JSON but is not a
hostile-local-admin security boundary until adoption runs from a protected
runtime artifact and protected state/service boundary. No adoption is allowed
until that operational prerequisite is satisfied and independently verified.
