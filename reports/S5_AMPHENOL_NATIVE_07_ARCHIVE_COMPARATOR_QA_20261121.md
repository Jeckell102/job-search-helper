# Archive-aware workbook comparison corrected pin

**ACCEPT for independent read-only workbook verification.** Comparator SHA-256 `0c6dc12ee0314206face2202be1e46b8c7873cbcc702c05495b4eb4f23b886c8`. Maintained tests SHA-256 `64a1c1ddad1b29b2152f15b687c3da10a6b5aa53daa5f92d22eeb46cde417c82`. Nine maintained cases and the prior independent exact-baseline red passed, for ten total.

The archive path is limited to the exact v1 record fingerprint format used by this v2 application plan. It verifies the archived plan digest, projection, exact application scope and original receipt before remote reads. Baseline and live workbook fields now each independently reproduce the archived receipt, including the pinned note suffixes. A semantically equivalent but byte-different baseline scalar no longer receives original-fingerprint credit. The fallback and exact identity, bounded row reads, and read-only scope remain intact.

Passing log SHA-256 `c98726dcb0c9f0252e8160d23de79ed048961494c9d2bff5c5f7d6fc6c831163`. The initial rejection and its exact fixture are preserved separately. These tests used a synthetic workbook only. Live workbook comparison depends on a confirmed receipt and remains unavailable at the actual held cut.
