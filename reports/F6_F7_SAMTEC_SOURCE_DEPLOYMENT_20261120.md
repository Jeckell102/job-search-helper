# Sprint 3 guarded source deployment on MuleLab

The source-only maintenance transaction completed on November 20 with
controller phase `RELEASED` and transaction phase `INSTALLED`. Independent
pre-deployment QA accepted the exact source and rehearsal after 78
receipt-path, eight maintenance, and three attestation tests. The private
capsule and rollback records are under
`/home/chris/.local/state/job-search-helper-maintenance/s3-samtec-operator-20261120`.

The admitted bundle pinned endpoint manifest
`d656cbc969868952382c3db16e8f2e9e4e94eefef94d8ae7dd332f2c41168ef9`.
The transaction's normalized after-manifest is
`c1fd91da55983bbb1befd326c5f521a3cf93f2c0e4afe1ba6a6ab90109836a69`.
It made 13 narrowly scoped replacements and six additions. The production
package retained its original inode. The deployed launcher and runtime
attestation ran before the transaction removed its maintenance guard.

The protected witness recorded before and after installation has the same
hash `9ad7ec7f357bd3478767c9f1804ee46fe71e122dded36f20ccb541002f3cf4cc`.
It includes State, jobs and inventory databases and WALs, the selected
Samtec request and receipts, and the protected lifecycle controls. Local
copies are `/tmp/jsh-s3-host/install-before.json` and
`/tmp/jsh-s3-host/install-after.json`. No job data or spreadsheet change was
made by the source installation.

Independent installed-source QA is separate and was assigned after release.
The Samtec provider, Google workbook and approved signing key were never
called for the install. The live pilot and its own independent evidence
review remain open.
