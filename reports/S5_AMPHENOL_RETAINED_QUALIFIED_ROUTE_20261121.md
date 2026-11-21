# Recovered Amphenol candidate: release-route check

Scope: source-only review of the staged release contracts.  No production
state, queue, service, inference, or network access was used.

## Result

There is **no supported manual owner-approved release/retry route for the
operator-owned Amphenol recipe as it stands**.  The existing release route is
intentionally bound to the older company-event enrollment and cannot be
truthfully reused for the recovered operator candidate without changing its
authorization and completion contracts.

## Existing route and its exact entry conditions

The only release entry is the `AmphenolRetryEnrollment` branch in
`dev/wrapper-coder/tools/host_server.py` (`catch_up`), reached only when the
process has both:

1. `WRAPPER_AMPHENOL_RECIPE_ENROLLMENT` containing a company-event identity
   (`CEV-...`, `request_id=company-event:CEV-...`), and
2. `WRAPPER_AMPHENOL_RETRY_APPROVAL`, a `RetryReleaseApproval` pin to an
   owner directory, release ID, filesystem identity, and qualification-receipt
   SHA; release activation additionally requires
   `WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE=1`.

The owner directory must contain both the exact release manifest and a
qualification receipt accepted by `release_qualification._QualificationOwner`:
`result=PASS`, `evidence_class=live_normal_dispatch`,
`release_qualification=true`, and digests matching the complete manifest and
candidate validation receipt.  The route also rechecks source/configuration
tree digests, current Company revision, idle application state, installed
verification, and then schedules the deterministic retry; it does not spend
inference.

`amphenol_candidate_release.read_owned_candidate_release` imposes a further
hard link to the completed coordinator record: exactly one held intake,
`PROMOTED_PAUSED`, task status `REVIEW_COMPLETE_LIVE_NOT_VALIDATED`, inspect
phase, matching completed inference receipt and generated candidate bytes.

## Why the recovered operator candidate cannot enter it

* `OperatorAmphenolRecipeEnrollment.from_process_environment` explicitly
  rejects retry approval and release activation controls.  Its request has no
  company-event identity, while the existing release reader validates the
  event-owned enrollment and event-style `failed_request_id` binding.
* The report of an old `PAUSED_ERROR` task does not meet the release reader's
  required `REVIEW_COMPLETE_LIVE_NOT_VALIDATED` status.  Resetting or editing
  it would not be a supported continuation and would weaken the durable
  completion proof.
* A recovered candidate and completed choice do not themselves constitute the
  independent owner-pinned qualification receipt required for installation.

## Smallest truthful next action

Keep the recovered candidate isolated.  Before any release/retry, obtain a
fresh, independently owner-pinned qualification package for a manifest whose
`failed_request_id`, Company revision, source/configuration digests, candidate
bytes, and installed verification all match the operator request.  Current
code has no operator authorization reader to consume that package, so a new
explicit operator release-continuation feature would be required; it must not
pretend the old event enrollment or `PAUSED_ERROR` task satisfies the existing
route.  No inference is needed by the established event route once such a
valid package and authorized entry exist.

## Addendum: low-level qualified-release contract

The low-level `qualified_release_owner.release_and_continue_qualified` path
does **not** intrinsically require a company-event ID, a wrapper-task ID, or
the `REVIEW_COMPLETE_LIVE_NOT_VALIDATED` task status.  Those are host-level
requirements in the existing `AmphenolRetryEnrollment` dispatch and
`amphenol_candidate_release.read_owned_candidate_release` reader, not
requirements of the installer/scheduler itself.

At the low level, a separately reviewed caller could use an operator request
as `manifest.failed_request_id`, provided it supplies all of the following:

* an exact canonical release manifest with the actual Company ID and current
  source revision, candidate file metadata, complete source/configuration and
  dependency digests, and validation-receipt digest;
* a pinned, independently controlled qualification-owner directory and open
  descriptor whose exact receipt is `PASS`, `live_normal_dispatch`, and
  matches that manifest and validation digest;
* a candidate tree that exactly matches the manifest, a verifier that returns
  the exact pinned PASS evidence after installation, and an idle admitted
  runtime; and
* a currently matching Company revision and normal retry completion evidence.

`release_controller` and `repair_retry` only require a bounded nonempty
`failed_request_id`; they derive a fresh `company-retry:RTRY-...` request and
do not parse it as a company-event ID.  They likewise do not read the old
wrapper task.  Therefore the preserved error record/recovered build receipt
may be useful independent evidence for a new operator-owned review, but they
are not sufficient release authority by themselves.  No PASS qualification or
release is implied by this conclusion.
