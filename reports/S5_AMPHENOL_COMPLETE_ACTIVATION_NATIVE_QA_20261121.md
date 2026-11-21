# Independent QA — M5 same-COMPLETE native continuation

Verdict: **ACCEPT — source/disposable resume-cut scope**

This acceptance covers only the private native-window continuation composition.
It does not authorize a native invocation, application retry, source install,
provider contact, scheduler action, or release.

## Exact accepted inputs

- Adapter: `native_window.py`
- Adapter SHA-256:
  `9e51c5197f4682fe653685a690481f98645f056d0229d4dfde4ad7ec36494b91`
- Fixture suite: `test_native_window.py`
- Fixture suite SHA-256:
  `7895356b36b9cd68d8c5d5076d15f7da44d5e96d2c6edc66f8605dcc1880030a`
- Predecessor accepted adapter SHA-256:
  `8f40d99f3718cee74cb5d522e648f41befde5ca1f3a4282650b711fc555ef069`

## Narrow delta reviewed

The change is limited to an explicit boolean `resume_complete` policy:

- Default behavior remains the prior before-only admission and continues to
  reject an active COMPLETE release.
- The opt-in continuation requires the exact active COMPLETE release binding
  for the same canonical manifest, including matching source/config/dependency
  measurements.
- The exact check runs during readiness, again after exclusion immediately
  before the worker yield, and during restoration.
- The native window journal records the continuation policy; recovery cannot
  reinterpret that window as a first installation.
- No installer, new retry authority, provider path, scheduler, or execute
  shortcut was added.

## Independent disposable result

Command run:

`python -B -m unittest -v test_native_window.py`

Result: **12 passed**.

The positive continuation fixture exercises the actual copied
`integration_release` and `repair_retry` binding logic, real fixture exchange
and flock behavior, and a simulated restoration failure/recovery. It proves
the application activation journal and source bytes remain unchanged; the
worker/app scraper lock remains available while the deployment lock is held.

Negative coverage rejects missing, rolled-back, wrong-release, wrong-manifest,
wrong-binding, changed-source, and no-qualification states. It also proves the
default policy remains before-only and that a spent window cannot be reused.

## Boundary

This is not live qualification or release acceptance. Real invocation still
requires the root-owned exact qualification owner, current observer, actual
native custody/lineage checks, and separately authorized application-resume
execution. No live action was taken for this QA.
