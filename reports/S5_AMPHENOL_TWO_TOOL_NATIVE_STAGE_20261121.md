# Amphenol two-tool maintenance stage

The approved source pair enables one fresh operator-owned repair for the
same failure as the spent prior request. Its installation is a coordinator
tool update. The application adapter and scrape data stay outside the scope.
The eventual application release needs its own live qualification and
one-company retry proof.

| Artifact | Exact staged SHA-256 |
| --- | --- |
| `deploy_two_tool_forward.py` | `cf9f82f6b85f441ab2e0fdd9bfee1448aa6c1e444ade09a3e66e2748ebb75597` |
| `test_deploy_two_tool_forward.py` | `0ab6e58b6260918ddf409af778239248e9ac0689d55561f530e5f1730b2ee697` |
| `current_tool_guard.py` | `e77f4ecc994ea45e8ddab97fbda76673bf2e41a2dc701b52bbb2e0d1a038dc31` |
| `test_current_tool_guard.py` | `a614fc84492549aebb7d0345c766acb1d937710eb622af98846f447595cbff78` |

The existing -03 terminal routine rechecks its old host image. The current
verified -04 receipt authorizes a different installed host image. The new
guard retains the historical locks, receipts, installer transaction and
directory identity checks, and uses the exact -04 host image for the
current layout. It also requires an independent positive live exclusion
check. The two-file updater stops only the existing wrapper service, saves
both prior files privately, writes the Store then the host, and confirms
the source binding at restart. On a failure with either new file present,
it verifies the stopped service and restores both scoped files before
starting the previous wrapper. Historical and current receipts are pinned
separately.

The root updater run passed its three focused offline cases, including
a stop that took effect before its callback raised. The guard fixture
passed across the current receipt, changed transaction and parked-source
identity cases. The old installer journal and embedded receipt agree on
the current host using a read-only byte comparison. Production source,
service configuration, database, app, and Jetson state were not modified.

Independent guard QA found missing readback of the actual historical
installer transaction. The corrected guard proves that journal and
directory identity, and passed recheck. Independent updater QA found that
the stop inside rollback could stop the service and still report an
error, leaving the changed files in place. The correction verifies that
the service stopped after that error before restoring either file. The
independent reviewer reran the three maintained tests and the original
repro. All four passed on the exact corrected updater. The historical
rejection evidence is preserved.
[Guard QA](S5_AMPHENOL_CURRENT_TOOL_GUARD_QA_20261121.md)
· [Initial updater QA](S5_AMPHENOL_TWO_TOOL_UPDATER_INITIAL_20261121.md)
· [Corrected updater QA](S5_AMPHENOL_TWO_TOOL_UPDATER_QA_20261121.md).

Remaining gate: join the existing native process, listener, alternate
checkout and unchanged-scope readback to the staged guard. It must use
fresh actual host-exclusion evidence and confirm installed and restarted
tool identities, services and the default-off controls with the historical
task and inference receipt intact. Then obtain independent acceptance of
the exact native result. An administrator observer may be requested for
that host evidence once the window is ready. Leave it off before then.
