# Sprint 4 alternate checkout exchange QA

**PASS for the existing disposable regression suite. HOLD for host acceptance.** Tested the byte-identical source from /tmp/jsh-s4-host-exchange.MTKXfv6I, SHA-256 `0103a6643062b9200ca638d9f07b1396690f58925dda091c8380d36117eb0ac5`. The supplied suite passed **15 of 15**, with no failures or skips. [Staged source](/tmp/jsh-s4-host-exchange.MTKXfv6I/host_exchange.py) · [Existing fixture suite](/tmp/jsh-s4-host-exchange.MTKXfv6I/test_host_exchange.py)

Interrupted prepare, close, restore, and journal synchronization recovered cleanly in the covered fixture cases. Replay finished the expected ordered exchange and refused unexpected placements. Restore required accepted terminal evidence and the same proof on replay. Default host-write refusal and policy, lock, and namespace mismatch refusal also passed.

Host acceptance still requires continuous exclusion of changes to the named exchange endpoints and approved policy while a transition is in progress. The staged operation can detect some changes only after a swap, and the terminal verification callback precedes the reverse exchange. The ordinary regression suite establishes controlled replay. Actual host routing, parked-path exclusion and power-loss durability remain separate gates. [Exchange and restore boundaries](/tmp/jsh-s4-host-exchange.MTKXfv6I/host_exchange.py:395)

Execution used the supplied fixtures in a disposable source copy. The staged candidate, production, job data, Google Sheets, services and GitHub were untouched.
