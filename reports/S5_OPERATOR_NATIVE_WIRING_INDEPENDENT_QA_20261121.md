# Independent operator -03 launch and restoration wiring review

**ACCEPT** for the exact restamped source wiring.

| Reviewed source | SHA-256 |
|---|---|
| Freeze wrapper | `d3ba82f1e0a0929b9f57e6febde00d733d6743933f8a45c93dd61238431ee6e1` |
| Observer verifier | `837fd402cd9b46c677abd340feaeafd613ff8936c05bd81096b408cd1ca58065` |
| Guarded launch runner | `ccf7e1bb5c9d70d1fa956a1da859e98cc4fbd9d0ef9d364bb6b1429cf5ee759f` |
| Success restoration wrapper | `a24e299c898cae876564594807a72a8b5b30d3407a41455544023527f68cbec0` |

The freeze wrapper uses the exact independent `-03` enrollment `8d428d7f…`, the pinned current protected witness and unchanged guarded runner. The prior corrected thaw behavior remains intact and all four guarded disposable cleanup cases pass. The underlying runner still demands the enrolled private 0700 executable, pins the observer source, and applies its protected and unused-attempt checks before the exact launch.

The verifier takes the caller’s independently approved checker digest. The expected invocation uses `c0bec31a…`. Its static bundle, ID, launch UID, listener port and exact `/run/jsh-s5-operator-03/observer.sock` agree with the prepared enrollment. The observer start script has the same root-owned source and exact static scope of two helpers and seven checkout route arguments. Shell syntax passed without invoking it.

The restorer verifies the exact `c0bec31a…` checker, the `e35dac07…` exchange and reviewed nine-path manifest `8c73be24…`. It retains the existing archived `CYC-B639C6D864EC` proof as continuity, with the unchanged archive scope and protected pin. The installed-source measurement, inherited lease and sealed protected-state rereads remain intact. Native observer freshness and successful launch/restoration still require owned readback. No production files, observer, process or service were accessed during this review.
