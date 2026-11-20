# Pre-pause research checkpoint — 2026-11-20

## Decision

**PROCEED AFTER RESUME, WITH A MANIFEST-HANDOFF REPAIR.** The repaired
operator-request/retained-exception route remains aligned with Milestone 1's
containment direction. It is not yet authorized for signed activation or a
live Samtec preflight.

## Fresh independent QA evidence

- Independent QA accepted the repaired source boundary on 2026-11-20.
- 134 retained/operator/normal-isolation checks passed in 15.09 seconds with
  pytest plugin autoload disabled only to avoid an unrelated ROS plugin's
  missing `yaml` dependency.
- The preview test proved no added file or retained-store mutation. It reads
  the cycle with SQLite `mode=ro&immutable=1` and does not construct State,
  Google, Sheets, or other remote handles.
- The public preview CLI was independently checked to emit only
  `manifest_digest` and `required_claims`, not the historical cycle membership
  or full manifest.

## Research finding that remains open

`retained_exception_preview()` creates its manifest with `created_at=now()`.
The compact CLI then prints only the signer claims and manifest digest.
`activate_exception()` requires the exact full manifest, so rebuilding the
manifest later can produce a different digest and invalidate a signature.

Before a live authorization attempt, provide a safe private manifest-handoff
mechanism: preserve the exact generated manifest alongside the compact claims
and bind both to the same digest, or use an equivalent reproducible immutable
manifest reference. Do not print the full historical manifest to a terminal,
and do not relax signature, expiration, source/provider-disjointness, or
normal-lifecycle holds.

## Resume gate

1. Implement and independently test private exact-manifest handoff.
2. Generate a fresh private manifest and compact signable claims together.
3. Obtain a configured public key and time-bounded external Ed25519 envelope
   for those exact claims.
4. Run only the bounded Samtec private preflight, preserving the old cycle,
   no broad scan, and no automatic release.
