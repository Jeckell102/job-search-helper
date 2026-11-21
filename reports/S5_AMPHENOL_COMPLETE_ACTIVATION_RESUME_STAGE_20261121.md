# M5 resume after completed installation

The original native window intentionally admitted only a first installation
from the old source. That left an integration gap at the roadmap's required
cut after a COMPLETE installation and before its retry had settled. The
existing application receipt/retry owner already supports that cut.

The explicit `--resume-complete` staged entry uses a new, unused native
window for the same independently qualified release. It rechecks the exact
active COMPLETE journal, manifest, and installed source and runtime before
admission, after native exclusion, and on restoration. It gives the existing
application retry owner its normal scraper and writer locks. That path skips
first-install selection and checks its active binding again under the app
scraper lock. The default still admits the before-image only. A spent window
can only be restored, and restoration never reruns the worker.

The two independent QA lanes each passed 12 offline cases for the native
and application parts. The native suite used real directory exchange and
filesystem locks with substituted services and observer. The app suite
proved that the original install selector cannot run in explicit resume.
The staged CLI refused absent qualification before native code loaded.
[Native resume QA](S5_AMPHENOL_COMPLETE_ACTIVATION_NATIVE_QA_20261121.md)
· [Entry and one-shot QA](S5_AMPHENOL_COMPLETE_ACTIVATION_ENTRY_QA_20261121.md).

| Staged component | SHA-256 |
| --- | --- |
| Native adapter | `9e51c5197f4682fe653685a690481f98645f056d0229d4dfde4ad7ec36494b91` |
| Release entry | `e83730be7e69dce3e5a787b61d42c70603859ce1dad8df850d8fcc658d96aecd` |
| Private application one-shot | `1090d18053a50323b996a1ff0f3bfe82228db3c15eeb2c3422cc99795262cb00` |

Root installed the accepted entry and one-shot only in the existing private
qualification directory. Its real default shell verified all seven source
origins, the unchanged proposal and exact candidate. A separate physical
readback found the exact unchanged-before runtime and refused continuation
because there is no active release. The actual wrapper candidate
`895ec36e…` and proposal `REL-53592bb86b62492840c58267` remain unchanged.
No provider contact, production service or application change occurred.

The public qualification gate remains held until a complete current run.
There is no installation to resume now. The guarded native window still
requires its fresh observer if that qualifying evidence becomes available.
