# GA-ASI scope-hold source review

**HOLD on the first reviewed source pins.** The proposed local hold checks an exact permanent reservation receipt, current unclaimed Company source revision and the unresolved shared-parent mapping before storing an immutable outcome and bound local evidence in one Jobs transaction. Archival follows the commit and uses a non-replacing hard link before acknowledging the queue. The dedicated executable path contains no provider, Google, Jetson, Engine cycle or coordinator launch.

Two supported generic boundaries still need correction.

- The runner tests the raw CLI request ID for the reserved prefix. Reservation strips it, so a leading space can put a foreign Company's request into the reserved namespace. The exact scope-hold command then refuses that Company while normal SQLite start refuses the prefix. Check the canonical identity at reservation.
- The generic guard returns early for the Sheets backend, and shared scan admission does not independently refuse the prefix. Keep the request out of normal scan admission on every supported backend, and reject scope-hold reservation before opening a non-SQLite repository.

The runtime guard currently uses archive existence to decide whether mutation is pending. A process interrupted after linking can leave the archive and exact queue together. Gate same-request queue removal on the original runtime even when the archive link already exists. Replaying a final archive with no corresponding queue need not require the old runtime.

Source pins

- Hold module `1d5bd454d06ff3eac9d7907a96df4dff426eddd58544ad73ca197c1ccdff245f`
- Runner `6350147195d7eacd89a93e8287950960e6d77d844318dfc743022bbfd0f2554a`
- Generic guard `ce0f06f1be6e2bfcc38aff7c9716ed82c90b43c2839bb677ad2f658845ed8627`
- Shared scan admission `bff962b532c444448255ca81315ad5812ef9591050d62e1914f0174dd893d2e5`
- Bootstrap `9e15bf97ef9af0db88a48ff7632fdb826320f50463a0b64ef11f6aa07e9df6e5`
- Shell `429fd628e682e74549687452345aa0d440b9bb27eb2afe19e108fa4818ec1aca`
- Design decision `3660e80b1deea3061fdcc5112da7c53eb43a49ee1c0eb59c41028dc922321573`

Static source review and isolated normalization check only. No production actions or candidate changes.
