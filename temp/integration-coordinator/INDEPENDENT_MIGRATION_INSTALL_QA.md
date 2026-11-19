# Independent migration installation matrix — 2026-11-19

## Verdict: ACCEPT FOR SOURCE INSTALLATION ONLY

The drifted package was superseded by a resealed overlay that incorporates the
current protected `runner.py` and adds only the two accepted legacy-migration
CLI branches plus its `Path` import. The sealed source overlay and repaired
guarded installer pass the checks below. This is not permission or evidence
for a legacy-plan migration, Google request/write, scrape, service restart,
queue release, lock deletion, database change, or Jetson action. No
installation or live action was performed for this review.

## Fresh matrix

| Check | Evidence | Result |
| --- | --- | --- |
| Candidate seal | `sha256sum -c SHA256SUMS`: all 13 entries `OK`; manifest SHA-256 `a365c93822c6f3ca6419b7aea40b18626f86f7cfbe15c4317d45c1aceda25ff3`. | PASS |
| Protected baseline | From `/home/chris/job-search-helper_old`, `sha256sum -c PROTECTED_BASELINE_SHA256SUMS`: all 10 entries `OK`; manifest SHA-256 `d6c0574719792ea606a5a13dcfe945c4f7afad7b92cd930937ae32ac36de7a9f`. | PASS |
| New targets absent | Protected checkout lacks `exact_legacy_migration.py`, `exact_legacy_migration_runner.py`, and `test_exact_legacy_migration.py` at the three declared paths. | PASS |
| Package scope | Candidate holds exactly 13 sealed Python payload files plus README and the two manifests; no state, credential, lock, database, or runtime artifact; no payload merge marker. | PASS |
| Reconciled runner semantic delta | Current protected runner hash is `275e1490...`; candidate runner is `3e415524...`. The complete diff is only the `Path` import, help for `legacy-migration-preview`/`legacy-migration-adopt`, and those two contained command branches. Existing terminal Company-event bridge/start/sync behavior is unchanged. | PASS |
| Reconstructed overlay | `/tmp/exact-reconciled-overlay-rph7By` matches all 13 resealed payload hashes byte-for-byte. | PASS |
| Focused/adjacent suite | Fresh from that reconciled overlay with `-W error`: documented 14-module unittest matrix **248/248**, 21.866 s. | PASS |
| Activity precondition | Read-only snapshot found no running Job Search Helper scraper, publisher/sync, reviewer, or coordinator process. | PASS at snapshot |
| Lock precondition | Empty `.integration-install.lock` exists. Other PID-marker lock files identify non-running PIDs. They were not deleted, opened for locking, or changed. | CONDITIONAL: installer must acquire the advisory lock immediately before copying |
| Installer identity | `/tmp/install_exact_legacy_migration.py` SHA-256 is `0aa4fc62bb77b937585d39f186eb8af40e193a2286b0df98b5894d7000e91852`. This supersedes the rejected `49a7...` revision. | REVIEWED |
| Installer scope and normal lock handling | It requires `set(after) == set(before) | NEW`, exactly 13/10 entries, checks every package and protected hash, requires the three new targets absent, and uses nonblocking exclusive `flock` on existing `.integration-install.lock`. It changes only manifest entries and rolls back only entries it changed. | PASS |
| Installer rollback receipt durability | The repaired revision fsyncs every copied backup file, verifies its hash, fsyncs the created backup-directory entry and directory tree, then writes `BACKUP_DURABLE`. `durable_json()` fsyncs the temporary file and receipt parent after `os.replace`. Target replacement and rollback paths fsync their parent directories; new-target removal is likewise parent-fsynced and rollback hashes are rechecked. | PASS |
| Disposable installation | The installer produced receipt `/tmp/jsh-exact-legacy-migration-20261119T203743Z-x0iy93ju/manifest.json` with `INSTALLED_HASH_VERIFIED`; its candidate/baseline seals match this resealed revision and all 13 fake-target hashes reverify `OK`. | PASS |

## Installation-time requirements

Immediately before execution, repeat the 13/10/three-absence checks and confirm
there is no active scraper, publisher, reviewer, or coordinator. The installer
must acquire (never delete or bypass) the existing advisory install lock, retain
the generated rollback manifest outside job data, copy only the sealed paths,
verify installed hashes, and run the accepted offline post-install checks. On a
failure it may restore only the recorded replaced files and remove only recorded
new files. It must not access Google, start scraping, alter queue or database
state, delete locks, or change Jetson state.

## Remaining deployment gate

The protected state must be rechecked immediately before execution: a changed
package/baseline or present new target stops the installation. Live legacy
migration/publication remains separately approval-gated and was not exercised.
