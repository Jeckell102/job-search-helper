# Sprint 5 live AcquireTM page-transition witness

At 00:30 Eastern, the separately staged and source-reviewed diagnostic read
the exact public Amphenol Aerospace board without fetching details. The
board advertised 39 postings. After the same page-two click, the old
25-posting membership was still present at 98 ms. At 347 ms the board showed
14 disjoint posting IDs and the same advertised total. The diagnostic
returned the original partial result and a typed
`acquiretm_updatepanel_premature_read` witness. It made no second click.
These timings and counts are observations from this one run.

The capture contains scope, board URL, counts, timestamps and hashes of the
sorted memberships, without public posting IDs or body contents. Its
SHA-256 is `d10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602`.
Private source, capture and exact command are in
`/tmp/jsh-s5-amphenol-typed-live`. No Jobs/State store, Google client,
release, retry or coordinator task was used for this capture.

This proves why a bounded candidate should wait for a change in listing
membership. It authorizes no automatic repair or installation. An
application-owned terminal outcome remains required for the automatic path.
