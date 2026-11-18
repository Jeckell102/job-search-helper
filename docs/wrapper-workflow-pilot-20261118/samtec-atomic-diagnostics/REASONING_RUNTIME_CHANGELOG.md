# Temporary AI-computer change record

2026-11-18: Updated `/home/chris/AI/local-ai/wrapper_inference.py` on Jetson to accept optional strictly Boolean `think`, default false. Both context estimation and native inference use the flag. Same model, 12,288-token context, 3,072-token output ceiling, shared single inference gate, and private-reasoning exclusion remain. Restarted `local-ai-orchestrator.service` after idle checks. Independent stage tests 4/4 and author tests 4/4 passed; independent installed hash and service verification passed.

Original and deployed runtime copies plus deployment receipt are saved in this MuleLab temp folder. Reviewed deployment uses atomic replacement, preimage hash checks, and rollback. GitHub backup: `backup/wrapper-pilot-20261118`, commit `99f7bc4`. No integration wrapper changes applied.

Reasoning diagnostic 1: 11/14 route checks passed, rejected because Samtec invalid routes bypass original scope validation. 1,244 prompt + 999 generated tokens, 76.35 seconds; normal stop. Corrective diagnostic 2 is pending. Original non-reasoning probes all rejected. This is operator-assisted testing, not autonomous integration acceptance.
