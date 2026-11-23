# ATS Corporation single-edit failure

MuleLab admitted the real ATS pagination failure
`OUT-8b214610d53e23115e70da5f` from exact request
`operator-ats-20261122-01` after verified deployment of
`REL-aa0e7a762a8e741c03b99692`. The existing authenticated pilot stop
released the terminal Crown slot while preserving all prior task and
inference records. The ATS enrollment activated after one wrapper restart
to PID 800483. The settled task was `WRAP-9db6388719`.

The Jetson completed one request, `22a2ecf17cf744298a39f10418af7f5c`,
in one session, at 1,478 tokens. Its guarded edit changed only
`src/job_search_helper/ats_sitemap_parser.py`. The code-edit receipt
binds the isolated file SHA-256
`ae00fd0127af1551c78c177524080d5ebd8b2aa6fffec75373a466b377ba5d7a`.
The final diff shows the edit ended at the intended target.

The editable and independent immutable ATS tests both rejected the new
code. The parser uses the fifth slash-separated item as the posting ID,
which is empty for the ordinary root path exercised by the fixture. The
returned map inverts the required ID-to-URL direction. The code also
rejects ordinary same-host navigation URLs that the assignment allowed.
The provider-level test suite separately reported thread creation errors
on related shared-provider tests already present in the baseline.
That runner problem does not explain the ATS-specific assertions.

Decision: hold the repair with its original `PAUSED_TEST_FAILURE` state.
The task and its sole settled inference receipt are retained. No replay,
candidate qualification, candidate deployment, provider retry, or job
publication took place. No frozen Sprint 6 completion credit. The
installed production stub remains disabled. Automatic backlog processing
and automatic release remain off.

Evidence is saved in the installed coordinator's read-only task and
tool receipts, and the hash-only terminal summary at
`/tmp/jsh-ats-native-package/activation/INDEPENDENT_TERMINAL.json`. Next
review the smallest change that gives the model reusable parser helpers
and short, exact test feedback, while preserving the original tests.

Independent QA reproduced the diagnosis from saved receipts without
rerunning tests. Editable receipt 293 and immutable receipt 294 both
reject the ordinary root path. Baseline receipt 291 already reports the
sibling thread errors.

The assignment itself contributed to the reversal. Its examples and
stub docstring show URL-to-ID while the requested result and checked
contract are ID-to-URL. The next assignment will keep dictionary creation
and navigation handling in the host-owned code and give the Jetson one
small provider-specific classification function with executable examples.
