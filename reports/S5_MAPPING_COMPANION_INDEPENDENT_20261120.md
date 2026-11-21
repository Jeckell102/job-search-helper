# Independent acceptance — S5 paired source mapping release — 2026-11-20

**ACCEPT the exact final staged slice for its normal application contract.** A qualified automated mapping correction can replace its existing registry and measured descriptor together, while keeping the prior pre-install qualification, installed verification, rollback and exact retry boundaries. This is source/fixture acceptance; it establishes no real candidate qualification and deploys nothing.

Reviewed tree: `/tmp/jsh-s5-mapping-companion.4mbNVvkr`. The root agent owned every application edit. This reviewer added only `/tmp/test_jsh_s5_mapping_independent.py` and this report. No live use, production application paths, network or job data were exercised.

## Verified behavior

- `integration_release.py:169–176,217–225`: only the exact package file `source_configuration_manifest.json` gains a non-Python exception. It must accompany existing `company_sources.py`; both need a non-null before version. The only permitted extra files in this paired release are ordinary `tests/test_*.py` files. An unrelated package JSON, runtime module or configuration file cannot use this exception.
- The final additional check at `integration_release.py:325–332` rejects automated registry changes that omit the measured descriptor. A descriptor change also requires the exact configured qualification owner and the preinstall path. A manual call or arbitrary preinstall callback cannot authorize the companion exception. Existing ordinary manual releases retain their original path.
- `release_source_mapping.py:15–36` reads both artifacts without following path components and matches their exact before/after hashes. The descriptor must retain the reviewed Rippling capability and source-path list; each unique mapping must bind the full registry digest. Invalid, duplicate or added capability data holds.
- `release_source_mapping.py:70–88` preserves descriptor Company membership. Only the selected Company's configured board may change; every descriptor registry hash is refreshed to the changed full registry. Nonselected boards, names, authority/evidence, aliases and other mapping fields remain equal.
- The registry is parsed as inert Python AST (`39–67`). The selected Company must occur once and identify an exact literal dictionary matching the descriptor. Whole-module AST equality is required after masking just that Company's board URL. Unrelated executable changes and mismatched registry/descriptor values hold. The existing closed Rippling URL grammar also rejects a different provider host.
- Installation runs these checks under the existing scraper lease, before rollback preparation (`integration_release.py:366–374`). The accepted qualification reader remains byte-identical to the previous accepted slice. Existing complete-tree projection, post-install verification, completed receipt pin/readback and retry behavior remain exercised.
- Disposable positive tests install both files and schedule exactly one retry on replay. An installed verification failure retains the guarded recovery journal; rollback restores both original byte sequences and creates no retry. A separate fixture copies the staged application's real registry/descriptor, induces one stale Forterra board in the before snapshot, and accepts the exact correction to the unchanged staged candidate.

## Independent execution

Python 3.11.18; `PYTHONPATH=src:tests`; `PYTHONDONTWRITEBYTECODE=1`; pytest cache disabled. After the final automated-registry-only rejection landed, the bounded full check was rerun against the final source:

```text
python -m pytest -q -p no:cacheprovider \
  tests/test_release_source_mapping.py tests/test_release_qualification.py \
  tests/test_release_controller.py tests/test_integration_release.py \
  tests/test_repair_retry.py /tmp/test_jsh_s5_mapping_independent.py
95 passed in 19.62s
```

This comprises 86 maintained focused cases and nine separate reviewer probes. The additional probes reject a descriptor without its registry, either newly created pair member, extra configuration, altered capability, removed membership, duplicate mapping, another provider host, and public-only qualification of an otherwise valid pair. Rejections preserve the disposable installed source/configuration and produce no rollback record, release journal or retry request.

## Final pins

The final files matched these hashes after the independent rerun. Earlier pre-final test results are not used as evidence for the added registry-only guard.

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/release_source_mapping.py` | `ebada213094279aa015c47757d1ce07786e6f2670b7e3689b5597fa1b66971cf` |
| `src/job_search_helper/integration_release.py` | `8703b06828fbd94b70874c5ead787c03dce8ce4f20fe7968870ff6f1639f8386` |
| `src/job_search_helper/release_controller.py` | `e2bfa0e68f2f75685714ebf6902a1329e356945d179e602189703da2c9263f97` |
| `src/job_search_helper/release_qualification.py` | `886e6ac97e9b4979fdde4cb9f01630a8896edb569418f19bdfd76c7190f323d5` |
| `tests/test_release_source_mapping.py` | `34b1d2c3588f0e46c45e488e5cca2991f6f2fc33c465866619ef95b5ad51d62a` |

## Authority boundary

The fixtures manufacture a synthetic approved qualification only to test release behavior. This slice does not issue that qualification, validate live employer evidence, create a mapping fact or Jobs outcome, or widen application write authority. A valid board URL is a structural constraint, not proof of employer ownership. The independent live evidence authority must still approve the exact candidate and selected board. Existing offline/public-only results remain ineligible; no live producer or production installation was accepted here. No check was flagged.
