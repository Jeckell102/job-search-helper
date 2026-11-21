# Independent QA — -06 native window adapter

Verdict: **ACCEPT — source/disposable maintenance adapter only**

This is not authority to invoke a native window, qualify the candidate, install
the application candidate, or release it. The current public qualification is
held on provider rate limiting and remains outside this acceptance.

## Exact reviewed artifact

- Adapter: `native_window.py`
- SHA-256: `8f40d99f3718cee74cb5d522e648f41befde5ca1f3a4282650b711fc555ef069`
- Re-run disposable suite: `9 passed` under
  `python -B -m unittest -v test_native_window.py`.
- No service, observer, provider, Sheets, application database, lock, or
  source action was invoked by QA.

## Actual custody checks

The adapter's pinned read-only predecessor chain was verified against the
actual private records:

- -03 controller: `0f2543519bbd7dcf9737533c3e2caebf62e2e8a8cc1574d09287e21055ed1793`
- -04 forwarding receipt:
  `e07eab1cf86378f6b6fe0055763a83bb212b52626774fb6d0fe0366f311b7dc3`
- -05 two-tool receipt:
  `60b29ffc98f4ef35399f9c9fdefe949f42f34b928a35b51e766dc0ba41d480cf`
- Sealed host-check archive:
  `c0bec31ab59dbdc1064e2ee7003b9aa68e115d5902c34e43ebbe75058bf2a53e`

The sealed ZIP contained the required `host_checkpoint.py`, `site_policy.py`,
and `host_exchange.py` members. The adapter checks those members against their
own pinned hashes and rejects loose copies.

## Safety properties covered

- No module import, constructor, or `ready()` call creates a fence, journal, or
  worker.
- A missing or nonmatching qualification callback stops before module loading,
  observer inspection, or native write behavior.
- The production path demands the two authenticated -06 observer helper
  checks both before entry and before recovery service actions.
- The only lock retained across the worker yield is the deployment lock; the
  disposable proof acquired the fixture scraper lock during the yield and
  confirmed it remained available.
- The bridge and wrapper are re-fenced on close/restore failure. Recovery
  never replays the worker, provider fetch, or source installation; it restores
  only the new exchange, bridge fence, and quiet-window/service state after
  exact journal/observer/terminal checks.
- Historical -03 policy, journal, terminal proof, and route evidence are read
  and pinned rather than rewritten. The fresh exchange uses a new private
  generation/control directory.

## Scope boundary retained

`qualification_check` is deliberately supplied by the root release entry.
This adapter verifies only its exact `{release_id, manifest_sha256}` result;
it is not, by itself, an independent public-qualification authority. The
application release handoff assigns the real qualification-owner reopening and
`require(manifest)` call to root. A native entry must use that real owner, not
a test callback. This is an integration prerequisite, not a source-only
adapter defect.

## Conclusion

No smallest source correction is required for the adapter's declared narrow
scope. Native activation remains blocked until the independent root entry
supplies a passing real qualification owner and a current authenticated -06
observer, and separately satisfies release acceptance.
