# Independent QA — Sprint 5 verified transport/capture capsule recheck

Date: 2026-11-20

## Verified pins

- `DEPENDENCY_RECONCILIATION.md`: `8582872949d277457fc12a0c9eae38d0369732a5fdf13be0f2abc68247061e8a`
- `capsule/dependency-manifest.json`: `cf490b246224243fb560378145235fb600e067f3d8327ced5daecea78e88d247`
- `run_verified_fixture_capsule.py`: `03c891c1291b781a3ef377b72a488ace07d06c490be71c41233608ed9ea8c9a3`
- `check_fixture_capsule_refusals.py`: `f501a5b713af32ee8893279e7d0bce596bfbc652658520d8d6ece9043a437388`

The correction is real: the accepted collector is separately named as `rippling_public_capture.py` (`6a8…`); the parser/limits module actually imported by both collector and transport is separately named as `rippling_capture.py` (`46a0…`). The prior finding was correct for the earlier ambient-path test arrangement; the exact fixture closure now resolves that ambiguity for its synthetic execution.

## Fresh exact closure

```text
env -i PATH=/usr/bin:/bin PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3.11 -I -S -B run_verified_fixture_capsule.py --root /tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z/capsule --manifest-sha256 cf490b246224243fb560378145235fb600e067f3d8327ced5daecea78e88d247 --test-temp <fresh /tmp directory>

Verified 42 copied source modules and 388 framework files.
89 passed in 3.25s
```

The runner checked every manifest path and digest before project imports, rejects unlisted project modules, verifies loaded source origins, runs with `-I -S -B`, disables plugin autoload, uses only copied framework support, and installs a native-socket audit veto for the fixture execution.

## Replacement/preload refusals

```text
env -i PATH=/usr/bin:/bin /usr/bin/python3.11 -I -S -B check_fixture_capsule_refusals.py cf490b246224243fb560378145235fb600e067f3d8327ced5daecea78e88d247

Fixture capsule rejected: Digest mismatch before import: dev/pre_release_validation/rippling_capture.py
Fixture capsule rejected: A same-name fixture module was already loaded before verification
```

The first probe substitutes a same-name parser in a copied capsule and is rejected during raw digest verification. The second preloads a same-name parser and is rejected before test collection. These directly close the earlier synthetic-fixture import-provenance gap.

## Verdict

**The previous dependency-pin issue is satisfied for the exact integrated synthetic capsule.** The original isolated-adapter report should remain preserved as historical evidence; this capsule supplies the missing reproducible named dependency closure and pre-import refusal behavior.

This is not activation approval. A real execution still requires the separately measured caller to establish the identical loaded-module provenance, selected endpoint/policy authorization, and egress controls before any transport is invoked. No live socket, network, credential, production resource, or activation action was used in this recheck.
