# Milestone 5 employer authority improvement

**The exact saved public specimen returned `PUBLIC_EVIDENCE_ACCEPTED` for the frozen candidate. Independent QA accepted the exact repaired pin for this saved offline specimen.** Forterra returned 65 exact postings across four listing pages and PDW returned 33 across two. The offline validator matched both complete detail sets with stable listing membership and full descriptions. The result carries `release_qualification: false`. The existing synthetic capture contract retains its `FIXTURE_PASS` disposition.

## Frozen contract and scoped changes

Staged in the private tree `/tmp/jsh-m5-live-authority-repair.jMbESo7E`. The contract was frozen before implementation at `68dcc8d9e06b5052b7a2f8064598f1223fe3ecd9c0bc22b360b2182f58f31553`. The candidate application package, provider adapters and release code are byte-for-byte unchanged from the previous exact fixture baseline.

- Forterra authority is limited to the exact company careers URL and `forterra` board. The validator requires the independently reviewed script hash together with the unique active named mount, in execution order. It checks the separately reviewed goTenna pair and excludes it as Forterra authority. A replaced, inert, reordered or additional conflicting declaration holds. The validator reads script bytes as inert evidence. It does not execute employer JavaScript or assert general browser behavior.
- PDW authority is limited to the exact company careers URL, the canonical board anchor, the exact alias anchor and the separately captured HTTP 308. It accepts the literal same-host `/pdwcareers/jobs` redirect target. The observed header repeats that exact target in one optional `Refresh` directive. A different target, status, hop, origin, extra Location, contradictory refresh or missing link holds. The validator performs no redirect following.
- Public authority decisions use a distinct input schema and receipt disposition. The exact known Company rows, source/configuration/dependency digests, capture file hash, employer witnesses and unchanged provider replay are bound together. Only evidence hashes and approved identifiers leave the private working corpus. The raw captures have stayed private and are excluded from the handoff payload.

[External contract](/tmp/jsh-m5-live-authority-repair.jMbESo7E/checkpoints/AUTHORITY_CONTRACT.md) · [Implementation checkpoint](/tmp/jsh-m5-live-authority-repair.jMbESo7E/checkpoints/IMPLEMENTATION.md)

## Exact versions and output

| Item | SHA-256 |
| --- | --- |
| Candidate application package | `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad` |
| Candidate configuration | `fafe5191319d13d4c329a6a9e1913460f07b24ad46dbd398c43a0ad430afa1d8` |
| Candidate dependency policy | `d633e308a88f1056ea979f2024a9a0b92c76f3fb6c0030130a79abeb21156d5d` |
| `dev/pre_release_validation/validate_candidate.py` | `59095d9b12be010bb24b29d705d5756edc30c358bd82013e9522723cefa90682` |
| `dev/pre_release_validation/rippling_public_authority.py` | `5297cf4832bb287c91fac89f498729ec6c2d1c1dff9dc23008a6949568ac3e57` |
| `tests/test_live_employer_authority.py` | `247edadbf630fd736f8ee789b3e5689e53eccad1f3ea18ca7dd96fb79c9b756a` |
| Unchanged listing/detail and fixture authority parser | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| Private original public evidence manifest | `4b724ffead928ea1678e594eddfb4d934ee4139279e661e783ed7aa3397e55ce` |
| Private derived replay input | `75feafd84ced0cbeb8ce855eedbcb02ce8fe3582faeb034c10a924d34e992480` |
| Public-evidence receipt | `27905b63dfd391e5d3190ace7d4fee74d476b421ed29a4e866c8483d6b50706a` |
| Substituted-target hold receipt | `f9af39a09a20a1b53451b41a8e511674bd79178798e2aa0546b99108027d53f6` |

[Code and test pin manifest](/tmp/jsh-m5-live-authority-repair.jMbESo7E/checkpoints/QA_SHA256SUMS) · [Evidence receipt with hashes](/tmp/jsh-m5-live-authority-repair.jMbESo7E/checkpoints/public-evidence.receipt.json) · [Hold receipt](/tmp/jsh-m5-live-authority-repair.jMbESo7E/checkpoints/public-hold.receipt.json)

## Tests and reproduction

The previous synthetic-only unmodified baseline passed 26 tests. The extended scoped suite below exited 0 with 167 passed, including a positive exact private-specimen replay, an integrated hold with a substituted PDW redirect, and direct forbidden authority cases. The separate command-line replays emitted `PUBLIC_EVIDENCE_ACCEPTED`, exit 0, for the original corpus and `HOLD`, exit 1, with a substituted PDW target. With the private corpus unset, the targeted run exited 0 with 68 passed and 16 private-capture cases skipped. The documented earlier two unrelated Company-event baseline failures were outside these selections.

```bash
cd /tmp/jsh-m5-live-authority-repair.jMbESo7E
sha256sum -c checkpoints/CONTRACT_SHA256SUMS
sha256sum -c checkpoints/QA_SHA256SUMS
qa_tmp=$(mktemp -d /tmp/jsh-m5-authority-pytest.XXXXXXXX)
JSH_PRIVATE_PUBLIC_CAPTURE_DIR=/tmp/jsh-m5-current-public-validation.NyyH0uPo \
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o 'pythonpath=src . dev/pre_release_validation' --basetemp "$qa_tmp/pytest" -q --tb=short \
  tests/test_live_employer_authority.py tests/test_pre_release_candidate_validation.py \
  tests/test_shared_boards.py tests/test_rippling_locations.py tests/test_source_routing_recovery.py \
  tests/test_inventory_source_validation.py tests/test_integration_release.py \
  tests/test_release_admission_bootstrap.py tests/test_release_controller.py
```

Set the evidence location only on a host with access to the private corpus. Without it, the original-capture cases skip and synthetic negative cases remain available. Keep the pytest scratch tree private because the replay input includes saved public raw bytes. [Scoped test log](/tmp/jsh-m5-live-authority-repair.jMbESo7E/checkpoints/final-scoped-tests.log)

## Release owner handoff

Initial independent QA reproduced two CSS-comment hiding bypasses on the original pin. The repaired parser rejects both and the supplemental regressions passed. Independent QA accepted the exact repaired pin after 120 tests and 86 separate input probes passed. A disposable invocation of the existing release gate refused the exact `PUBLIC_EVIDENCE_ACCEPTED` and `FIXTURE_PASS` receipt digests. The QA report hash is `71a29463384a6a7169350d616ed93378716481eb64cef0f3407c84dce76b6bf7`. [Initial QA](/tmp/jsh-m5-validation-independent.pKaySTku/PUBLIC_AUTHORITY_INITIAL_QA.md) · [Final independent QA](/tmp/jsh-m5-validation-independent.pKaySTku/PUBLIC_AUTHORITY_FINAL_QA.md). When the actual generated Sprint 5 repair candidate is available, take a separately authorized fresh specimen and pin the exact candidate and Company revision. The Forterra policy intentionally holds if the reviewed script bytes or mount shape change. This lane issued no new public requests and made no changes to production, queues, Sheets, Jetson or the release installer.
