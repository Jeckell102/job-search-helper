# Independent nine-path maintenance policy and controller QA

**ACCEPT** for the revised staged source policy and disposable nine-path install/rollback.

| Reviewed artifact | Exact SHA-256 |
|---|---|
| Installer | `d85405266310a425bcc49027b5629cfb81dcc89f391cfbf75df33da7ac2a0920` |
| Controller | `f63f9399f3fcdec3d3b46a6d5e14fc3d1d78e420234b357b0adf44bd68a53ff8` |
| Maintained policy tests | `15b63561a11f28f23c972b2eb6fd8ec459621de8cc07e98793769bba4cb8ebb8` |
| Disposable nine-path manifest | `aea73847baae2595c457f1eb4e29ba380e0f378a33016cf5e01757d0680f14a5` |
| Disposable controller result | `18ffcb164a5a35e83653ce5910a659f6f3128808a2ce7f7a92875116fb7377c2` |

The exact approved old 44-path manifest parses identically through the previously approved and new installer. Legacy and prior consolidated sets remain intact. The new schema is limited to the exact nine paths and requires existing before-images for the six known installed endpoints, including root `release_admission_bootstrap.py` and the executable launcher. It permits absent before-images only for the three newly added operator application modules. The initial parser `5603b7fc…` accepted a missing bootstrap before-image. The final parser refuses the same exact fixture. All 25 guarded source tests passed.

The real controller and installer in scratch reached `RELEASED/INSTALLED` for the 44-path predecessor and nine-path successor, then `RELEASED/ROLLED_BACK` with the successor candidate unavailable. The predecessor used all 44 exact reviewed after-image bytes with synthetic predecessor before-images. The nine after-images came from the then-current staged source files. It used their staged modes in the fixture manifest. The root bootstrap moved forward and back between the actual staged bytes. All 44 predecessor after-images were restored, including 40 unscoped files that retained the same custody throughout. The three operator module absences returned, and 134 predecessor artifacts, inherited guard and receipt bridge stayed unchanged.

The first disposable attempt exposed an old fixture helper assumption that coordinator_store.py always belongs to the successor scope. The proof changed only that disposable service helper to choose the always-enrolled wrapper host for its side check. The exact candidate tools stayed unchanged. Systemd, physical exchange and protected continuity were substituted disposable observations. No native prep, production access, service action or data operation was performed.
