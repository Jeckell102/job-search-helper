# Sprint 5 Amphenol scoped retry and test workbook

November 21, 2026, 01:47 Eastern. Independent QA accepted the exact
publication evidence. The release, job database, and workbook in this
replay are fixtures.

The prior genuine public retry returned all 39 advertised postings in one
fetch and froze the exact complete inventory. The prior test run saved 18
applicable rows locally and stopped before publication because its deferred
checkpoint did not advance to locally processed. The new source also binds
the actual repair request and release in the publication plan and receipt.
Both fixes were exercised together in a fresh disposable copy, using SQLite
backups so the settled original failure attempt survived the copy.

| Gate | Verified result |
| --- | --- |
| Guarded installation | The disposable guard installed the pinned runtime and the validated Amphenol adapter `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`. All 16 installation checks passed. The guard created `REL-76cc6f8179568b839386f429` and one request `company-retry:RTRY-94818009148713cd8859150f`. Replaying the guard returned the same durable request. |
| Scoped intake | The normal requested scan consumed the exact retry and recorded `CYC-8F35E1D030EF` for only `COMP-0490`. It saved the 39-posting inventory from the hash-verified local archive. Three isolated commands denied network access. The retry made zero provider calls. |
| Local storage and workbook | Normal exact recovery began without an existing publication plan. Filtering saved 18 unique Amphenol Job History rows. The in-memory workbook applied one write batch and read back the identical 18 keys. The settled predecessor remained identical. |
| Terminal identity | The durable inbox held exactly one `SYNC_CONFIRMED` receipt for the actual retry request and Company, bound to the active rehearsal release. The private exact request SHA-256 is `9aa2817ef445ff37791ad3ab083ea67c2a364724cf121471346818e890fccb69`. |

The evidence lives at `/tmp/jsh-s5-amphenol-publication-rehearsal/`.

| Evidence | SHA-256 |
| --- | --- |
| `publication-source-pins.json` | `b4cd14e0efad776d5aa0a33fae26780352f470b93eaef127223766192f0a66c3` |
| `rehearsal-result.json` | `9e66ed37ed7aab642cfa98334f18e4f6f6b5855a9ca46acdb84c784fe2b27ce9` |
| `scoped-retry-result.json` | `443a9eeac6297a5416be5a88fc862a602ee3aa719ac9f0b4300c9c1310e902f9` |
| `fixture-sync-result.json` | `802a4d905c415cf5c8f61f38122d5b1e89e242e841d53b875d2b01a0be46389f` |
| Private `fixture-workbook-readback.json` | `3296275b166ce0735edd9a3046b92795f663a428676603d0ad2edc8d3c4b890e` |
| Private inventory archive used by the retry | `94250320f27fbf987f417405599f609de6ea965feb41f1b6297cfee57dba5fa8` |

The older blocked fixture and the historical production cycle are preserved.
No native release, real Google client, real workbook write, or schedule change
occurred. Production needs a genuine initial failure with current owned
provenance, qualified install, and independent verification of the resulting
retry and published rows. Keep broad processing and automatic release off.

## Local cycle closeout on a separate disposable copy

The workbook rehearsal finished exact company publication. The Company
stage was complete, and the overall cycle status was still In Progress
because exact recovery does not run the normal cycle closeout. On a separate
SQLite backup of the same completed fixture, the normal local sync-only
resume advanced only that cycle and its local mirror to Complete. The
admission blocker for the fixture's next cycle cleared. The exact receipt,
Company, Job History, Job Evidence, Opportunities and predecessor remained
identical. The test had a rejecting fetcher and network audit guard. It
made no workbook write, and changed no application source. The first copy
correctly held on the missing release journal. The confirmed rerun carried
the original exact journal and archived request.

Sanitized closeout result
`/tmp/jsh-s5-closeout-check.yynrvfx6/closeout-result.json`,
SHA-256 `e8f5d42f3c7667f468e951bdb58160655361908680389ee0a5b0f72afe54b25f`.

Earlier evidence is in [the live wrapper validation](S5_AMPHENOL_RECIPE_LIVE_ACCEPT_20261121.md),
[the owned failure and Jetson choice rehearsal](S5_AMPHENOL_OWNED_REPLAY_20261121.md),
and [the preserved publication hold](S5_AMPHENOL_DEFERRED_PUBLICATION_HOLD_20261121.md).

[Independent workbook readback](S5_AMPHENOL_FIXTURE_WORKBOOK_INDEPENDENT_20261121.md) ·
[Independent receipt binding source review](S5_AMPHENOL_RECEIPT_BINDING_INDEPENDENT_20261121.md) ·
[Native failure-origin hold](S5_AMPHENOL_NATIVE_ORIGIN_READBACK_20261121.md).
