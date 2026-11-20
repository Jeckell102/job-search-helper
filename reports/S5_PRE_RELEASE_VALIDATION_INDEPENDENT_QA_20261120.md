# Independent QA recheck — Milestone 5 candidate validation

**Verdict: ACCEPTED for the exact isolated Forterra and PDW fixture scope.** The validator's fixture evidence does not meet the live qualification or release gate. The validator was reviewed against the existing correct-route candidate. A resulting candidate from the full Sprint 5 repair chain still requires its own validation.

| Reviewed file or input | SHA-256 |
| --- | --- |
| `dev/pre_release_validation/rippling_capture.py` | `46a0d7372a6e73447e59fb2f6a9e3b3e25839ec48a82a3293c98b5874d87db0d` |
| `dev/pre_release_validation/validate_candidate.py` | `47c734bc718dfbed60e2d15044e72f061715e2a05b7f47fa3f1f3f2089c44dc0` |
| `tests/test_pre_release_candidate_validation.py` | `5e3883a738f037c25c97b30596871d5b487fa2ddf8248c3ba0e5ec2453d5020c` |
| Candidate package source | `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad` |
| Candidate fixture configuration | `fafe5191319d13d4c329a6a9e1913460f07b24ad46dbd398c43a0ad430afa1d8` |
| Candidate dependency policy | `d633e308a88f1056ea979f2024a9a0b92c76f3fb6c0030130a79abeb21156d5d` |
| Pinned release-admission measurement tool | `c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f` |

### Commands and observed results

From `/tmp/jsh-m5-pre-release-validation.OHy7TsMZ`:

```sh
sha256sum -c checkpoints/INTEGRATED_SHA256SUMS
qa_tmp=$(mktemp -d /tmp/jsh-m5-qa-recheck.XXXXXXXX)
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider --basetemp "$qa_tmp/pytest" -o pythonpath=src -q tests/test_pre_release_candidate_validation.py tests/test_shared_boards.py tests/test_rippling_locations.py tests/test_source_routing_recovery.py tests/test_inventory_source_validation.py
```

Both exited 0. All three integrated hashes matched. The combined run passed 62 tests in 9.06 seconds (26 dedicated and 36 existing provider and routing tests). The fixture receipt exercised the ordinary `ats.fetch_inventory` dispatcher. The suite separately exercised the same frozen candidate in the normal `Engine.start_cycle(company_ids=[...])` and `Engine.resume` company-only flow with fixture stores and transport. Forterra returned 62 fixture postings over 20/20/20/2 rows per listing read. PDW returned one fixture posting. Stable identities and the full projected descriptions matched on the synthetic captures. The bounded reconciliation and missing/foreign detail or page cases were included.

From `/tmp/jsh-m5-validation-independent.pKaySTku`:

```sh
/usr/bin/timeout 40 /home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_snapshot_recheck.py
/home/chris/job-search-helper_old/.venv/bin/python -I -B ./probe_release_gate.py
```

Both exited 0. The race probe proved that the original-to-detached copy rejects source substitution during the copy and that short-lived mutations to either the original candidate or detached candidate during imports are unable to change the independently pinned Python bytes executed. Detached configuration and dependency measurements matched the pin in both successful runs. The release gate probe supplied the exact digest of the actual `FIXTURE_PASS` receipt to a disposable release and got the expected refusal with no completed release receipt.

The updated original evidence probes are under `/tmp/jsh-m5-validation-independent.pKaySTku/recheck-evidence.7wUBt7Y3`. Each exited 0 after running its intended assertions or emitting the inspected dispositions. Omitted or relabeled PDW and a renamed Forterra all returned `HOLD`, even though the source revision alone was unchanged by relabeling. A deliberately truncated candidate description held both companies. A stale zero payload in template or noscript, filtered or one-read zero, inert description, overridden employer iframe, wholly inert iframe and lookalike source authority all returned `HOLD`. The positive explicit-zero case remains covered by the integrated suite.

Prior reproducible defects and their original pins are preserved in [INITIAL_QA.md](/tmp/jsh-m5-validation-independent.pKaySTku/INITIAL_QA.md). No live provider, workbook, production state, service, queue, or shared implementation edits were used in QA.
