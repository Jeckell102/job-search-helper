# Sprint 5 transport dependency reconciliation

The exact staged transport and capture helper passed their integrated synthetic suite from verified copies. The earlier independent report remains intact. This update resolves the name and pin ambiguity and provides a reproducible dependency capsule for independent QA. It does not change the transport or grant activation approval.

## Exact named dependencies

All copied paths below are relative to the sibling `capsule/` directory. The manifest gives the full originating path, exact copied path, role, and SHA-256 for each listed module and all transitive test paths.

| Fully qualified project path | Role | SHA-256 |
| --- | --- | --- |
| `dev/pre_release_validation/rippling_public_transport.py` | Staged adapter | `1df2a46f9f0aff246a9e0b1c5a74a96bf3d012a5a861ff9253dc7646809c708a` |
| `dev/pre_release_validation/rippling_public_capture.py` | Accepted collector that consumes the adapter in synthetic composition | `6a8ff763c69f7aeebf3da0f60b85a2d7deba17c9f2b20677d9a5e75db58bd571` |
| `dev/pre_release_validation/rippling_capture.py` | Separate parser, CaptureError and pagination limits used by the adapter and collector | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| `dev/pre_release_validation/rippling_public_authority.py` | Reviewed route and public header rules | `5297cf4832bb287c91fac89f498729ec6c2d1c1dff9dc23008a6949568ac3e57` |
| `dev/pre_release_validation/validate_candidate.py` | Digest and byte limits and the existing synthetic candidate replay | `e1e5cfb34c01694f9722169343d9fe19417c16623758de79cb74c17685aca25e` |

The previous independent report treated the accepted collector hash as the expected parser hash. Both files are now named and verified separately. The missing import-provenance concern is valid for activation. Its conditional conclusion is preserved. [Original independent report](/tmp/JSH_S5_PUBLIC_CAPTURE_TRANSPORT_INDEPENDENT_QA.md)

## Capsule verification

- Manifest SHA-256 `cf490b246224243fb560378145235fb600e067f3d8327ced5daecea78e88d247`. The closure contains 42 exact project and fixture modules plus 388 separately pinned framework files. The platform trust root is system Python 3.11 and its standard library. [Dependency manifest](/tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z/capsule/dependency-manifest.json)
- Fixture runner SHA-256 `03c891c1291b781a3ef377b72a488ace07d06c490be71c41233608ed9ea8c9a3`. A clean `-I -S -B` interpreter checks the separately supplied manifest digest and the exact copied paths and file digests before source import. It executes the verified project and fixture bytes, checks their loaded origins, rejects unlisted project imports and native socket activity, and uses copied framework dependencies without ambient packages, config or plugin discovery. [Fixture runner](/tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z/run_verified_fixture_capsule.py)
- Negative fixture SHA-256 `f501a5b713af32ee8893279e7d0bce596bfbc652658520d8d6ece9043a437388`. It substitutes the same-name parser in a disposable copy and separately supplies a preloaded same-name parser. Both are refused before import and test collection. [Negative fixture](/tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z/check_fixture_capsule_refusals.py)
- **89 passed in 3.33 seconds** from the verified capsule. This combines 47 adapter cases, 27 accepted collector cases, ten original independent probes and five callback probes. The accepted collector completes the actual 31-exchange synthetic ledger through the new adapter. Both refusal probes passed separately. No native socket, credentials, production resource, or prior artifact write was involved.

For activation, the previously planned measured owner must establish loaded module provenance before executing the transport or its dependencies. It owns the transport, collector, parser, authority and validator closure pins and the independently approved endpoint and policy configuration. A transport-side check after importing bare module names could not establish that provenance. No activation owner or redundant transport check was added here. [Measured caller boundary](/tmp/jsh-s5-measured-issuance-launcher.NiHiTtwZ/MEASURED_CALLER_BOUNDARY.md)

## Reproduction

From `/tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z` after independently checking the runner and manifest pins, use an unused scratch test directory.

```sh
env -i PATH=/usr/bin:/bin PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3.11 -I -S -B \
  run_verified_fixture_capsule.py --root /tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z/capsule \
  --manifest-sha256 cf490b246224243fb560378145235fb600e067f3d8327ced5daecea78e88d247 \
  --test-temp /tmp/jsh-s5-public-capture-transport-pin.Cp0PpA1z/review-pytest
env -i PATH=/usr/bin:/bin /usr/bin/python3.11 -I -S -B \
  check_fixture_capsule_refusals.py cf490b246224243fb560378145235fb600e067f3d8327ced5daecea78e88d247
```
