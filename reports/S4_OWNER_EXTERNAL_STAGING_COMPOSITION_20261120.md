# Sprint 4 owner-external intake and retained staging composition

**PASS in one disposable composition.** The accepted owner-external helper produced one eligible Company revision and outbox event with origin `sheets-reconciliation`. The existing Sprint 4 operator command accepted those exact event, Company and source revision values for `stage-event --company-event` behind one disjoint retained historical blocker. [Composed test](/tmp/jsh-s4-owner-external-retained-composed.qNA17pl8/test_owner_external_retained_stage.py)

The test invoked the real staging command under a real scratch scraper lease. It revalidated the historical manifest using the scratch State, Jobs and Inbox and used the normal bridge to produce one request, acknowledgement and bridge receipt. The existing read-only verifier returned the same evidence. A second staging invocation returned the same result and left the request and receipt bytes and full acknowledgement row unchanged. The historical State and Scan Cycles mirror and the rebuilt inventory, plan and Jobs evidence matched their original snapshots. The enabled automatic dispatcher held the manually reserved request.

| Artifact | SHA-256 |
| --- | --- |
| New composed test | `2cd6f2fc1a1d1727ad8ad082af889b4ceef4e4cfd11f2ad37f981663aa95a773` |
| Accepted external intake source | `c053591c38e27e36b564a953da4835cefd1d5bd0aff4a23b0db12caff4d8607e` |
| Sprint 4 retained operator command | `d3708c7173d9a8653877116cae7fa41b53c902a8e3c929536edbaeee18fe0724` |
| Sprint 4 Company-event bridge | `149ec39ca47f3adbb338fa77d95fc99d12db70ccbe6544a678c11a3d0ab422ea` |
| Reused retained staging fixture | `3dae6de9f4eb2a03376fcc88c83de39d59960a0ea62f2fd46bdb8552d469bd26` |

The system interpreter passed this one selected test in 0.48 seconds. The admitted scratch paths and repository factory were test-supplied. The helper used its existing synthetic workbook service, and the test forbade a real Sheets client, socket connections, and hostname lookup. This result covers staging through the bridge acknowledgement and receipt. It does not cover signer authorization, scrape, publication or live activation.
