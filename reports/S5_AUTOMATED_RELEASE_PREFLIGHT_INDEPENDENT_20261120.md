# Independent acceptance — S5 automated pre-install gate — 2026-11-20

**ACCEPT the exact staged admission slice.** No blocking defect was found within the normal application contract. This verdict covers qualification receipt admission, complete candidate projection, install sequencing, completed-receipt readback and compatibility. It does not establish a live-qualified candidate, validate an evidence producer, enable automation or deploy source.

Reviewed tree: `/tmp/jsh-s5-automated-release-preflight.6SuVCPap`. Root retained exclusive ownership of application changes. This reviewer added only `/tmp/test_jsh_s5_preinstall_independent.py` and this report; no source, live application, job data or external system was changed.

## Evidence

- `release_controller.py:38–61` validates the owner-pinned qualification before entering the installer. The separately retained `release_and_schedule` API at 28–35 preserves existing reviewed callers.
- `release_qualification.py:38–58` binds the physical owner, exact approved receipt bytes, complete release manifest, candidate validation digest, evidence class and explicit qualification. Offline, fixture, public-only, missing, extra and changed evidence cannot enter the installer through this API. Root identity and receipt identity are reread.
- The preinstall callback remeasures the complete candidate source/configuration and reconstructs the resulting installed source/configuration from the listed changes. `integration_release.py:117–132` rejects an unlisted source/configuration addition, including a root configuration change that the release cannot install.
- `integration_release.py:319–345` runs the second qualification check under the existing scraper lease and before rollback backup or prepared journal writes. The test demonstrates competing lease acquisition fails at that point and withdrawal/receipt replacement holds with no release artifacts.
- Installed-source/configuration/dependency measurement, verification callback, receipt pin and guarded rollback remain in place. Failure after installation keeps the nonterminal journal and schedules no retry. The accepted positive fixture measures the actual disposable installed candidate before returning its exact verification evidence.
- Completed receipt readback (`integration_release.py:394–418`) checks Company, source revision, failed request, release binding, validation evidence and activation time. New completed journals also pin the entire receipt. Qualified replay requires that pin; compatible legacy manual replay remains available. Crash after activation reuses one exact release receipt and retry attempt without repeating installed verification.

Independent executions used Python 3.11.18 and the staged source via `PYTHONPATH=src:tests`, `PYTHONDONTWRITEBYTECODE=1`, and disabled pytest cache. All application writes were to disposable test fixtures.

```text
python -m pytest -q -p no:cacheprovider tests/test_release_qualification.py tests/test_release_controller.py tests/test_integration_release.py tests/test_repair_retry.py
76 passed in 2.92s

python -m pytest -q -p no:cacheprovider /tmp/test_jsh_s5_preinstall_independent.py
10 passed in 0.24s
```

The ten additional probes cover missing schema/evidence class/eligibility/producer hash/capture hash; qualified but unlisted integration configuration and root storage configuration; candidate configuration drift after approval; extra nested offline evidence; and a changed qualification receipt during admission. Positive activation/replay, offline pre-installer rejection, under-lease withdrawal, post-install failure/rollback and existing manual behavior are exercised by the independently rerun maintained tests.

## Exact reviewed files

Hashes were identical before and after the independent executions.

| File | SHA-256 |
| --- | --- |
| `src/job_search_helper/release_qualification.py` | `886e6ac97e9b4979fdde4cb9f01630a8896edb569418f19bdfd76c7190f323d5` |
| `src/job_search_helper/release_controller.py` | `a867ec859a1177711e6647e1ced164dcaff61553277c703a032b1cc3d5354dd0` |
| `src/job_search_helper/integration_release.py` | `69a4261f117a61d41a3a3cb023ca7c73098b1c0ee0a6c98b2fefb525d7ab21df` |
| `tests/test_release_qualification.py` | `11d7bcd0964bc5b1e90fa90f97faa7867c7130793f3b54d16f2ed5dda3fdd9ee` |

## Evidence boundary

The qualification reader authenticates a separately approved receipt; it does not independently collect live evidence or prove that its producer deserves approval. The positive qualification in these tests is deliberately synthetic and proves only the gate's behavior. A future production composition must provision the owner identity and exact approved receipt digest from the reviewed qualification authority, preserve original live/offline provenance through that producer, and bind the installed verification callback to the accepted candidate. It must not let the repair candidate choose its own authority or route automatic releases through the manual API. No current offline receipt is upgraded by this verdict. No check was flagged.
