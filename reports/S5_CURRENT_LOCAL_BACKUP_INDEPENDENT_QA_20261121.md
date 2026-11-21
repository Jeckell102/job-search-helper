# Independent finalized backup verification

**ACCEPT the finalized private backup.** Independently recomputed SHA-256 for all 2,352 declared payload files, totaling 6,745,247,566 bytes. All checksums, file sizes and private copied modes matched the manifest. The path inventory also matched. All nine declared SQLite paths returned `PRAGMA quick_check=ok` under immutable, query-only connections. The root review runtime file is a zero-length placeholder. The concurrent runtime database is present and nonempty. Backup inode, mode, size, mtime and ctime remained stable and the verification created no SQLite sidecars. [Saved backup manifest](/home/chris/.local/state/job-search-helper-backups/current-scraper-20261121-090919/backup-manifest.json) · [Independent result](/tmp/jsh-current-backup-independent.CV8fKLDq/RESULT.json)

The copied manifest, State, Inbox and Jobs agree that cycle `CYC-B639C6D864EC` was `In Progress` and had 800 saved Company entries. Saronic remained at the inventory stage, with a **67 of 208** publication cursor and **276** complete, unblocked saved jobs. The Jobs cycle mirror matched. The saved plan and Jobs also preserve the operation 194 source transition and operation 195 paired evidence, including one existing evidence row for the current source and zero for the proposed source. These are exact copied recovery facts. [Independent Saronic readback](/tmp/jsh-current-backup-independent.CV8fKLDq/CHECKPOINT.json)

The manifest records that coordinator storage was captured separately from the core scraper files. The preserved backup is a local recovery copy for inspection and rehearsal. This review opened no live databases, ran no scraper or workbook operation, and wrote only sanitized verification artifacts under `/tmp`. [Reproduction](/tmp/jsh-current-backup-independent.CV8fKLDq/verify_final_backup.py)

| Artifact | SHA-256 |
| --- | --- |
| Final backup manifest | `236c688c5a5636b7ac9e57d77e54510d5867b536292f14483072d671e649a3bf` |
| Independent verifier | `90d88eb4be3513771c1cd8c316fce26b37a07136665877917b7b71624466e322` |
| Independent full result | `2ec05f77a00ebba91dffcb710c754c59d9e486d9b06daa78fa381acbc7be9885` |
| Independent scoped checkpoint result | `1dd68db6a0412b6849af178f5a30bd6275155cd43aea3fa407e08de9e7c19a41` |
