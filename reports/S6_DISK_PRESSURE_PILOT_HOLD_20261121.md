# Sprint 6 disk pressure and the selected repair pilot

November 21, 2026, 02:47 Eastern. Staged source and offline tests only.

The existing supervisor disabled the broad queue and campaign on low disk
space. The one-Company pilot remained selected, which let the scheduler
claim queued work even while supervision reported `DISK_PRESSURE_HOLD`.
An existing running pilot also remained `RUNNING`. Both failures were
reproduced against the prior backed-up source in a disposable SQLite store.

The fix uses the existing settings and task transaction to hold new queue,
campaign and pilot activation, stop the current pilot at its action
boundary, and preserve its task and inference receipts. Activation checks
the hold before preparing a workspace and again before committing. The
first healthy check clears the disk hold without enabling the queue,
campaign or the paused pilot. The ordinary queue-pause control remains
independent of a selected pilot.

Both previously failing tests passed. The final focused run passed all 79
tests across the selected recipe scheduler, supervision, queue and campaign
transitions, the exact host enrollment and inference accounting. A local
network-denial hook rejected address resolution and network connects.
An already dispatched fixture reply was accounted for and could not apply
an action. The tests used simulated disk usage and never filled a disk.

A separate composed replay exercised the enrolled host with the original
owned Amphenol fixture. A low-space tick cleared the queued pilot. A new
host instance with healthy space retained the same paused task and declined
catch-up without inference. An explicit fixture-only resume was then able
to build the exact reviewed wrapper. It used one simulated reply across the
later restart and zero actual model calls. The durable result is
`DISPOSABLE_ENROLLED_DISK_HOLD_AND_RESTART_PASS` at
`/tmp/jsh-s6-disk-pressure-pilot.20261121/enrolled-disk-hold-result.json`.

| Source or test | SHA-256 |
| --- | --- |
| `coordinator_store.py` | `9f0a84a626fcf910f24233759ff940ff68db81c97b9b0e7096a3d4b0580ea835` |
| `coordinator_supervision.py` | `c06e77fc42170277e462f811b32c2ff9821993c78a1765a83a4c92929eeeb012` |
| `test_owned_recipe_scheduler.py` | `62327ec9c8c4845b6845d662eb6e828a54b3ca2ff1c8dc740d8292a3fba66441` |

Files live in `/tmp/jsh-s6-disk-pressure-pilot.20261121/dev/wrapper-coder/tools/`.
Independent QA accepted the staged scheduler path. Its bound late-reply
probe preserved the reservation during the hold, accounted the reply once
at 560 tokens and allowed zero candidate writes. The existing deployed
service was untouched. The native release and full sequential pilot still
need acceptance. [Independent QA](S6_DISK_PRESSURE_PILOT_INDEPENDENT_20261121.md).
