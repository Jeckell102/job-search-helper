# Sprint 6 native source-only composition recheck

**ACCEPT for staged source and fixture scope.** The source entry supplies the real idle predicate as a required callback. The owner passes it through and the installer invokes it under the canonical scraper and writer locks, after checking the exact predecessor and empty queue but before sealing the record or writing PREPARED. The earlier lock-gap finding is closed. The prepared package now has mode 0600 and retains its exact bytes.

The existing composed fixture uses competing flock attempts to verify both locks, asserts refusal on the simulated unfinished-work predicate before any record is written, checks fresh staged admission after the pre-PREPARED recovery, and checks that an undrained route blocks rollback before source changes. The coordinator reported the fixture passing and an actual read-only BEFORE phase. I reviewed the checked bytes and fixture assertions without rerunning the host entry.

A separate readiness-only proposal can pin this review and the historical qualification as evidence. The final entry accepts the readiness schema only for ready. Apply and restore still require the full approval schema. Source acceptance and readiness confer no authority to apply the package.

- `native_window.py` `78d07bcd6296b0e11d3e80026a22372a89388a2fa8de015b965915881ca6c7ad`
- `start_observer.sh` `bd41e03929be48646cebf8698562f686d8d1e72e38af88e656d32e924db0ea14`
- `native_source_release_entry.py` `a50c09317eddf7bffec5cf18b86d5a9c4f746fd868985dc0cafe70d4a541ab6f`
- `maintenance_source_owner.py` `155f63b7f7048f26bf3acbefe1b899e51433e514ec216a4d4907dada93cd72ed`
- `native_source_advance.py` `7297735fefe0dfee30b4ed47aad39d3f75ab84b4cfee1a774b631f606a42b412`
- `PREPARED_PACKAGE.json` `9e6a0d04a5d932dff086f30a8783b9d0c452a89a2d80ff768ec6e960ac2ef5a4`
- `test_native_source_advance.py` `145585023d1104d0db0c7c18bde684172873babe6c1833a1bfd00bc7d92f0fa3`
