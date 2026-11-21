# Independent held Amphenol proposal and release entry review

**ACCEPT the frozen proposal and corrected read-only package entry. HOLD public qualification and release.** The only manifest path is `src/job_search_helper/acquiretm.py`, with original mode preserved. Independent measurement reproduced the installed and candidate full source digests, their exact one-file difference, identical effective configuration, the installed dependency bytes and the 256-file public capture vector. All four preparation inputs matched their recorded raw hashes. The expected installation readback digest deterministically binds those projected bytes and wrapper metadata. Its `PASS` is an expected measurement. The separately captured provider log ends in HTTP 429 with Retry-After 3600 and has no qualification pass marker.

The seven reviewed sources are the only files in the private 0700 tool directory. Each is physical, mode 0600, matches the entry's pin and resolves through `PathFinder` to that exact file. The corrected entry’s origin verifier is unchanged, checking pre-import and post-import paths and the binding of installed Host to the application and coordinator roots. The coordinator separately verified actual isolated default import and projection. This lane computed private origin resolution without starting the installed Host or touching its credentials.

The exact prior default entry called the staged idle check. An independent disposable WAL-mode coordinator database proved that this check created `tasks.sqlite3-shm` and `tasks.sqlite3-wal`. The corrected default removes that call and corresponding quiet claim. Its remaining output is an import/readback result and installation was not requested. No native application store, provider, workbook, service or network was accessed by this review.

| Artifact | SHA-256 |
| --- | --- |
| `prepare_candidate.py` | `41f9dd6939c0cdb18f934537e43e986f6b92a34d0c64075cbeeccc659fc8fdc6` |
| `CAPTURE_PREPARATION.json` | `dbf3196f8ff5e2467ae00a1b7ec0c7cf4afcfd66996f5ee70cf697fba40ac7ea` |
| Public hold report | `4390a8570ec7e77ed4eda20df7f5646d9b5f3f636eee5c56a5d71d2d654741b7` |
| Canonical proposal | `9b02e2bb924666d240ec666d5ad6292def584e8f7155f89bfa3c465999fc323e` |
| Prior entry | `17701004f6f05c5356bd442e483c93cdd5ce71575c1edca0378f0c2a9af3a089` |
| Corrected entry | `b1e018358043de59ae4c525e7e778637a0a6986613398b63199b8626514d9199` |
| Artifact and WAL-sidecar result | `9dea91c9ea23fb6fcc261a868224c401426518234387acdb1b5f6011fce33ff7` |
| Exact corrected-source diff check | `45d48ca5c2fbb66a7fccd59e6bd0b5e8fc1fbf9c44bac2b890f8d00298505a76` |
