# Exact operator company-only entry deployed

November 22, 2026 Eastern. Source release
`REL-03cc531d6c60113584d57722` installed the ten reviewed endpoints
and validated the entire active runtime. The endpoints include the
normal scraper launcher, its pre-import bootstrap and the selected
operator path, planner, receipt and recovery changes. The test is in
the private source backup and stays outside production runtime.

Independent deployed QA matched all ten installed endpoints and all
applicable before images by bytes, permission mode, owner and size.
It verified the absent before image for the new module. The native
holder restored the original checkout routes and parked sentinels.
The wrapper and assistant bridge were active and enabled with PIDs
815986 and 816023. The scheduled sync service and timer were inactive
and disabled. Existing full coordinator ledger custody passed through
the guarded stop and restart.

| Evidence | SHA-256 |
| --- | --- |
| Prepared package | `b43de554d3119581cd595f5ad2635594e063d318ba4868a79d4ba9a306200c1c` |
| Active source tree | `d9eb79ef5ec5fc5990ee462f268b596ce349c16455974446c46994dae339b52e` |
| COMPLETE journal | `6256d17daca06885913c04f80f2a74af9e477bca70dfefd1377816d160d37108` |
| Release receipt | `bff54b0a497105170f1b846f3527f0407b935019aa80c26278c31d98feaa403a` |
| Native restoration | `e50fcaa910393679399b089abd281301cd281069fc835f30bf1582157a842563` |

The predecessor journal and before images are sealed under
`.state/native-runtime-releases/REL-03cc531d6c60113584d57722`.
An interrupted PREPARED change is restored through the owned native
window, whose bootstrap loader accepts only the two approved byte
images. A completed source rollback is a separate reviewed reverse
transition. The [source and fixture acceptance](S7_POSITIVE_OPERATOR_SOURCE_QA_20261122.md)
covers a simulated lost acknowledgement and recovery without replay.
Live pilot completion and the separate real lost-acknowledgement gate
remain distinct. Broad backlog, scheduled sync and unqualified releases
remain off.

[Independent deployed readback](/tmp/jsh-positive-operator-native-release/DEPLOYED_READBACK.json).
