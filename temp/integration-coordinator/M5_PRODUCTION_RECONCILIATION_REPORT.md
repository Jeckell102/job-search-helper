# Milestone 5 protected-source reconciliation report

Status: source-level reconciliation accepted for continued review; not merged,
deployed, activated, or used for a live scrape.

Updated: 2026-11-19.

## Boundary

The protected checkout at `/home/chris/job-search-helper_old` remained
read-only.  Reconciliation occurred only in
`/tmp/job-search-helper-production-reconciliation`, using a sanitized copy of
source and tests.  The MuleLab coordinator was reconciled in that same
temporary tree from source and tests only; no task database, runtime history,
credentials, locks, Company records, jobs, or Google Sheets data were copied.

The resulting candidate is deliberately not a deployable claim.  It proves
that the M5 contracts can coexist with the current protected source without
replacing its newer scraper, review-preservation, retry, performance, or sync
behavior.

## Reconciled contracts

- One completed, independently reviewed release receipt can create one exact
  repaired-Company retry, bound to the failed request, current Company source
  revision, release version, activation time, and retry attempt.
- Company-event and repair-retry provenance are mutually exclusive.  A stale
  source is rejected at admission and checked again before storage.
- The normal scraper lock is the release lock.  A nonterminal durable release
  journal blocks the actual run and interrupted-cycle recovery boundaries.
- Release input, output, full source tree, configuration tree, dependency
  digest, and validation receipt are pinned.  Rollback refuses unrelated
  target drift.
- Publication receipts bind the exact request, Company, source revision,
  release, and record fingerprints.  A returned write is not treated as saved
  until fresh exact readback confirms it.
- A protected review-field preflight rejection may replace a receipt only
  before the first published slice.  If any slice was already acknowledged,
  the exact plan and receipt are retained for reconciliation instead of
  silently replanning a repaired attempt.
- Repaired outcomes carry attempt, failed-request, and release identity.  The
  coordinator records one successor lineage, prevents late original failures
  from reopening repair, rejects competing successors, and creates a new
  repair key for a genuinely failed repaired attempt.

## Verification

All commands used fixture or temporary state only.

- Reconciled M5/request/runner selection: 72 checks passed with resource
  warnings treated as errors.
- Current protected durable-inbox behavior, excluding its unrelated real
  startup-preflight CLI fixture: 11 checks passed.
- Repaired publication/restart/storage selection: 9 checks passed.
- Current protected SQLite migration selection: 46 checks passed.
- Disposable release-versus-scraper race: passed.  While activation held the
  normal lock at its durable prepared boundary, scraper admission was refused;
  after activation completed, the lock was available again.
- Full reconciled MuleLab coordinator suite: 398 checks passed with resource
  warnings treated as errors.
- Scoped compilation and diff whitespace checks passed.

An older feature-branch aggregate of 178 scraper tests is not used as
production acceptance evidence: when pointed at the newer protected source it
retains obsolete expectations for startup preflight, elapsed summary output,
and run-scoped sync timing.  The authoritative current-source selections above
were run instead.  Those obsolete expectations must not be restored because
doing so would replace newer protected behavior.

## Exact reconciled source hashes

The temporary candidate's principal files are pinned below for owner review:

```text
engine.py                  2b7c39ec0a117e9f1d71ce13858e9bcad0af8c9d61ca54a5604e5f76b5d01f0c
inbox.py                   482895c72900ddcdfda1089090a6277af494bea7941b1f1289ac8f2ae5cb23cd
integration_release.py     1a15c158f699193e675c429f1e8e96e5b43ad83040e7e161ccb45d06773ad4d8
local_pipeline.py          6f47c8f6a88908e8843c50a5e5639300e4b862a415a7fc72000d391cd54da4f8
outcomes.py                f8824da599f27646421b9c480da920f706ca1653507fd65b82d6ff49aea0e939
publication_receipts.py    68b029585948b9dcf99c6277f2fe5334eed38642f5679e072fd5375d93384ff2
release_controller.py      cb916ba55634051420f0998ab6dcc76455fb184e4f6901c8074ccf29eee0031d
repair_retry.py            c6169e17fce73706f3d697c933d3dfb17900fb455a1e00df364c0416eea3d1b2
runner.py                  178600cf76b5ba223780e563b37d05aa3e902c059890efc43776df99485d74fa
scan_request.py            f47e0746e4f5528611b55af6e54080cfb5b4b77608984ce4dad54d26b3669c30
scrape_outcome_producer.py 6f9d38029c23d32062f11efe448c948f38ff2bb6f9deed6cd4f2e8164bf0e393
coordinator.py             bc276d79b23c7b39b983656a0b6b50b3a13ee1d1396c6462049e1ed7e9801664
coordinator_store.py       3c2f930997198b750bdf2d529231e78583b9b6f18a19de7fff6b89616dd8a970
```

The `publication_receipts.py` and `local_pipeline.py` hashes above include the
reconciliation-only protected-review safety repair described in this report.
They intentionally differ from the older isolated feature source.

## Remaining M5 gates

1. Independent review of this exact reconciled candidate and evidence.
2. Owner-reviewed integration into a frozen protected baseline, followed by
   rerunning the current production-owned suites on the exact installed set.
3. Guarded activation and live one-Company release-to-retry proof, including
   confirmed Google Sheets publication and managed FIRST PASS start.
4. A scoped sanitized GitHub backup of accepted source, tests, and evidence;
   never publish the private protected snapshot or runtime data.

