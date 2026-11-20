# Sprint 4 integrated site continuity independent QA

**ACCEPT the launcher output repair. HOLD protected continuity finalization.** Reviewed the snapshot in /tmp/jsh-s4-site-continuity.OYkaX1Dy with controller /tmp/jsh-s4-continuity-controller.Agp06zzf. The tested launcher SHA-256 is `0a9fb612bafe0f3318d92ccfd4099e8aa1c32df375604d3009dcc9349ce458f2`, protected continuity SHA-256 is `82257a1ac0d76f4ddbf39ed87449aa6e3b9f8a2818e559083ae6734447ee1be0`, and controller SHA-256 is `e4a68b539efe3d8bfb2c19066e495e4be9ee0a6183e34eec4c26f728b5899691`.

## Remaining continuity gap

The initial callback checks the private approval pin and, for a short installer checkpoint, reads the verified receipt. Finalization repeats owner and physical-file observations only. The entrypoint emits success immediately after finalization. These two cases reproduced with actual disposable protected SQLite databases and the real logical and physical witness:

- A short callback read a valid receipt. Before its last check, a same-generation enrollment replaced the record with the normal `pending` state. The already-running short callback still finalized successfully, although a fresh short callback refused the pending receipt.
- A full held enrollment completed the approved logical comparison. The private approval pin then changed during the simulated remaining site checks. Finalization still published a `verified` receipt using the preceding seal. A subsequent short callback correctly rejected the changed pin.

Recheck the exact approval pin at finalization. For short acknowledgements, require the same verified receipt through the final check and refuse its disappearance or replacement. For enrollment, keep the intended pending generation bound through final publication so outer failures or a changed authority cannot promote the receipt. [Initial and final evidence checks](/tmp/jsh-s4-site-continuity.OYkaX1Dy/protected_continuity.py:84) · [Success emission](/tmp/jsh-s4-site-continuity.OYkaX1Dy/host_check_main.py:39) · [Independent reproduction](/tmp/jsh-s4-continuity-independent.cUmE9qzn/test_independent_continuity.py:90)

## Verified behavior

- Usage printed only during import now refuses in published and admitted phases. Command rows without their own descriptions also refuse. The exact baseline and candidate launchers and actual audited help still passed across install and rollback phases in the disposable checkout. [Launcher cases](/tmp/jsh-s4-continuity-independent.cUmE9qzn/test_independent_launcher.py:184)
- A short callback cannot reuse a pending record at entry. A verified receipt passed with the original boot, PID, process start, target and checker seal. Changing any of those pins refused. Protected file drift or lost ownership after logical comparison refused at finalization and preserved a pending record when applicable. [Independent continuity controls](/tmp/jsh-s4-continuity-independent.cUmE9qzn/test_independent_continuity.py:46)
- The controller passed five seconds for nested installer checks and 180 seconds for full checks, including controller enrollment. The timeout fixture confirmed a dedicated child session, a group kill, a reap and refusal. The test intercepted process launch and signaling. [Controller hook](/tmp/jsh-s4-continuity-controller.Agp06zzf/controller.py:504) · [Timeout fixture](/tmp/jsh-s4-continuity-independent.cUmE9qzn/test_independent_continuity.py:120)

All 50 supplied and 23 independent cases passed. The two continuity defect cases assert the observed behavior and should be inverted during repair verification. The staged source remained byte-identical to the reviewed copies. No live host, service, network or production activity occurred. Full controller rehearsal and site acceptance remain separate gates.
