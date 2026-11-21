# Native retirement preparation script author handoff

Staged only. No native preparation, service action, observer, production write or external call was run. Root owns native ownership/current witness and the independent reviewers own final acceptance.

## Fixed input contract

Use system Python in a fresh native process, outside the live source working directory:

```
/usr/bin/python3 -I -B /tmp/jsh-retirement-preparation/prepare_native.py \
  --current-pin /absolute/private/independently-approved-current-pin.json \
  --current-pin-sha256 <exact-independent-SHA256> \
  --enable-native-preparation
```

The current pin must already exist as a physical, single-link, current-user-owned 0600 file with exact schema/project. The caller supplies its independently approved exact byte digest. There is no API to mint a fresh acceptance pin, clear controls or ignore a mismatch. Without the explicit preparation flag the CLI refuses before reading any input/native state. All native locations, release identity and capsule pins are fixed; no user CLI can select another project, predecessor or payload.

- Payload: `/tmp/jsh-retirement-reviewed-capsule.0v3Nkcga`.
- Catalog: `07914c01013397d8a5e6e2b19902e513e72e3d53cfbf8bdef0883fa82fddba4d`.
- Exact 44 source manifest: `af3a43ce8031f5e5552fd0735ed6a96d6ccdf0d02f740fa829b5e2ca19dfa047`.
- Predecessor: `/home/chris/.local/state/job-search-helper-maintenance/s4-freeform-20261120-01`, exact recorded RELEASED/INSTALLED files pinned in PRIOR_PINS.
- New bundle: `/home/chris/.local/state/job-search-helper-maintenance/s5-owner-retirement-20261121-01`.
- New attempt: same path with `-attempt` suffix.
- Observer: `/run/jsh-s5-owner-retirement-01/observer.sock` (not created by this script).

## Behavior

The script checks all 63 accepted payload members plus the independently pinned catalog before importing maintenance dependencies. It requires fresh absent output directories and verifies the exact previous controller, plan, installer journal, installed continuity, checker, manifest and restored exchange bytes. It reuses `Controller.restoration_terminal()` for the normal maintenance/writer leases, verifies the supplied current witness through the unchanged staged `measure_for_private_review`, reads the actual installed predecessor and restored exchange/guard, verifies all 44 original source endpoints and the three current launch files, then writes only the new private bundle and empty attempt custody.

It creates a new exchange policy/control/generation and calls only `HostExchange.prepare()`. It never calls close/restore/install/rollback or starts/stops a service. The prepared exchange journal is at closing/0 with no terminal proof; all checkout placements remain original. The host-check zip includes the exact accepted modules, updated 44 manifest/source scope, exact host before/after endpoints, correct current-before/new-after launcher hashes, new hold/socket/fence, and supplied current pin.

A fresh predecessor handoff keeps the old historical pin and old installed continuity separate from the exact current successor pin. plan.json binds the new manifest and handoff digest. The existing `enroll_abort` returns an unused-attempt enrollment which is saved verbatim. Before returning PREPARED_NOT_INSTALLED, every pinned predecessor file and the exact current witness are rechecked. The current witness is measured twice; an unresolved legacy backlog, controls or physical-read hold remains a hard error. Prior application records, historical pin and receipts are never rewritten.

Failures leave any partially created private preparation for inspection; reusing an existing bundle/attempt is refused. No automatic cleanup or replay of a partial preparation is attempted. Successful stdout returns manifest/checker/pin/handoff/enrollment/exchange digests for independent capsule QA. The script does not itself approve or activate the capsule.

## Staged evidence and limits

Six focused unittest cases pass in 0.374 seconds with a Python audit hook refusing socket/subprocess/os.system. The positive case verifies real payload checks, immutable checker zip creation and actual fresh HostExchange preparation on disposable paths, no route inode movement, unchanged predecessor fixture files, separate old/current pins, correct manifest/launcher scope and unused attempt. Negatives cover explicit opt-in, wrong digest before owner/output, unresolved backlog before output, foreign/project/drift/mode current-pin failures and duplicate preparation refusal.

The disposable fixture substitutes native Controller ownership/source observations, protected database measurement and final enroll_abort readback. It does not claim a native owner window or real final enrollment. The previously accepted full controller and abort fixtures remain separate evidence. A real native snapshot, authenticated observer, service/process/site proof and independently reviewed final capsule remain required.

Root reported the revised exact settled-Freeform witness is undergoing independent review. This script only pins that supplied capsule and does not independently accept the witness change.

## Frozen author pins

- prepare_native.py: `0203d80925c54b5c7bee2e47b6caa06f44eb667a3501bdbef5b527e2fa607de4`
- test_prepare_native.py: `4348a0d06e1190420d82e8e6c789ff9f524f2ff71ade5e5ed6095b9ee8f80e21`
- RESULT.json: `7007ae8f33e466dc721d1b8e00723fc7c395e2cb0e9cd78af811d8d19c4ab64c`
