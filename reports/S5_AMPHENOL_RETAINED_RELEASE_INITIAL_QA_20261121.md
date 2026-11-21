# Retained Amphenol operator release preflight

**REJECT** the exact staged preflight. It accepts ancestor aliases in two filesystem inputs, throws on unavailable State, and can create an empty coordinator database while trying a readback.

| Evidence | SHA-256 |
| --- | --- |
| Captured reviewed module | `b6bdcf7277cb4f630a620130637604e8bb3875c98817da6d4c84366ba4da209f` |
| Captured maintained test | `95322c9ecbf909e7976efbab4e788a738ce0dd39b4dd242a278bf105eee3851c` |
| Independent tests | `9682337ba79e4ad8c7836bbfc4cc95b869fa571971ec1595bd297bf55c5b4683` |
| Combined output | `338f456ecaf1e8525baf2d7acb5300dabede314f8e481809a058a04caab98bac` |

Three controls passed and four targeted cases failed. The maintained checks verify default hold and explicit-only delegation with substitutions. The independent positive control uses real canonical manifest validation, the actual on-disk private qualification owner with a pinned descriptor/device/inode/digest, and a copied exact before-image, candidate and build receipt. The synthetic authority isolates the proposed orchestration from the actual live proof. A missing receipt, or a correctly pinned receipt reading PASS for a different manifest, holds.

- In the otherwise identical positive case, supplying an intervening symlink in either the project-root or candidate-root path returned a prepared release. The terminal target file and candidate root were not symlinks. Require physical absolute roots and physical candidate file paths before accepting them.
- The actual operator source reader with a valid scratch inbox destination and absent State raised SQLite OperationalError past preflight. Treat unavailable or incomplete readback as a held gate.
- Following a successful source readback, calling the real configured Store on an absent coordinator file caused its default read-write SQLite connection to create an empty database, then error on the missing tasks table. Obtain task and receipt from an explicit existing-file read-only receiver snapshot.

The saved evidence shape agrees with the module's choice inputs. The sanitized pilot reports task `WRAP-6a3a372032` with one completed inspect receipt `2b444fe8f48a4c6e9638f1c6a7acb40c` and the exact W1/listing_membership_change/phase_done choice. The saved candidate result identifies outcome `OUT-9f4b030568412faca159be2f` and its candidate hash `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`. The actual archived build receipt contains request, response, Company, outcome and source-revision fields consumed by reconstruction. The pilot report alone supplies neither the private current readback nor independent live qualification.

The review was limited to staged source, sanitized reports and disposable files. No live release, provider, scheduler, SQLite, remote or model operations were performed.
