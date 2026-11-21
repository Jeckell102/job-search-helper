# Sprint 5 ordinary raw-capture custody handoff

**Independent QA accepted the exact isolated custody component.** The component reserves one exact ordinary dispatch, buffers one bounded direct response, seals the original bytes and exact manifest only for the matching final inventory, and reopens it only for the exact PREPARED marker and paired inventory. The scoped tests use disposable synthetic bytes.

## Integration interface

- `open_custody(root_path, root_fd)` takes a launcher-enrolled descriptor for the private evidence root. It duplicates the descriptor, checks every component of the named root without following symlinks, and uses descriptor-relative operations for its files. Directories require owner-only `0700`, and files require owner-only `0600`, a regular inode and a single link.
- `custody.reserve(armed, dispatch_sha256, *, source_manifest_sha256, capture_policy_sha256)` derives the dispatch digest from a copied exact ARMED snapshot. It fsyncs the reservation in a unique private staging directory, atomically publishes with no replacement at the dispatch key, fsyncs the root, and yields one context-managed ticket. An existing dispatch name holds subsequent reservation attempts. A cut before atomic publication grants no ticket. A cut after publication leaves the exact dispatch reserved.
- The separately owned adapter callback calls `ticket.offer(typed_observation, request_url=…, response_url=…, status=…, body=…)` only for the approved direct response. It holds at most one immutable body of at most 6 MiB. The callback receives the already validated typed response and checks source, exact requested/final URL, integer HTTP 200 and byte digest. Invalid or duplicate offers leave no selectable body. This component takes the upstream measured callback provenance as a precondition.
- Root computes the ordinary F6 payload once and passes it with the returned `Inventory` to `ticket.seal(inventory, payload)` before writer-side preparation. A final result with no typed mismatch discards the body. A typed claim with conflicting status, jobs, access, temporary failure, verified zero, browser gaps or source holds. A matching result publishes two fsynced files under one atomic no-replace directory rename, fsyncs the slot and verifies exact readback. The return is a private manifest digest. Neither `Inventory` nor the payload gains raw fields.
- After `read_prepared_inventory` has established the exact current State/Inbox pair, root calls `custody.read_prepared(marker, saved_payload, blocked=…, source_manifest_sha256=…, capture_policy_sha256=…)`. It checks the entire closed PREPARED marker, dispatch, unchanged payload digest, exact observation, generation, independently supplied source and policy pins, raw size and SHA-256. Root, slot, capture folder, reservation, manifest and body identities are rechecked. Persistent file stamps detect replacement or restoration. Exact reuse reads the same immutable result and grants no further callback.

The deployment host must provide Linux `renameat2(RENAME_NOREPLACE)` and working directory fsync for this prototype. Incomplete private staging remains a hold for the owning retention policy. The component performs no recovery writes to State or Inbox, acquisition, public verification, networking or release. File permissions and hashes protect a caller-owned channel; they do not authenticate records against a hostile process controlling the same UID. [Frozen interface](/tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK/checkpoints/INTERFACE.md) · [Custody design](/tmp/jsh-s5-ordinary-live-capture-design.md)

## Exact files and test results

Overlay `/tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK`.

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/ordinary_raw_capture.py` | `b038adffbdf2bac9811806a8aaecf2cb816cebeb2bcce73037447670503ee571` |
| `tests/test_ordinary_raw_capture.py` | `cde3a01936dafb9c9c962e08c74125c0ad7f9933abee81ee816f8f4a1a051b0e` |
| `checkpoints/INTERFACE.md` | `290e7e1d9fefeb63e90a7d04795607d333f53125e8879f3c8d5d2a1977cee8c4` |
| Unchanged pending marker dependency | `efda2b34c9550c56bb0e974194a9ce9d82d1db29343ef97c29b5697ff8c20bdd` |
| Unchanged typed response dependency | `92a1e43194f02201089e81f5a891fb368f44865f50aeab351d8281fdd0290a20` |

```bash
cd /tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK
sha256sum -c checkpoints/QA_SHA256SUMS
worker=/tmp/jsh-s5-ordinary-worker.akf3gPsM
qa_tmp=$(mktemp -d /tmp/jsh-s5-capture-custody-tests.XXXXXXXX)
/home/chris/job-search-helper_old/.venv/bin/python -I -B -m pytest -p no:cacheprovider \
  -o "pythonpath=$worker/src $worker $worker/tests" --basetemp "$qa_tmp/pytest" -q --tb=short \
  tests/test_ordinary_raw_capture.py "$worker/tests/test_ordinary_verification_pending.py" \
  "$worker/tests/test_s5_ordinary_worker_handoff.py"
```

54 focused and 88 combined tests passed. The combined command includes the worker checkout root so its existing launcher fixtures import the bootstrap. Focused checks cover process exits before and after publication, concurrent reservations and offers, empty-destination no-replace, exact readback and reuse, invalid or oversized body, final selection precedence, generation/runtime/source and payload changes, incomplete captures, file and ancestor aliases, physical directory replacement, in-place restoration and no raw fields in F6. [Focused log](/tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK/checkpoints/review-tests.log) · [Combined log](/tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK/checkpoints/combined-root-tests.log) · [Hash manifest](/tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK/checkpoints/QA_SHA256SUMS)

The coordinator owns setup and final selection in LocalPipeline, and the provider lane owns the direct observation hook. The caller must enforce PREPARED/Inbox custody before export, launcher slot enrollment, raw-data retention and backup exclusions. This lane made no changes to runner, LocalPipeline, provider adapters, production or external systems.

## Independent QA

The verifier matched all source and test pins, reran the 54 focused tests, and passed 59 independent checks. The checks included actual process exits around both no-replace renames, exits between rename and parent fsync, exact six MiB acceptance and oversize refusal, persistent inode and content stamp replacement, independent source and PREPARED pins, and concurrent ticket/offer behavior. This acceptance covers process restart on the disposable filesystem. The real callback and application integration, host retention policy, and power-loss rehearsal remain separate. The QA report SHA-256 is `b217e9ebc734b6c85a998520c9adb4dbf7abcea3fc4083d74d1eca7a08540470`. [Independent QA](/tmp/jsh-m5-validation-independent.pKaySTku/raw-capture-custody-qa.Zn6hoSyX/RAW_CAPTURE_CUSTODY_FINAL_QA.md)
