# Independent final AcquireTM Retry-After review

**ACCEPT the exact staged runtime transport correction.** Seven focused offline tests passed. Both an explicit numeric hour and an HTTP date produced UTC deadlines. The exact adapter composed with the normal Company retry loop made one detail request, zero Python body calls and one Company attempt for either HTTP 429 or 503 with a one-hour Retry-After. Short delays retain bounded retries. The diff from the first staged variant changes only over-budget responses to the existing blocked classification. Ordinary short 5xx failures retain the prior partial classification.

The original adapter made three requests and three Python body calls for the 429 fixture. The first staged variant fixed 429. It still classified a long 503 as partial and the actual retry loop attempted that Company twice. Those results and the first-stage report are preserved. The final fix prevents that default repeat. The installed Playwright request driver still buffers the network response before returning status and headers. The correction avoids application retrieval of that body. This review made no provider or production calls and does not qualify the separately held generated recipe candidate.

| Artifact | SHA-256 |
| --- | --- |
| Final adapter | `63f7a91af1185bcb171cb70a8a93e7097d46519bd43f1a198911acc84a27f2c8` |
| Final maintained tests | `9729563bb49716ce9236b70ad6b05c636dd4999bd17dd7778e7e2e7df2552841` |
| Original adapter | `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61` |
| First staged variant | `d8268569cf3e911a7311a61c92234d56ef0382532c52ab774669728dce278528` |
| First independent report | `19057185c03ce29480baa82749fe50d9837e1884a4b67f2a3058ddcef5dae1b9` |
