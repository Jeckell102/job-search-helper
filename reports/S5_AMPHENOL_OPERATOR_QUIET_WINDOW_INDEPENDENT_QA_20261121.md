# Independent quiet-window staging and composition acceptance

**ACCEPT** the corrected quiet window at the exact staged pin and its integrated disposable result.

| Evidence | SHA-256 |
| --- | --- |
| Corrected quiet-window source | `8b124170b12897dcc37a82d6a5af5ed38538fee22d9194ddf4146c2565a2fdc4` |
| Reviewed Systemd controller | `f63f9399f3fcdec3d3b46a6d5e14fc3d1d78e420234b357b0adf44bd68a53ff8` |
| Maintained tests | `6fe349b403fc54f3a85010d2738139f6b0f5331aa55ffdb63d10a7fdd0a96394` |
| Combined corrected test result | `cce5f7ae517c87d398f4f08a4afa760295509221ab0510bd0958d9589474e324` |
| Earlier exact red result | `9fd7c59291cc89a612bea2280849f702892325dc77a29f201f68bd077b13b1b7` |
| Final integrated fixture result | `0afd1523c3c2db01df805d4f8b4680a2edb7b66e5c4e91a2e76485b027171fa2` |
| Independent integrated readback | `b012b503d2467a46d2e2e34f1b46d63b99d8d07c8320d37747f922716a403c0d` |

The captured original `73883c50…` failed four cases. A failed restored proof or a start that took effect and then errored left its service fence removed. Incorrect backend or Jobs configuration entered the quiet window. The corrected source passes all 12 maintained and independent cases. It checks the configured SQLite backend and exact State/Jobs pair before admission and service work, reestablishes the physical fence after failed start or restored proof, and retains `RESTORING` for explicit recovery. Partial durable `CLOSING` replay restores without entering the worker. A nonterminal application release retains the fence; restored replay verifies prior state without a second start. Default and missing independent approval perform no admitted service changes.

The integrated copy matches the corrected quiet window, one-shot, controller, gate and installer bytes. Both private mode-0600 window journals report `RESTORED` for the same approved fixture attempt. The original wrapper active/enabled and sync inactive/disabled references match exact fixture file inodes, modes, owners and bytes; both fences are absent. Immutable ledger readback confirmed two matching receipt pairs, one `VALIDATED_COMPLETE` event, one `SYNC_CONFIRMED` publication, one Amphenol job and one workbook batch. The original paused synthetic task and completed choice remain.

The reused Systemd implementation targets exactly the wrapper and sync units. Its command/cgroup observations and the separate outer maintenance authority were simulated. This result provides staged and disposable coverage; native host exclusion, fresh deployment approval and production qualification remain separate. This lane ran no native or network operations.
