# Evidence storage in Google Drive

Full job descriptions now live in private **Job Search Evidence - Volume NNN**
spreadsheets. The **Job Evidence** tab in Job Search Master lists their links.
Match both **Job Key** and **Source Hash** when looking up a description.

The scraper and managed reviewers automatically search every volume. Continue
using the existing launch commands. No new scraper cycle is launched by this
migration. Job History, Opportunities, review decisions, snapshots, and saved
scan checkpoints stay in the master workbook / existing local state.

`EVIDENCE_ARCHIVES_FILE=.state/evidence-archives.json` in `.env` enables routing.
Keep this registry with the project's state backups. A missing or mismatched
registry stops execution; it does not silently put descriptions back into the
master workbook. A restored installation must retain this setting and file.

New evidence rolls into another private Google spreadsheet before the active
volume's conservative byte reservation reaches 30 MB, or its rows approach the
repository's limit. Reservations include repeated writes and ambiguous retries,
so this is an upper-bound growth counter, not Google's reported file size.
Existing evidence identities are updated in their original volume. Newly
created volumes appear in My Drive and are linked from the master directory.

Evidence writes complete before the corresponding master-workbook transaction.
Google does not provide transactions across spreadsheets: interruption can
leave an extra unreferenced evidence record, but never advances history after
an evidence write failure. Resume the same keyed operation; it will reuse an
existing record rather than append a duplicate. The existing single-writer
lock is still required. Do not run an old installation against the converted
workbook, or manually reorder/modify the archive registry.

The migration verified every archived value against its source. The original
workbook is permanently read-only and remains unchanged as an additional backup.
All operational tabs were copied into a recovered master; Job History was
transferred in verified sections because Google rejected a whole-tab copy. A local copy of the original evidence and a backup
of replaced code/configuration are retained under `.state/storage-migration-backup/`.
The master still grows through job records and compressed snapshots; archive
rollover controls evidence growth, not all possible workbook growth.

Active recovered master: https://docs.google.com/spreadsheets/d/1LJwaKYvD8Xh1cCub9VAYfzhsDEyoIcew9LHgaxbOT7Y/edit

The scraper configuration and inventory destination now use this workbook.
Existing inventory payloads, sync cursors, review decisions, and cycle checkpoints
were preserved. Pre-reconnection database copies are in the migration backup.
