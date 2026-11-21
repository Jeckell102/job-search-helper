# Fresh Amphenol application qualification checkpoint

Root assembled the actual automatic output for `WRAP-11dc97a3dd` in
`/tmp/jsh-fresh-amphenol-qualification.FdVVPAdT`. The existing release
projection reproduced the installed source and configuration measurements,
and proposed exactly one changed file, `src/job_search_helper/acquiretm.py`.
The full 256-member evaluator vector matches the previous one complete
public observation, including four inactive maintenance marker files that
the evaluator counts. The fresh manifest belongs to the live -05 request,
not the old manually reconstructed candidate.

| Input | SHA-256 |
| --- | --- |
| Full public source vector | `7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea` |
| Canonical fresh manifest `REL-53592bb86b62492840c58267` | `9b02e2bb924666d240ec666d5ad6292def584e8f7155f89bfa3c465999fc323e` |
| Restamped evaluator | `a6b23ca6c41f7552e1990870870a022da846a1c6e844bcaf8d146b3a50e98e32` |
| Frozen execution preparation | `dbf3196f8ff5e2467ae00a1b7ec0c7cf4afcfd66996f5ee70cf697fba40ac7ea` |
| Provider-hold structured log | `42da27f2769e03ea7687da9e489c6e1aa446369a7b591a8c5f4ea90dbb71a482` |

The independent live evaluator made one normal company-only run at
16:47:52 Eastern. It verified the initial 39-listing pagination and saw
32 successful detail responses, then stopped on the first actual detail
429. The received Retry-After was one hour. Honor the terminal event time
16:48:54.201935 Eastern and do not contact this provider again before
17:48:55 Eastern. A future separately recorded bounded run still needs
an affirmative readiness decision. There was no complete final reread,
full-detail confirmation, approval or installation. No additional provider
request or retry was sent. [Independent public QA](S5_AMPHENOL_FRESH_PUBLIC_INDEPENDENT_QA_20261121.md).

While the provider is held, root installed no tools. The private loader
loaded the seven accepted tools from a clean source-only import path and
retained the installed host and controller dependencies. An initial SQLite
read reported idle controls. Independent QA showed that the same read may
materialize SQLite sidecars, so root removed it from package inspection.
The later native window owns the actual quiet-state proof. Work on the
existing guarded release window and recovery checks continues privately.
[Native dependency review](S5_AMPHENOL_FRESH_NATIVE_RELEASE_MAP_20261121.md).
