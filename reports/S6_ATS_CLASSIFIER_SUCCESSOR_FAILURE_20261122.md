# ATS classifier successor failed verification

The scoped classifier source installed and passed independent readback
as `REL-4141919bb885000b0e7244c2`. A distinct real company-only request,
`operator-ats-20261122-02`, observed the same ATS pagination defect. The
new acknowledged outcome `OUT-0f9f42286193d7caa8d22f98` reserved one
successor. The original task and its inference stayed intact.

The single Jetson request `4ca2e279ef434046b627d1c4c956235f` completed
for task `WRAP-9546a1473a`, one session, one call, and 1,097 tokens.
It produced one guarded edit to `src/job_search_helper/ats_job_path.py`.
The prompt and executable fixture agreed on the contract. The edit used
the same slash indexes for both root and branded paths, and rejected
`/job/Test-Engineering/10001/`, the first valid example in the assignment.

The editable run (receipt 298) and immutable run (receipt 299) each
reported 25 passed and four ATS failures. No shared-provider thread
failure recurred after the independently accepted offline runner fix.
The rejection originates in the model-authored path classifier.

The successor remains `PAUSED_TEST_FAILURE`. There is no accepted
candidate, live qualification or ATS retry. Nothing from this attempt
was published to the workbook. No broad controls were enabled and no
frozen Sprint 6 case earned completion credit. Stop further ATS
inference on these tasks. Carry forward the tested deterministic
host boundaries, and select the next qualified named pilot.

Evidence is the installed task and immutable receipts and the local
terminal summary
[`TERMINAL_OBSERVED.json`](/tmp/jsh-ats-classifier-release/qualification/TERMINAL_OBSERVED.json).

Independent review reconstructed the exact model edit against the
installed stub without executing the rejected code. It matched
receipt 297 and final source digest
`e72d6c3817db47b247b34821c23c2d12c823a5994276afc1a29680cfe34ca821`.
Independent QA rejected this successor. No provider calls or test reruns
were used in the review.

A fresh installed local intake check after the ATS attempt saw zero pending
Company events, zero unassigned repair entries and zero unsettled
inference requests. Neither Forterra nor Amphenol had a current unassigned
qualified outcome. Allen's accepted ordinary source migration is a
separate proof. The frozen qualifying sequence remains zero of three.
