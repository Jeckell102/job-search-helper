# Independent systemd enrollment readback review

**ACCEPT for the exact staged quoting fix.** The literal ANSI-C wrapper for the existing managed key is removed without shell evaluation, expansion or escape decoding. An unsupported escape or duplicate scoped key still holds. The prior forms still use the existing `shlex` handling, and manager and process values must still match the exact owned enrollment. The armer diff only updates the helper digest.

The exact original helper reproduced the foreign-owner error on the maintained fixture for a manager write followed by the systemd-formatted readback. The corrected fixture reconciled the same saved key with the old process using one wrapper restart and zero second writes to the manager. All five tests passed on the corrected pin, including foreign-scope and unsupported-escape refusal. No real service, environment, network or data was accessed.

| Artifact | SHA-256 |
| --- | --- |
| Corrected manager helper | `8255eb149845ea66fcc1a850693e703ae64bd34996dd267e9ad7bb36c1d45ae4` |
| Re-pinned armer | `3a69fa39e9b4e5948c2ef18a29462bb3cff129e7650337d1826219c943422d83` |
| Maintained test | `e62a1c302247e4a3681b4d01ae0c88cbb7f14ed2f97181d340d2410bce9223c3` |
| Archived previous manager helper | `2a00894c617904ee4edae4b0c4fccf0d45e63776550f9ffe569141ad5507307c` |
