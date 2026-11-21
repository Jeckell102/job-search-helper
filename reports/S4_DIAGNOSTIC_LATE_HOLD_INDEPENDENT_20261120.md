# Independent progressed-attempt transcript review

**ACCEPT the captured transcript as a progressed-install hold.** The canonical launch, process, and exit records matched the enrolled diagnostic bundle, exact `controller.py install` command, and the original closed exchange intent for all three path pairs. The original boot/PID/start identity had exited. The six files matched between reads and the attempt directory and lock retained their enrolled identities.

The controller returned **1**, with **empty stdout**. Its entire stderr was:

```text
Site checkpoint held. Protected release evidence could not be verified. [SQLITE_CONTINUITY]
Maintenance stopped. Preserve the bundle for recovery. Host checker refused restored
```

The attempt contained no `refusal.json`. The early-refusal recorder requires the exact `preflight` suffix before it would write that receipt. The staged controller runs `restored` after publication, receipt verification, and unit restoration. Failure there reestablishes the hold and prevents terminal `RELEASED` publication. This review leaves the actual rollback state for the subsequent terminal check. [Early-refusal recorder](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/preinstall_abort.py:253) · [Release and hold recovery](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/controller.py:889)

| Captured evidence | SHA-256 |
| --- | --- |
| `launch.json` | `bce9e1c2694f467b0c043c57b6e4aa8e92f03c6fb7656d1d0fc563482545c7af` |
| `process.json` | `1081beca9f4dc8adaa227362bf02e717289a9d8f41e683c7d2cc77e8d227b491` |
| `exit.json` | `603fb5f410cc6708568be0746d19d18fbf70b9e18a6546b28fcfe57940d93f0d` |
| `stderr` | `185ba9495a81e0958a8feee7370f5d4859a9090c615bbb36041ef44de4d5b8af` |
| Empty `stdout` and `attempt.lock` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## Inputs required after terminal rollback

1. A controller terminal record with phase `RELEASED` and source `ROLLED_BACK`, the pinned before-image and installer receipt, restored prior runtime units, and absent runtime marker and service-hold sentinel. The restoration reader takes the controller, installer, and writer leases and binds the source manifest, controller journal, and installer receipt digests into its release record. [Controller terminal reader](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/controller.py:980)
2. A private mode-0600 canonical selection with independently supplied SHA-256, schema `sprint-4-pre-pilot-rollback-selection-v1`, and `pilot` set to null. Bind the diagnostic bundle's 12 named tool hashes, canonical project and virtual-environment interpreter, current exchange policy path and hash, workbook ID hash, and canonical coordinator database path. The restored bootstrap must match the before-image SHA-256 `c508a85743d54f0840b4906d17bb6780c3c8daad2914d53f58a5006602e70862`. The staged reader checks that the coordinator path is the original protected baseline's declared path and that the interpreter uses `-I -B -X pycache_prefix=/dev/null`. [Selection schema](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/pilot_restore_command.py:55) · [Bound tools and runtime](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/pilot_restore_command.py:122) · [Command flags](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/pilot_restore_command.py:213)
3. Observe under that selection to produce exact canonical approval bytes with schema `sprint-4-pre-pilot-rollback-restoration-v1`. The approval binds the terminal release, acknowledged closed exchange identity, and rollback proof containing the selection SHA-256 and original protected pin SHA-256. Observation requires a fresh protected baseline check, including retained FIRST PASS coverage, and a stable database layout under the writer lease. Restore requires the private approval and independent SHA-256. The restore path rereads the terminal release, exchange, and protected rollback proof under leases, then binds the exact approval digest into the terminal restored exchange record. [Rollback proof and observation](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/pilot_restore_command.py:189) · [Restore approval verification](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/pilot_restoration.py:26) · [Exchange terminal proof](/home/chris/.local/state/job-search-helper-maintenance/s4-atomic-machines-20261120-01-diagnostic/host_exchange.py:439)

This review read the fixed private capture and staged source. It did not query runtime services, open production SQLite files, or inspect the changing rollback journal.
