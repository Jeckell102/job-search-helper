# Independent operator canonical-source forward fix

ACCEPT the staged forward fix at the pins below. This covers future operator recipe source admission and candidate materialization. It does not recover the existing paused live task, deploy the source, execute inference, validate a provider, or authorize a release.

- Stage: `/tmp/jsh-operator-owned-bridge.xu59ooer`
- `dev/wrapper-coder/tools/host_server.py`: `5abe835b6b550f3bb81a7c787e97382910ce1d882687521c60e3e8ec630a37ad`
- `dev/wrapper-coder/tools/test_amphenol_operator_enrollment.py`: `88d21c45af5268b139c3f95d8c0afb447b868add878053bb65b41cefc9972976`
- Unchanged choice input: `f9014988ab91f65cc8060fe0b358920fadb4feb62f3df70b47675eb7898cd426`
- Unchanged candidate publisher: `126b2d4c29e4aa7a26acd0f7f00d813031475bfb7fe07bb30920513c0daf67ae`
- Unchanged deterministic recipe: `e753da1c44d2bafe8b1d1ce8a5954fd23c113c3eeeced11fa5a2592d8854479a`

The exact host diff from the accepted prior bridge adds a hash import and methods only on `OperatorAmphenolRecipeEnrollment`. Existing Company-event class behavior remains unchanged. The operator `_read` validates the canonical installed target's exact compiler source hash before entering the owned choice reader. This runs before pilot promotion and before the coordinator's inference branch. `build_candidate` rechecks that source and current owner, exact durable receipt, pilot ownership, pause state and deadline under the established owner scope, then supplies the canonical root to the existing isolated candidate publisher. The compiler independently hashes the exact bytes it reads, closing the gap between host precheck and compilation without relaxing its accepted source pin.

## Independent composed proof

`python3 -B /tmp/jsh-operator-source-forward-qa.IbK2OWAR/run.py`: **7 passed in 1.26s**, comprising six maintained cases and one independent end-to-end disposable case.

The independent case uses a real normal operator request, typed AcquireTM page fixture, actual local settlement and dual outcome receipts, actual host catch-up and Coordinator promotion/pilot admission, actual isolated workspace creation and local Git, and the unchanged candidate compiler/publisher. The stale queue-base fixture contains the exact previously observed adapter bytes `88893583bb01ed0b8878020d9b71ddb9043bbfcdb70d6e0eb6b2475bc8855392`; its isolated task retains those bytes. The canonical source is a separate private copy pinned to `a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61`.

Verified results:

1. Wrong canonical source holds at `HELD_RECIPE_OWNER`, with zero tasks and zero inference receipts. Returning to the accepted canonical source admits one isolated pilot even with the old task baseline.
2. A synthetic delivered model response is recorded using real local session/reservation/control-binding/finalization APIs, yielding one COMPLETED accepted W1 choice. No model transport or worker thread is constructed or called. Baseline-passed/inspect posture is explicitly seeded as fixture setup; no claim is made that the stale task's baseline tests were run here.
3. Canonical source drift after that completed response causes `build_candidate` to refuse before any candidate exists. The completed receipt is unchanged.
4. Restoring the approved canonical source produces isolated candidate hash `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d` through the real unchanged compiler, despite the active coding workspace still containing the older baseline. A second identical call returns the same candidate.
5. Canonical source, old task source, completed receipt, calls/sessions/tokens and one-pilot controls remain unchanged by build/replay. The existing restart test also preserves one task and receipt.

All writes occurred in private fixture directories. The one read of the prior selected live task's non-sensitive source file supplied only the exact old baseline bytes; no live application import or database access occurred. Audit hooks deny sockets/shells and all subprocesses except fixed local Git init/add/commit with hooks disabled inside the private fixture. Canonical production source, queues, model services, Sheets and task state were untouched. The retained live-task recovery remains a separate required action.

Evidence: `test_forward.py`, `run.py`, `RESULT.json`, and `HOST_RESULT.json` in this report directory.

- `test_forward.py`: `d4444c1176695ffa2bfd445b49f57a66322a423ff8b7cce0268e4a5166a01ac7`
- `run.py`: `74c9c4dd98b2f3c16ef2259c22b0c719f257c3bb1fedd1d4ec9c9769c38a338e`
- `RESULT.json`: `5819eecb4fe2b9f80ebf3baa13eea851e522d672959e5b6e42d768d3e8ccefaf`
