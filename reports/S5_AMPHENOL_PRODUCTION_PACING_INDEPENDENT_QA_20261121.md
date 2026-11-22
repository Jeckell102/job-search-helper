# Independent Amphenol production pacing fixture review

**ACCEPT for the exact final staged adapter.** Eighteen tests passed on a private copy of the full old candidate overlaid with only `acquiretm.py`. A byte comparison confirmed the generated listing and posting routines were preserved. The maintained tests exercised the normal AcquireTM dispatch, exact board scope, parsed descriptions and employer, validated detail cache, successful detail spacing, final listing reread and short transient pacing. Independent probes used the actual normal Company retry loop with a disposable fixture engine and transport. Missing, zero and long Retry-After on HTTP 429 held without an automatic Company repeat. A long HTTP-date 503 also stayed blocked.

The original staged pin allowed the Company restart to start at clock 33, at completion of its last timed-out or short-503 detail. The intermediate pin correctly waited until clock 45 but could lose the blocked status if the browser close or Playwright exit raised after a 429. Both original failures were reproduced and preserved. On the final source both cleanup exceptions leave the first observed 429 and its provider deadline blocked with one detail attempt. Nonblocked partial returns still preserve normal retry classification and wait the full twelve seconds before the next Company can start.

The offline review did not start a real browser, call the provider or change any installed source or project files. It does not bind the staged bytes to a release or qualify a public run.

| Artifact | SHA-256 |
| --- | --- |
| Final adapter | `ac1b1e62ca139fcef47cae368ac25ebc56043a6d3133428ec2e97f22fdbc9e7c` |
| Final maintained cases | `6006ce80137e87c4d6dd66c61ee94b78288a823739da17201d608ad142ab1e2c` |
| Original paced candidate | `76fdd4ea6c0a48d057c32ed5f89190f2aff95b50b4c5be01ced7b0bc74e6f2c2` |
| Intermediate candidate | `5ae907179ccfccfab614d5e77b9a176ee1e739e2d97192a2cc4e922f1bb7111e` |
| Earlier failure report | `d48bcd371e4e39704b69327ff5ab176d259f27210ae710f78c7fb94e9a81eae4` |
