# Confirmed workbook comparator review

**ACCEPT for independent verification tooling.** Comparator SHA-256 `4767ef42b2e9f8c21d6d9f99761147149495abde96999bebb781ccc22ffc774f`. Maintained test SHA-256 `95f1cabc9c9cab62c926ef3ca092f81f4cceb5fe93161c8339a166f11b657c78`. Four maintained tests passed.

I selected the exact retry from the completed disposable operator fixture, joined the Inbox receipt to the verified Jobs application and acknowledgement, and opened the fixture stores immutable and read-only. I passed the independently archived workbook snapshot through the existing GoogleRepository over its in-memory Sheets fixture. The comparator matched one Companies row and one Job History row, with both original fingerprints and zero writes. The archived workbook input SHA-256 was `fe9fa3ae2c38d3da9f539e6cf368d123cfcb0e21560e895b5314c9d0d718fa81`. Supplemental tests rejected local-only Scan Cycles and Job History Source Hash before any read and withheld original fingerprint credit where the baseline string was equivalent but differed in bytes. Appended note coverage was separately reported as one observed row and zero original fingerprints.

One fail-closed result-format edge remains in this pin. If a monitored identity is also a published field, an equivalent but byte-different identity value such as trailing whitespace in a Job Key can recompute a differently labelled fingerprint. The helper then raises KeyError instead of tallying that row without original fingerprint coverage. This proves no false confirmation. It warrants handling if that presentation can occur in the authorized workbook.

No live workbook, production store, provider, service, or release action was used. The comparator has no release or acknowledgement authority.
