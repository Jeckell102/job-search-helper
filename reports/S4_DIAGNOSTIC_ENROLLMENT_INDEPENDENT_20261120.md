# Independent diagnostic capsule enrollment review

**ACCEPT for the exact staged diagnostic capsule.** The review read staged artifacts and left native operations to the coordinator.

| Diagnostic artifact | Verified SHA-256 |
| --- | --- |
| Checker | `2152e99bd8994cc5bd51aa6cb9fea1c6ff36557fd975793456543342bc5101b8` |
| Unused enrollment | `16e50fdf972cf7058f86ece6c6630a820c14f050117bcd20f160845a788898ca` |
| Fresh exchange policy | `04aad106dd9cf585d0d02854c4c315c55049f2a0364911af80c5e1fff3006f9a` |
| Reviewed diagnostic entrypoint | `36407235f3d12df8db3070e6278c1090b8395c6a2b88b00953f3ea3faab1c8e7` |

- Recomputed all 69 listed payload hashes in each capsule. The only changed staged payload was `site-source/host_check_main.py`. All 47 candidate paths matched the same manifest digests, modes, and owners. The plan, manifest, and abort tool were byte-identical.
- Both checker archives had 12 unique members and passed CRC checks. Only `__main__.py` and the embedded policy differed. The policy changed only the exact diagnostic capsule path and the fresh exchange identity. The observer socket, wrapper port, protected-state pin, both recorded source inventories, and external controller and lease records matched.
- Both exchange policies reconstructed to the same three exact canonical and parked path pairs. Their normalized intents and digests matched their respective journal and enrollment. The old exchange journal was terminal `restored` with three completed pairs and proof `4dc2b2ad75566f880ac296cc8553837c15a7d3a456ba0abd4366b4f31e6881a4`. The new exchange was prepared at `closing`, with zero completed pairs and no terminal proof.
- The new attempt contained only its empty private `attempt.lock`. The diagnostic capsule had no transaction directory, controller journal, service hold, pending admission guard, or sealed wrapper images at review time.
