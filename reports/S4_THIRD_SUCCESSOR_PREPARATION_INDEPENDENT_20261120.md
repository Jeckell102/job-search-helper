# Third successor preparation: independent handoff

**ACCEPT private preparation only.** The third successor must inherit the immediate completed `s4-atomic-machines-20261120-02` terminal rollback, while retaining the exact physical guard originally created by the earlier release. It must not substitute the first release's terminal receipt or restored exchange for the second's.

This follows `controller.py:553–621`: the observed predecessor is opened, its terminal Controller and installer receipt must be ROLLED_BACK, its actual journals and restored exchange are compared to the handoff, and its original protected pin and guard are retained. `load()` additionally checks an inherited guard against the predecessor's own handoff (`controller.py:666–668`). Existing inherited provenance remains immutable; it does not require creating another guard.

## Verified new private bundle

`/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01`

| Artifact | Exact SHA-256 |
|---|---|
| Host checker | `e62365c1fcce52018900f6a3687c16fdf90ed89b4681ea0c4c185c4e99b19dd6` |
| Unused preinstall enrollment | `3d2bb8cee5cccf7948d1a657594f67a60d31f079bbb35d185ba49720b4738fc4` |
| Immediate predecessor handoff | `41359813a3795062beafe8d6f6644afc038c77de65d78ef108b3b6c8a40546a1` |
| Fresh exchange policy | `8b230d6cbc620779212f85fc8b66c27181f3d7a34eced08a8d1c6e09d2b083a2` |
| Embedded observed predecessor | `545c09e288491f9b0eae8e728478d7d2f84f8c2e8d83f2f9fca1efecf6ebfd56` |

Read-only comparisons matched the actual private -02 terminal Controller journal `e7773d0fa755a404c8d59a1ed3f4156c6345aab141ee103c9e542bcb7b571b49`, installer journal and canonical receipt, and restored exchange journal `b34626982fe987c99e95ae839923afaa2301aae5419ea6f2af8f211c5111bd00`. The carried guard's directory/marker identity, mode, ownership, parent, mount and marker digest agree with -02's own inherited handoff. The protected reference remains `abab8873ce31e0c0b8526f9bdcaa7ff684fc53498c3293f25b12a49092f28b96`.

The new checker, plan, handoff and enrollment agree on the fresh hold ID, bundle identity, manifest, checker and exchange. All 70 catalog members match the earlier approved catalog, with identical bytes and modes. All 11 executable archive members match the new private `site-source` files. No application code was imported during this inspection.

The new exchange journal is prepared at `closing`, count zero, with no terminal proof. No Controller journal, installer transaction, service hold, continuity record or sealed host images exist in the new bundle. The enrolled attempt directory contains only `attempt.lock`. These are private-artifact observations, not fresh live route/guard/service verification.

Machine-readable evidence: `/tmp/jsh-s4-third-successor-review/private-bundle-evidence.json`. Reader: `/tmp/jsh-s4-third-successor-review/check_private_bundle.py`.

## One additional disposable test

The earlier composed test covered an ordinary predecessor and its first inherited-guard successor. One additional scenario was justified to exercise the next generation's real predecessor loading and admission.

```text
/usr/bin/python3 -I -B /tmp/jsh-s4-third-successor-review/test_third_generation.py
```

**1 test passed in 20.464 seconds.** It performs real first and second Controller CLI install/rollback against synthetic disposable files. The third then names the second as its immediate predecessor, validates that predecessor's own inherited handoff, and reaches real durable CLOSING before package exchange. The same guard directory and marker remain parked; third state/lock identities are fresh; every file in both older private bundles remains unchanged. Only the test's third process is killed at the deliberate CLOSING cut; its disposable hold stays contained under `/tmp`.

Evidence: `/tmp/jsh-s4-third-successor-review/run.embx5u4f`. Its scenario contains `third-generation-result.json`, actual journals, subprocess results, and checkpoint evidence. The exact Controller/gate pins remain `927063a9797c121a8c6e4b73011a79ea2874d72427c64387e969355503b092eb` and `7df4121796ce400461be9b4329984bc6f1ced83858588d3a63d4e5258d286537`. Host, service, listener and alternate-exchange observations are explicitly substituted. This adds nested predecessor coverage; it does not replace native acceptance.

## Minimal next inputs

Reuse the same approved source/candidate catalog, original protected witness, original physical guard, and exact route-pair scope. Keep -01 and -02 history untouched. Use the new bundle's fresh hold ID, locks, unused attempt enrollment, checker, observer identity and exchange generation/policy/intent; the normal release still has to revalidate live source, guard, leases and protected evidence at its gates.

Freeform intake is a separate authorization/evidence track. It needs its own independently reviewed current workbook/table/header projection, genuinely fresh Company identity, exact company/source fact, and a fresh versioned intake claim. Do not carry Atomic Machines' uncertain append claim or request identity into it, and do not use a fresh Company identity to repair that old uncertainty. The separately reported external-writer race is not decided by this private release inspection. No prospective Freeform row, event, write, scrape or pilot acceptance is established here.

All writes by this reviewer were confined to `/tmp/jsh-s4-third-successor-review`. No network or production interpreter/cwd, database, application import, service/process inspection, live guard/checkout access, lock acquisition, or release invocation was used. Locks and release tools ran only in the disposable fixture. The private native artifacts were read as files only.
