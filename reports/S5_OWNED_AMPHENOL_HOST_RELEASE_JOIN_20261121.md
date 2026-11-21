# Sprint 5 host-owned Amphenol release

November 21. The maintained host previously stopped after saving its owned
recipe candidate. A separate terminal callback recognized an already
published retry. The test harness supplied the call between them. The
staged host now calls the existing guarded installer for one exact completed
Amphenol task and independently approved release. This is a staged
candidate. Current native release admission still holds unfinished work.

The existing exact event enrollment and pinned retry approval are both
required. `WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE=1` explicitly opts
that exact process into installation. An approval used for receipt readback
alone keeps its existing behavior. The private approval directory uses the
existing canonical qualification receipt plus `<release_id>.manifest.json`
and `<release_id>.candidate`. The original independent receipt pins the
manifest and the manifest pins the complete source, configuration and
dependencies. The host cannot issue a qualification receipt.

The existing application leases protect the read of the archived origin,
the finished pilot, its one settled choice, the generated source and the
full independently measured candidate. The host releases those application
leases before calling the guarded installer. The exact pilot, current
Company revision, control generation and disabled global scheduling still
need to match. The existing installer holds its normal application leases,
then a fresh measured worker takes the exact retry. A measured callback
reads back the full installed runtime before the release becomes COMPLETE.

On the first integrated source, a completed release whose retry was held
could start the same worker at every supervision tick. For a publication
hold that could reopen the workbook repeatedly. The corrected source
checks exact terminal delivery first, then returns
`HELD_RECIPE_RETRY_CONTINUATION` for an already recorded COMPLETE release
without terminal confirmation. The operator can use the existing exact
scoped continuation after review. The host does not repeatedly reopen the
worker or create a new attempt. Unsettled installation journals retain
their existing guarded rollback gate.

The corrected stage is `/tmp/jsh-s5-owned-host-trigger-held-guard.20261121`.
Twenty-one focused tests passed, including the real host callback, lease
handoff to a fixture installer, readback-only default, terminal replay,
and held retry after rebuilding the host against the same durable record.
Independent QA then reproduced the original defect through the real host
and worker. The corrected positive canary used one owned build, one
measured child and a test-workbook batch that confirmed the same 18 jobs.
Receiver restart reused its terminal receipt. The corrected negative
saved the first worker's incomplete inventory, then restarted the host.
It held the same attempt with one worker total, zero workbook calls and
identical application records. The model reply, publication and approval
in these tests were fixtures. The existing intake terminal fixture also
passed after the actual project dependency manifest was supplied to a
disposable copy, clearing the earlier source-only test setup failure.

| Exact staged file | SHA-256 |
| --- | --- |
| `host_server.py` | `30854d51eaaf0bc2dcd4f833d192acf28572b8c0ec63ba0ac2a25c1f4e6dc586` |
| `amphenol_retry_completion.py` | `c7ca5f021989a5f552482be2f3eb3d40a3da428c733f49b6f8a601c05945f6ef` |
| `amphenol_candidate_release.py` | `7cf2c0795925f077b5cda4a67ce6418adf6fbafae2a955732f60765951ab087f` |
| `amphenol_installed_verification.py` | `aeea069ce3ea41d721f19eba73b21ac351ac820d991e3da9f85e546c33d58b8d` |
| `test_amphenol_candidate_release.py` | `50b4d3d09200fd36561ba58cb7c3c6434097a0c07c2f82c12e511c21473a6a92` |
| `test_amphenol_installed_verification.py` | `30e3fd8fa95690fe09c71e44fd73a4da90cf76ce5628193686c4b4ef5f86480d` |

[Native route verdict](S5_EXISTING_NATIVE_RELEASE_ROUTE_INDEPENDENT_20261121.md)
· [Direct installer QA](S5_INSTALLED_RECIPE_READBACK_INDEPENDENT_20261121.md)
· [Corrected host QA](S5_OWNED_HOST_RELEASE_INDEPENDENT_QA_20261121.md)
· [Initial failure report](S5_OWNED_HOST_RELEASE_INITIAL_QA_HOLD_20261121.md).
