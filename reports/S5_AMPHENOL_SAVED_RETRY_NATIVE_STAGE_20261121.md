# -07 saved-retry native window stage

Status: prepared only; no observer, service, `/run`, router, or production
action was performed.

The stage is an exact completion-only derivative of the accepted -06 resume
window.  Its maintenance identifier is
`s5-amphenol-saved-retry-20261121-07`; its prospective observer socket is
`/run/jsh-s5-amphenol-saved-retry-07/observer.sock`.

The -06 predecessor was read-only verified before staging continuation:

| record | SHA-256 | terminal state |
| --- | --- | --- |
| native-window.json | `a6df3c1d196187183d1185a718c2a643c4124d4af9f878157c553c4927d235c1` | `RESTORED` |
| operator-quiet-window.json | `f7cf92c27f1cc72cecdf5d13b10b9a3afab5b89fed59aafceafd2471e6f4c437` | `RESTORED` |
| exchange-private/exchange.json | `ae77b6e09c7d2958e059d9fa8c8315125012a6193d6662111e5a3785cb8deabe` | `restored` |

The exchange terminal proof was
`894cd4410ee656f945c24791b166e6eb893d23723af21cb9aa6471419aecaa30`.
`NativeWindow._require_predecessor_06_restored()` subsequently passed against
the actual saved records using only private readback.

The only behavioral narrowing is that `resume_complete` must be exactly
`True` at construction, readiness, and restoration.  The existing physical,
bridge, scraper, worker-lock, exact-source, and scoped restoration safeguards
are retained.  The disposable suite includes both predecessor-terminal and
before-only rejection coverage.

Offline result: `python3 -B -m unittest -v test_native_window.py` — 13 tests
passed.
