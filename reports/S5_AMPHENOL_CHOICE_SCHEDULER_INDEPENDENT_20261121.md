# Independent coordinator choice and restart QA

**ACCEPT for the exact staged coordinator and inference-receipt changes.** All 80 maintained offline tests passed on the final pins. The isolated pilot fixture used synthetic reader, builder, and model callbacks with the existing coordinator, claim path, and durable store. Outbound connections and DNS were denied throughout testing.

| File | Final SHA-256 |
| --- | --- |
| `coordinator.py` | `dcf6f14ea4ff15e6c221ff3f46c29523419d931dfbf0dffe6e2edd6b0f427a91` |
| `coordinator_inference.py` | `4d94acad23e879089dee088c04826ddef4b062b77316915bf493ee2db17db968` |
| `test_owned_recipe_scheduler.py` | `e7f5975ef3ea5ae8c65efd25a6431da712a9ee0eb018a4be832141300f18c0fc` |
| `test_inference_store.py` | `c5dcb8a968a8974194daf84f5206dabc7bb615c3ce976e51ed3db73980cb738b` |

The scheduler requires the named work order, isolated claimed pilot, review/inspect, passed baseline, current repair identity, and both hooks. Defaults held before inference. The one turn used the existing durable reservation and ownership binding. Receipt settlement persisted only the fixed `W1` choice with a valid, completed and accounted response. Generic inference continues through the original behavior with choice persistence off. The maintained suite covered generic scheduling, receipt accounting, dropped responses, and an unresolved owned turn remaining held. [Coordinator entry and dispatch](/tmp/jsh-s5-single-choice-coordinator.20261121/dev/wrapper-coder/tools/coordinator.py:1049), [receipt settlement](/tmp/jsh-s5-single-choice-coordinator.20261121/dev/wrapper-coder/tools/coordinator_inference.py:266)

An independent abrupt process exit at builder entry left the single completed W1 receipt durable and no candidate file. After reopening and reclaiming the same pilot, the builder received the identical receipt and wrote exactly one candidate fixture. The task reached `REVIEW_COMPLETE_LIVE_NOT_VALIDATED` and could not be claimed again. The inference totals stayed at one session, one call, and 560 tokens. The restarted model double was never invoked.

The initial `coordinator.py` pin `5c78737660e1401e54864f46bd99ca5e23ece7df76a36180f45d3e6aec528415` failed an independent deadline probe. Advancing the fixture clock during the second owner read caused one build after expiry before result publication set `PAUSED_BUDGET`. The final pin checks the deadline immediately before the builder. The same probe preserved the completed receipt, made zero candidate builds, and ended in `PAUSED_BUDGET`. [Corrected action boundary](/tmp/jsh-s5-single-choice-coordinator.20261121/dev/wrapper-coder/tools/coordinator.py:1133)

Native reader and builder wiring, recovery after a candidate has already been written, and live validation were outside this acceptance.
