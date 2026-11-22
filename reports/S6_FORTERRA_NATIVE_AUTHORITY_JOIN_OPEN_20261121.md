# Forterra Sprint 6 finish-join review

## Result: no safe source-only join available

The positive typed-outcome composition is already implemented below the command
layer. `ordinary_verification_finisher.finish_published_ordinary` accepts the
two required trusted capabilities:

- `qualified_owner`, an `_LiveVerdictOwner` opened from a descriptor-proven,
  independently configured verdict root; and
- `capture`, the exact persistent `CaptureCustody` for the dispatch.

When both are present, its existing `_prepare_live_repair` rechecks the
published marker, exact captured response, verdict, State seal, runtime fact,
Jobs write and terminal checkpoint. The staged Forterra composition has already
proved default `VERIFICATION_PENDING`, one qualified result, and idempotent
`ALREADY_STORED` without modifying that accepted source.

The named command does not join those capabilities: runner
`_run_owned_ordinary_verification_finish` calls the finisher with no optional
arguments. This is intentional default-pending behavior, not a missing local
import.

`ordinary_live_issuance_enrollment.snapshot_live_issuance_binding` only reads
and binds a separately approved issuance; it neither issues a live verdict nor
opens/re-enrolls persistent raw-capture custody. The reader
`open_live_mapping_verdict_owner` requires a trusted descriptor, owner identity,
approved verdict SHA, and reviewed-tools SHA. No staged runner/host-owned
configuration source supplies those values or a capture-custody descriptor to
the named finish command.

## Smallest remaining safe seam

Add a host/application-owned continuation that, while it owns the existing
ordinary scraper/writer admission, obtains the configured private verdict-root
descriptor and exact enrolled capture custody from trusted configuration. It
must open `open_live_mapping_verdict_owner` with the configured owner identity,
approved SHA, and tools SHA, then call the existing finisher with that owner and
capture. It must not expose any caller-selected path, SHA, directory FD,
verdict bytes, or capture root via the generic runner CLI.

This continuation also needs the independently approved issuer lifecycle that
creates the verdict. The existing issuance enrollment is only a readback and
the saved issuer dependency plan confirms there is no maintained producer for
the five approved verdict evidence assertions. Implementing a bridge without
those two trusted host capabilities would invent authority.

No source, production state, provider, Sheets, native service, or release was
changed by this review.
