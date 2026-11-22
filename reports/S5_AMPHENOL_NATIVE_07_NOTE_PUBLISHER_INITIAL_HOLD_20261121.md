# Independent guarded note publisher initial QA

**REJECT the exact `28552f7dee8f5c7abe7f0453995056fd3d9fa13a70a92a789943026ca0012e2b` adapter for release.** Its normal and lost-response paths succeeded in the private real SQLite/fake-workbook composition. Three independent negative checks showed that the durable override removed existing authority checks.

After one fixture workbook commit with its response interrupted, I separately replaced the VERIFIED local Jobs parent with a foreign plan digest, added an unrelated valid durable row scope, and set the remote intent to observation-only without corresponding durable authority. The installed reconstruction held all three. The new method accepted all three. Preserve parent plan digest equality, exact normalized-to-projection cardinality and identity, and durable delivery mode/evidence validation. Keeping this private adapter write-once and refusing alternate observation authority is sufficient for the narrow case.

Both unchanged-authority positive tests completed through real exact receipt and local acknowledgement, standard cleanup, and one COMPLETE closeout result. Four review notes were appended once. Neither normal completion nor lost-write-response recovery sent a second workbook operation, and closeout replay left one immutable outcome. This result confirms the narrow rendering and reconstructed note fixes without exercising the missing authority checks.

Synthetic/disposable only. No production application state, process, provider, workbook or network was accessed.
