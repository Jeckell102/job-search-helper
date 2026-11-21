# AcquireTM membership-readiness repair capsule

This is a source-only, non-installing recipe. The copied staged source remains
the accepted typed pre-repair diagnostic baseline; it is not represented as the
desired repaired outcome.

## Fixed inputs

- Baseline target: `src/job_search_helper/acquiretm.py`
  `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61`
- Independent W1 witness: `/tmp/jsh-s5-amphenol-typed-live/result.json`
  `d10331c3e89b63ef00a8a26af7ac4c69f66beb95167e3b2005b4d9e101cd0602`
- Only accepted selection: `{"strategy":"listing_membership_change","evidence":"W1"}`.

W1 is the exact same-board page-two observation: 25 old rows at 98 ms followed
by 14 disjoint rows at 347 ms, with total 39.  The recipe verifies the witness
hash and exact scope/failure fields before generating anything.

## Transformation

`repair_recipe/acquiretm_membership_recipe.py`
`d6465801a0932a85895441914170d11e0258e642927f2d3349e2d044dfebc377`

It replaces only the production pagination readiness wait.  The old
`document.body.innerHTML !== old` gate becomes the existing bounded predicate
that waits for a new same-origin, same-detail-path numeric ID absent from known
listing membership.  The existing post-wait parser, same-source check, total,
overlap, count, detail, employer, full-description, and reread guards are not
changed.  The delayed-transition diagnostic helper remains in the baseline as
pre-repair evidence.

The builder returns `source`, `diff`, and `receipt`; it does not write the
candidate or install anything.  Unsupported, alternate, or additional
selection values fail closed.

## Generated review pins

- Candidate source output: `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`
- `repair_recipe/proposed.patch`: `ce042dffa0addfdbb04e14e450d6e5ae3979d2c881bd1ff9bf9c8173ce749abc`
- `repair_recipe/build-receipt.json`: `b4f4494becefbdf0aa8ceb42d6f073d04181b0f9155912db2edb4398a8bd1083`
- `repair_recipe/test_acquiretm_membership_recipe.py`:
  `5c8e73667ed66ad26a7c989ab3da9dc47bc6940210164c322499a9c6dd81e6f0`

## Offline checks

`python3 -B -m unittest discover -s repair_recipe -p 'test_*.py'`:
`Ran 3 tests ... OK`.  The regression calls the generated candidate's real
`inventory(page)` method through a synthetic browser callback and asserts the
exact same-board membership predicate, prior IDs, and normal timeout.  A
private local raw-fixture check pins
`/tmp/jsh-s5-amphenol-raw-fixture/result.json`
`acc0ba9b1fa8855dc588cc28d9911bf4ab6fa58816cba426e8ca9954437e4bdf`,
then proves the actual pre-click/premature 25-row membership is unchanged and
the late 14-row membership is disjoint before the generated callback completes
the 39-row inventory.  Its raw HTML is neither copied into this capsule nor
included in a receipt.

`python3 -m pytest -q tests/test_acquiretm.py tests/test_outcomes.py
tests/test_scrape_outcome_producer.py`: `56 passed in 6.97s`.

No network, scheduler, dispatcher, data, production repository, service, or
model request was used.
