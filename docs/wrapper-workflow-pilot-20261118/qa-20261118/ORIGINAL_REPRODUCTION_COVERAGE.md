# Original finding reproduction coverage

The original `check_*.py` files are preserved as historical diagnostic artifacts. Some print buggy observations and exit successfully; `check_scheduler.py` hooks an internal pilot setter that the atomic transition repair removed. A zero exit or obsolete-hook timeout is not accepted as QA evidence.

The original failure scenarios were converted into assertions against the repaired public commands and transaction boundaries. The clean-installation host suite executed all of these modules (272 test executions, no failures, resource warnings treated as errors). Fresh final reviewers must inspect this mapping against the original QA report rather than treating the test count alone as coverage proof.

| Original finding | Current executable reproductions |
| --- | --- |
| 1: individual pause overwritten; unrelated tasks claimed | `host/test_campaign_isolation_qa.py`: explicit pause/exclusion, campaign ownership, unrelated queue isolation and restart |
| 2: concurrent pilot/autopilot and failed pilot slot | `host/test_control_transitions_qa.py`: competing public commands, preparation races, failed activation rollback and separate Store instances |
| 3: contradictory objective/identity; duplicate company imports | `host/test_identity_integrity_qa.py` and `host/test_identity_registry.py`: canonical worker packet, immutable bindings, cross-batch conflicts and retry ownership |
| 4: unassigned writes; replacing assertion with pass | `host/test_scope_acceptance_qa.py`: exact file authority, immutable assertion bundle, edited source proof binding; `verify_real_acceptance.py` additionally uses the actual OS sandbox |
| 5: pause during budget preparation still dispatches | `host/test_inference_reservation_qa.py`: budget/prompt pause before reservation, callback count zero, post-reservation pause behavior, uncertainty and accounting |
| 6: no durable completion; misleading status | `host/test_campaign_completion_qa.py`: exact current-company denominator, persisted revisions, named exceptions, real evidence binding and truthful actions |
| 7: direct-run lock bypass; untracked root inputs | `host/test_ownership_baseline_qa.py`: public direct run, separate process owner, complete source/fixture/root-input pin, Git tracking and drift rejection |
| 7: incomplete deployment source set | `test_release_bundle.py`: required workspace and Jetson mirror, dependency preservation, missing/substituted/extra files, copy races; `test_paused_rollout.py`: rollback and abrupt interruption |

`verify_two_company_rehearsal.py` verifies the combined offline workflow with real guarded edits, Git folders and OS-sandbox tests, using simulated model and public-page responses. It does not establish live integration success.

Deployment-controller QA, independent final staged QA, paused installation checks and final GitHub parity remain separate gates. This coverage note does not mark those gates complete.
