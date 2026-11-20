# Sprint 3 live Samtec pilot evidence

The signed request `operator-samtec-m1-20261119` admitted only Samtec
`COMP-0739`. The deployed operator path collected a complete **160-posting**
inventory and rechecked the live Jobvite board. The provider stage took
67.142 seconds. The queued request was 52,000.314 seconds old when the provider
started. It had waited behind `CYC-B639C6D864EC` for the approved, signed
exception. The ordinary busy scheduling boundary remains separate from this
exception, with a 60-second target after safe cycle completion and a
60-second idle target from enqueue, both verified in disposable admission
fixtures.

Normal filtering produced **63** Job History rows and **63** exact local
Job Evidence records with full descriptions. The 63 Sheet rows included 60
pending review and three deterministic exclusions. The selected review
release held 51 FIRST PASS and nine SECOND PASS rows. The pilot did not turn
any posting into an Opportunity or change another company.

The observed pending snapshot distinguished the verified local application
from the still-pending publication. All three exact remote chunks were
confirmed at sizes 25, 25 and 13. The final full readback reached
`SYNC_CONFIRMED` at 12:32:53 Eastern. Its acknowledgement is
`63d83bcf2ccf067afb4efb567af0afb10b2546baa3feaed48f90cda5cd1569a5`.
The matching receipt is
`f06f9c82a7873aa19bd2f932de762a25a74a8d77cc07a1e52d7c19b9b8a554fd`.
The consumed request and exact journal are now archived. No active operator
journal, pending request, or dirty cell remains.

The coordinator recomputed every exact local record fingerprint and the
terminal receipt from local durable stores. The selected records and
receipt matched the sealed plan and archive. All **140,468** out-of-scope
local records matched their pre-pilot fingerprints. Historical State and
inventory databases, WALs and the original request receipt matched their
protected hashes. The retained Saronic record was never resumed or
reconciled.

A replay of the same signed request returned a byte-identical terminal
receipt. The deployed replay's syscall trace had no network activity.
Replay also left every protected database and control file byte unchanged.
The before and after witness SHA-256 is
`03a0f8dceffbd65b138d11594b442dc8ccd291491e14ff5f887da8c2daa5e055`.
Independent disposable fixtures separately cover a lost Sheets
acknowledgement, a changed manual decision, and a blank extracted salary
with an existing estimate. Recovery holds on the intervening manual
change and never resends the claimed write or refetches the provider.

Independent live QA accepted all 63 selected Sheet rows, 60 preserved
guard values, exact readback digests for each of the three chunks, and the
original full acknowledgement. See F6_F7_SAMTEC_LIVE_INDEPENDENT_QA_20261120.md.
Private, durable operational evidence is in
`/home/chris/.local/state/job-search-helper-maintenance/s3-samtec-pilot-evidence-20261120`.
The approval, raw postings, job records and OAuth/signer files stay out of
GitHub. Broad backlog processing, automatic intake and unqualified release
controls remain disabled. Sprint 3 and Milestone 1 are accepted.
