# Sprint 6 provider hold followed by a separate successful company

November 21, 2026, 03:03 Eastern. Coordinator run in one disposable
application workspace with actual ordinary event, outcome and exact
publication code. The fixture injected one typed access-denied response
and used an independently captured Amphenol inventory. The two provider
responses and the workbook transport were fixtures. No native operation,
release, inference or Google request occurred.

1. The first Company's observed access failure settled as `BLOCKED` and
   its cycle as `Complete with exceptions`. The exact sender and receiver
   recorded the same `RECORDED_NO_REPAIR` receipt. There was no repair task,
   Jetson call, or workbook write for this case.
2. The second Company's event entered the outbox during the first cycle.
   The normal bridge kept the event there without queuing a second
   request. After the first settlement, the same event queued its own
   request, without replacing the first Company's outcome. A new
   Coordinator instance reopened the same receipt store.
3. Amphenol's separate cycle loaded 39 postings from the sealed archive
   and sent one batch to the workbook fixture. Readback matched 18 unique
   Job Keys between local storage and the workbook. Exactly one
   request-bound `SYNC_CONFIRMED` receipt was saved, and the cycle
   completed. Its sender and receiver receipts matched separately.
4. Each fixture fetch observed both application locks and exactly one
   active owning cycle. Terminal replay fetched no provider and did not
   reopen the workbook. The first Company, unrelated Company, saved
   unrelated job including its manual salary estimate, and Opportunities
   were unchanged during the second cycle. Broad queue and campaign stayed
   off.

The first two driver attempts exposed fixture assumptions. The normal
bridge keeps the second event in the outbox while work owns the lane.
The v1 receipt labels a blocked outcome `RECORDED_NO_REPAIR`. Neither
required changing application source.

Independent QA separately found that the original fixture's salary label
was outside the actual sheet schema. The corrected driver uses the
canonical columns and checks a nonempty estimate before either event,
after the first hold, and after the second publication. Both stores
retained the same unrelated row and estimate.
Independent readback of the corrected runtime verified the actual local
and fixture workbook value and all seven protected fields.

The passing composition includes the current staged host and disk hold
source and the separately reviewed exact publication and guarded-release
modules. There was no active release in this test. The two-case
disposition does not satisfy the remaining deployed three-Company
sequential and controlled repair gates.

| Evidence | Exact value |
| --- | --- |
| Fixture root | `/tmp/jsh-s6-sequential-composed-estimate.20261121` |
| First cycle | `CYC-9435AEA3A0F9` |
| Second cycle | `CYC-B776CC93171E` |
| Runner SHA-256 | `24a604dc396291d4403595438b772c4d6193de7f0399a426baa2a4a66b838fc7` |
| Sanitized result SHA-256 | `b919145e9081476bba0340f6c7bbdb8802eacfa9f040203ba23302b535ce149f` |
| Source pin file SHA-256 | `01285515ccba9b37e455deb6ded90d1d97f7edddf9145124de32d9e91150d443` |
