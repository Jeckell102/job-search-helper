# Recheck of the Amphenol host-only updater and native launcher

**REJECT** the reviewed core and launcher. The original two rollback defects are repaired on the narrow exercised paths. Three related failures at the same transition remain, and the launcher's apply call cannot pass the updated function signature.

| Reviewed or captured evidence | SHA-256 |
| --- | --- |
| Updater | `042b56e51556958eedb7adb17f8c5c247f7e53b65a5a0ca2f8540b78a683c441` |
| Maintained tests | `795b6f4097ec26c20bc875526b0edb7887fd951e77cf3302815960477085c9d6` |
| Native launcher at inspection | `8e5cc1753138ed843439ec6aa2b8b378673413c32e8808b00737cbf028d94cc8` |
| Six passing checks | `7548474fb14d06939e7c5c04118884c7575e481e66341dcb60a44054161cc931` |
| Late-effect probes | `5fb35194d4a0ecfecbd424719cd2756b77f75b0b01c80ac108a1f183b254859a` |
| Combined test output | `5c8be3b214a325db1415faef9153a0a2c9a8892764bdf09f0f44629756147d23` |

Four maintained tests passed, as did both original independent probes after supplying the new mandatory stopped-state callback. The original findings and exact original source remain preserved in `/tmp/jsh-amphenol-host-forward-independent.Ij1ijZdX` with report SHA `6de1f7b91aa3114f14ea4485ae75e578599693ff835cb6c450f28eb59504c057`.

The actual disposable file and emulated service checks additionally reproduced:

- A replacement that completes the rename and then raises leaves candidate bytes with no active wrapper. The updater assigns its replacement flag only after the call returns.
- A start that loads the candidate and then raises leaves candidate bytes and candidate runtime. The updater assigns its start flag only after the call returns, then cannot prove that the running candidate is stopped.
- A failing readiness probe for the restarted original is never invoked. The code publishes `HOST_FORWARD_ROLLED_BACK` after the start call alone.

Track attempted effects before effect calls, observe exact source to decide whether an original image needs restoring, prove that a potentially started candidate is stopped before restoring, and verify original runtime before writing a verified rollback receipt.

The launcher statically binds the exact approved -03 manifest, controller terminal, installer receipt, three restored routes, checker-derived listener and process evidence, task and inference request IDs, and approved adapter digest. Its only stop/start target is the wrapper. The apply call omits mandatory `stopped_probe`; with these exact pins, it creates the private -04 directory and raises before touching the wrapper or source. The preflight branch bypasses that call. Wire the already implemented inactive-unit and exact listener-absence proof as the required callback.

Only staged source and disposable files were used for this review. Native SQLite, services, application, network, and socket availability were outside this run.
