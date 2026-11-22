# Observation-only evaluator and release entry QA

## Evaluation fixture

**ACCEPT for the exact normal adapter’s offline behavior.** The corrected evaluator explicitly measures its own observed transport calls, retains exception-path evidence, verifies detail and final reread spacing, and binds the prepared source and effective configuration. The evaluator’s hold check does not independently count a later failed or successful listing start. In the reviewed exact adapter, the first qualifying detail hold exits the listing/detail block before the final reread. The fixture independently confirmed that behavior. Pending coordinator disposition on adding the explicit begun-listing assertion before live use.

- Evaluator SHA-256 `f8ca04f9ec6e9c0b53bc4398595a0c57edb6e248e725216dbf73f35ca002b38b`.
- Maintained tests SHA-256 `5ba3c346e5c25088f4bcdce669281d861ab5572e66969a2071247748083549d4`. Five passed.
- Independent test SHA-256 `954f93ed2484e6bd47f3f7ab52dbeecde1eb98ca28659267f827118392debe37`. Four passed using the actual staged AcquireTM module with fake browser, transport and time. The successful fixture observed detail starts at 0 and 15 seconds and final listing at 30 seconds. The HTTP 429 and the explicit long HTTP 503 each produced a terminal hold with 3600 seconds recorded, one detail request and no final listing. The synthetic unpaced 0 and 3 seconds control held.
- Preparation raw SHA-256 `7e0ca2034fc3be3003edce8bf77375ce0f6d74ce8754ab8822dd770b1378fa0c`. The actual private candidate config/source measurements were retained, and the declared shared dependency result was substituted through a fixture that required both pre- and post-measurement at its private stand-in path. Synthetic cohort constants drive the fixture only. Provider and installed dependency validation require their separately authorized evidence.

Initial rejection, original files and both exact failing probes remain under this directory.

## Explicit release entry

**ACCEPT at the entry boundary.** Entry SHA-256 `5247f191d02598f760c49e13f6b7e61aef62762b9f74459078d1778ed5f91ca7`. Four tests passed using the actual owner parser with the native loader replaced by a stopping fixture. Missing owner held for every action and both COMPLETE-only choices. Missing, symlinked and changed candidate paths held on new preparation or apply. With exact owner approval, restore and COMPLETE-only reached the stopped loader even after the test removed candidate, preparation and patch. The existing downstream COMPLETE-only delegate still calls its candidate verification and therefore cannot resume through a missing candidate. That delegate is outside entry-gate acceptance.

No public dispatch, service action, production data store access, or edits to the candidate took place.
