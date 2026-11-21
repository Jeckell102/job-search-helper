# Amphenol’s second exact qualification attempt

Chris explicitly requested a bounded restart after the provider cooldown.
Root verified the exact automatically generated wrapper, evaluator,
manifest and recorded first hold. The separate private run started at
18:20:47 Eastern, approximately 91 minutes and 53 seconds after the first
429. This was one independent invocation with unchanged quality criteria.

The initial listing contained all 39 posting IDs. Its membership digest
matched the preceding attempt. The evaluator observed 35 independent
HTTP 200 detail responses and stopped at the first new HTTP 429, at
18:21:54.230019 Eastern. Retry-After was 3,600 seconds. No provider contact
before 19:21:55 Eastern. There was no final listing reread, complete
description confirmation, or release approval. No automatic replay.

| Private evidence | SHA-256 |
| --- | --- |
| New execution preparation | `7a59adb41005f4e5ea61821436203b54a30de3c1d90512ccf0c9e8a252ea13ac` |
| New structured evaluator log | `1d33814c36798fe34942fb8b85e48849b5f94e5c997e39d09b7e08673a26a5c7` |
| Exact unchanged evaluator | `a6b23ca6c41f7552e1990870870a022da846a1c6e844bcaf8d146b3a50e98e32` |

Keep the generated wrapper and its held proposal as the same exact
identities. A second full attempt after a documented cooldown still could
not verify all descriptions. A later run needs a credible window or a
separately accepted provider-respecting approach with the same complete
coverage and source-binding requirements. Raw project logs remain under
`/tmp/jsh-amphenol-qualification-retry.XzvXJ1qr`. No app release, Sheets
write, production service change or new Jetson inference occurred.
[Independent public retry QA](S5_AMPHENOL_POST_COOLDOWN_INDEPENDENT_QA_20261121.md).
