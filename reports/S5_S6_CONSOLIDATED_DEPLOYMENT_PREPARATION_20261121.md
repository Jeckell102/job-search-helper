# Consolidated release preparation

November 21, 2026. The current staging source contains 38 changes against
MuleLab's installed checkout, with 28 replacements and 10 additions. The
original 31 before-images still match. Six candidate files have newer
independent QA pins, and seven current target paths were absent from that
review's inventory. All 13 match their later exact source QA. The stable
bootstrap and package manifest match native. The launcher matches the
previously approved staged version.
[Exact inventory](S5_S6_CONSOLIDATED_SOURCE_SCOPE_20261121.json)
· [Independent endpoint audit](S5_S6_CONSOLIDATED_SCOPE_INDEPENDENT_20261121.md).

The disposable overlay rebuilt all scoped runtime files from native
before-images and those 38 after-images. It reproduced the complete
staged application and direct wrapper tools under SHA-256
`28015a3d3b9be15dc1c91bdc4dce378c8daf10638bb294f20e9f50af0b8f6a2c`.
The installed wrapper vendor subtree remains outside the overlay. The
first expanded test fixture omitted the retained bootstrap and stopped
at test collection. Adding the existing, independently measured bootstrap
and package manifest to the fixture allowed all 71 release, host and
intake tests to pass from that reconstructed tree. Their listed runtime
files and existing root files stayed byte-identical. No native files
were installed or changed.

The exact accepted Freeform parser accepted its original 47-path control
manifest and rejected the new 38-path package. Nine required wrapper
paths sit outside its allowlist. It also requires the existing receipt
bridge in the mutation list while refusing unchanged before/after bytes.
The existing bridge matches its accepted installed source and stays
protected as an unmodified sibling.
[Independent parser refusal](S5_S6_OLD_INSTALLER_SCOPE_HOLD_20261121.md).

Root staged a distinct manifest policy that admits exactly the 38 reviewed
paths and requires the existing wrapper host and store. Previously
accepted manifests retain their original path rules. The controller
derives which wrapper files it can exclude from its protection witness
from the actual validated mutation list. The original receipt bridge is
outside that list. The staged parser and controller witness rejected a
missing path, added bridge path, unchanged replacement, wrong manifest
digest and a changed bridge. Roots and physical installer ownership still
use the original controller mechanisms.
[Independent policy design](S5_S6_MAINTENANCE_SOURCE_POLICY_REVIEW_20261121.md).

Independent QA accepted the parser and actual guarded installer on private
disposable paths. All 38 exact staged after-images passed readback, and
all ten absences were restored when rolling back without the candidate
available. The unchanged receipt bridge kept its inode, mode and bytes.
Rollback used synthetic before-images. Native controller, host witness
and service acceptance remain open.
[Independent policy QA](S5_S6_MAINTENANCE_SOURCE_POLICY_INDEPENDENT_QA_20261121.md).

The latest read-only service observation found the wrapper host and
assistant bridge running with their expected entrypoints. Scheduled sync
was disabled and inactive. This observation grants no maintenance hold.
[Service readback](S5_NATIVE_USER_SERVICES_READBACK_20261121.json).

Native approval still needs a fresh maintenance capsule and protected-site
proof. The unfinished-cycle release guard and missing eligible pilot
remain separate. The requested user choice concerns which live pilot
direction to prepare. It provides no data-write authorization.
