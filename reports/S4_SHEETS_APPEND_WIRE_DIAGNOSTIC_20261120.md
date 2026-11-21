# Google Sheets native table append diagnosis

The guarded Sprint 4 rollback finished with all 47 before-images restored
and all three alternate checkout paths at their original locations. The
original wrapper and bridge are active and enabled. Scheduled sync stays
inactive and disabled. The exact Atomic Machines legacy claim stays spent.
No Company event, scrape or publication resulted from that attempt.
[Independent rollback and route review](S4_SUCCESSOR_ROLLBACK_RESTORATION_INDEPENDENT_20261120.md).

The application write credential successfully performed a metadata-only GET
of the working Companies table. It is 17 columns wide, has no footer, and
sits on a nonzero worksheet ID. The API reported zero restricted ranges
where this token could not edit. This diagnostic requested zero writes.

The same application Google client created one new, synthetic workbook with
a 17-column native table on a deliberately nonzero worksheet ID, and a known
seed row. No working workbook or backup destinations were accepted. A
one-row `appendCells` containing only `tableId` failed with HTTP 400 and
`No grid with id: 0`; exact readback found zero such rows. The same shape
also invalidated a batch with metadata creation. Its test record is separate
from the prior production response. The observed error explains the likely
failure in the production request but does not recover its discarded status.
[Google Sheets request reference](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request#AppendCellsRequest).

Adding the exact worksheet `sheetId` to the `appendCells` alongside the
native `tableId` succeeded in the same synthetic fixture. The row was
inside the native table. A separate batch created one explicitly keyed
developer metadata object and appended one synthetic row together. An
identical batch returned HTTP 400 for the existing metadata ID. Readback
confirmed one row and the exact marker. A tail value beyond the native
table survived both insertions. The synthetic workbook was moved to
recoverable Drive Trash after the test. No real job or Company data was
copied into it.
[Native table behavior](https://developers.google.com/workspace/sheets/api/guides/tables) · [Explicit metadata IDs](https://developers.google.com/workspace/sheets/api/guides/metadata) · [Atomic batch behavior](https://developers.google.com/workspace/sheets/api/guides/batch).

Next stage one fresh, independently approved Company selection and
versioned claim. Preserve the legacy claim readback-only. Use both exact
IDs and persist the marker, frozen scope/body, and bounded redacted result.
Confirm the same literal remote row and exact marker before the existing
local intake/event transaction. An ambiguous response with missing marker
or churn stays held. The test did not establish a production guarantee
against explicit metadata removal or justify a retry under that condition.
