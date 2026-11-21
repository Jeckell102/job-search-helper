# Sprint 5 Amphenol candidate public live test

The exact candidate at `/tmp/jsh-s5-amphenol-recipe-live-candidate` passed
its bounded two-run live evaluation at 00:59 Eastern on November 21. Both
fresh normal `ats.fetch_inventory` calls returned complete. Each initially
read 25 plus 14 same-employer postings, read and checked all 39 full
descriptions, and reread the same two pages through the real adapter. Both
runs had the same member, URL and description cohort digest
`728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b`.
The observed board count is point-in-time evidence.

- AcquireTM source `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`.
- Source/configuration vector `48f80b004f69fe4015f711e7f235176ffb69742162010091e017d21143dd1cae`.
- Evaluator SHA `692cf7db590f53524bfa1fc08d298c7f1bb842b682596eef799a851e85ed42ad`.
- Complete private JSONL `4a112649009f43322722be73cee16b52a53224d96b8142b65f7d8c0d53f2bc85` at
  `/tmp/jsh-s5-amphenol-candidate-live.hrygHxP7/evidence.jsonl` with zero exit
  and empty stderr. Runtime 05:57:21 to 05:59:48 UTC.

Independent source QA accepted the exact builder and candidate before the
live run. Independent evidence review also accepted the bounded capture.
It recomputed all four listing unions, exact detail identities and employer
labels, and matched all 39 hashed descriptions across the two runs. Full
normalized descriptions were 3,493–6,386 characters. The evaluator compared
the complete normalized JSON-LD bodies with returned descriptions while
running. The saved log contains description lengths and hashes.

Release precheck compared all 243 application `.py` and `.json` files by
bytes and mode. Only `acquiretm.py` and `ats.py` differ. The installed source
tree SHA is `7f556997f9296433756bf2d825221b8c33e2a1665c39362ca619829c26bf7dad`.
The candidate source tree SHA is
`24aa9e2d05398555bb738180d59eb075f118783aa3f9400cde361a48f4d9b5b3`.
These source digests do not replace the complete qualified runtime vector.

This was an isolated public test of the selected candidate. The installed
repair, authenticated event-to-generation, qualified release, fresh scoped
retry, and synchronization checks remain open. Production and Google job
data were not used.

[Recorded model choice and build](S5_AMPHENOL_RECIPE_CHOICE_20261121.md) ·
[Exact candidate source QA](S5_AMPHENOL_RECIPE_SOURCE_ACCEPT_20261121.md)
