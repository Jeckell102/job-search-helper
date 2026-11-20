# Sprint 3 live Samtec preview did not pass

At 12:12 Eastern, the independently accepted deployed source reached the
live read-only preview and exited with `retained_operator_workbook_schema_changed`.
The exact legacy historical manifest was produced. No v2 approval claims
were produced, no approval was signed, and no scraper provider, publication
writer, or retained reservation was started.

The production environment sets `EVIDENCE_ARCHIVES_FILE`. The default remote
repository wraps its compact main client in `EvidenceArchives`, whose public
schema is the full workbook schema. The source fixture originally returned
a bare compact client and did not exercise this combination. The operator
route already keeps full posting descriptions in local Job Evidence and
publishes only the compact Job History projection. Select the established
`evidence_archives=False` option for both scoped factories. Preserve the
strict stored-profile/current-header check, all archived evidence, existing
configuration, workbook, and the held request. QA must exercise real
repository construction with the archive setting present and reverify the
installed correction before authorization or a provider call.

A separate read-only diagnostic process explicitly disabled archive wrapping
for its own main-workbook call. It returned valid exact Samtec preview claims.
That process used a different runtime configuration digest and its claims
are diagnostic only. No production configuration file changed and the
diagnostic claims will not be signed or used for execution.

The single-file correction installed and rolled back successfully in a
disposable copy at manifest
`d70ce1c69a4a6798c3e40b2528c79a3b59c1e53daeffca7df1c0a82433c6d280`.
The separate maintenance namespace preserves the completed Sprint 1 and
initial Sprint 3 records and parking sentinels. Eight transaction tests
also passed with the new maintenance namespace. The main-workbook factory
regression and deployed recheck remain open.
