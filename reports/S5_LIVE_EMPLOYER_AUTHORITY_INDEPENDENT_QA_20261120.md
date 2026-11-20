# Independent QA recheck of public employer authority

**Accepted for offline replay of the saved Forterra and PDW public specimen.** The final implementation evaluated the original employer responses, PDW alias response, listings, details, and rereads using the exact frozen candidate. This verdict does not qualify a release or replace review of a future generated repair candidate.

| Reviewed input or artifact | SHA-256 |
| --- | --- |
| Authority contract | `68dcc8d9e06b5052b7a2f8064598f1223fe3ecd9c0bc22b360b2182f58f31553` |
| Final five-file QA manifest | `c0bab7bb8497df6007e32b1fa53909b5580675b20b1829092c2318e24e971c21` |
| Validator | `59095d9b12be010bb24b29d705d5756edc30c358bd82013e9522723cefa90682` |
| Authority evaluator | `5297cf4832bb287c91fac89f498729ec6c2d1c1dff9dc23008a6949568ac3e57` |
| Existing oracle | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| New public authority tests | `247edadbf630fd736f8ee789b3e5689e53eccad1f3ea18ca7dd96fb79c9b756a` |
| Unchanged synthetic fixture tests | `5e3883a738f037c25c97b30596871d5b487fa2ddf8248c3ba0e5ec2453d5020c` |
| Existing candidate package source | `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad` |
| Preserved private capture manifest | `4b724ffead928ea1678e594eddfb4d934ee4139279e661e783ed7aa3397e55ce` |

The original capture replay returned `PUBLIC_EVIDENCE_ACCEPTED` and `release_qualification=false`. It confirmed the exact distinct Forterra/goTenna widget identities and the single PDW alias normalization, alongside 65 and 33 fully matched postings respectively. Witness checks retained exact hashes for employer response headers and bodies and the PDW alias headers. The synthetic original returned `FIXTURE_PASS` for 62 and 1 postings. Labeling fixture inputs as public returned `HOLD`. Both exact successful receipt digests were refused by the existing disposable release gate with no completed receipt.

All five final implementation hashes matched. The scoped pytest run passed 120 tests in 13.37 seconds. Three independent probe runs exited 0. The main battery had 67 input scenarios, including original positive evidence, receipt privacy, reordered or changed widget evidence, inactive mounts and scripts, malformed or ambiguous HTTP blocks, and location substitutions. The seven redirect-refresh cases distinguished an exact or absent redundant directive from divergent, duplicate, absolute, delayed, and folded directives. The twelve hidden-context cases held, including the two CSS-comment cases found on the initial pin, escaped style forms, and raw-text or closed/fallback ancestors. The [initial review and hold](/tmp/jsh-m5-validation-independent.pKaySTku/PUBLIC_AUTHORITY_INITIAL_QA.md) are preserved.

### Commands and evidence

From `/tmp/jsh-m5-live-authority-repair.jMbESo7E`, verify the final hashes and run the isolated suite:

```sh
sha256sum -c checkpoints/QA_SHA256SUMS
qa_tests=$(mktemp -d /tmp/jsh-m5-public-authority-qa-final.XXXXXXXX)
JSH_PRIVATE_PUBLIC_CAPTURE_DIR=/tmp/jsh-m5-current-public-validation.NyyH0uPo \
  /home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  --basetemp "$qa_tests/pytest" -o 'pythonpath=src dev/pre_release_validation' -q \
  tests/test_live_employer_authority.py tests/test_pre_release_candidate_validation.py \
  tests/test_shared_boards.py tests/test_rippling_locations.py \
  tests/test_source_routing_recovery.py tests/test_inventory_source_validation.py
```

Independent reruns, from this report's directory:

```sh
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_public_authority_patch.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_public_authority_refresh.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_public_authority_hidden.py
```

Logs `authority-recheck-tests.log`, `authority-recheck-main.log`, `authority-recheck-refresh.log`, and `authority-recheck-hidden.log` contain dispositions and summaries. No raw capture files or raw header bodies are copied into this report. The authority checks are static, scoped to the two reviewed shapes, and do not establish browser-rendered visibility. Previously reported response freshness limits still apply. No network, production checkout edits, release, deployment, service, queue, or workbook actions were performed by this QA.
