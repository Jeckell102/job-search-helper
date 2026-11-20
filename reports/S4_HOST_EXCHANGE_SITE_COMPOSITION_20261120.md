# Sprint 4 site verifier and maintenance journal composition

November 20, 2026. The site verifier now reads the approved exchange
controller's journal via its read-only witness API. The staging directory
is `/tmp/jsh-s4-journal-site.uL3AMus0`. The verifier matches the account,
approved policy digest, exchange generation, intent digest and ordered
canonical and parked paths. The controller authenticates the locked journal,
validates both endpoints, and refuses any phase other than complete closure.
The site still checks both route sets for running processes and verifies the
writer fence both before and after the other site observations.

The bundled controller was copied byte for byte from the independently
tested staged source. Its SHA-256 is
`0103a6643062b9200ca638d9f07b1396690f58925dda091c8380d36117eb0ac5`.
The site adapter SHA-256 is
`72ea4682d60200669b6052906d32899946e6bc67da482b105e47d01239c0ccad`.

## Verification

The combined suite passed 82 tests in 7.71 seconds using the production
virtual environment's Python with disposable test paths. It checked that
the verifier leaves journal content and metadata unchanged, rejects a
different policy, generation, route order or intent, refuses an interrupted
close, accepts after replay, rejects an old closure after restoration and
refuses a substituted endpoint. The site-level tests also cover an active
process at a parked route, an omitted alternate route and exact round-trip
of archive policy. Independent review of the composition is assigned to
`/root/site_journal_qa`. The underlying exchange controller's independent
QA passed 15 fixture checks and held live acceptance.

## Live release gates

A live policy must be compiled from an acknowledged close by the approved
controller. After an uncertain exit, require a successful exact close replay
before compiling the policy. A visible terminal phase alone cannot prove the
controller completed its directory sync. Enrollment still needs a supported
way to continuously exclude changes to the approved policy and checkout
paths during transitions, an accountable production and alternate writer
drain, and a separate exact terminal-proof verifier before reopening. The
82 checks establish source behavior on disposable paths. Production code,
checkout routes, services, job data, Sheets, and the Jetson were untouched.
