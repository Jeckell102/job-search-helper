# Amphenol candidate materialization: independent live failure diagnosis

REJECT live candidate completion; the task correctly stopped before producing a candidate. The triggering defect is a coordinated source-baseline mismatch, not an invalid or incomplete model choice.

Task: `WRAP-6a3a372032`. Read-only inspection of the exact selected workspace and exported checkpoint/receipts found phase inspect, mode review, PAUSED_ERROR, baseline_passed=true, calls=1, sessions=1, max_sessions=1. Failure: `Source differs from the accepted typed pre-repair baseline.` No `recipe-candidate` directory exists.

## Exact source cause

| Source artifact | SHA-256 |
|---|---|
| Production `src/job_search_helper/acquiretm.py` | a95953afe2bc10138714f6b11af22572b17ab344bf61d78b834647895025aa61 |
| Task `repo/src/job_search_helper/acquiretm.py` | 88893583bb01ed0b8878020d9b71ddb9043bbfcdb70d6e0eb6b2475bc8855392 |
| Wrapper `queue-base/src/job_search_helper/acquiretm.py` | 88893583bb01ed0b8878020d9b71ddb9043bbfcdb70d6e0eb6b2475bc8855392 |
| Wrapper compatibility `repo/src/job_search_helper/acquiretm.py` | 88893583bb01ed0b8878020d9b71ddb9043bbfcdb70d6e0eb6b2475bc8855392 |

The task's baseline manifest pins the older hash, and its assignment baseline digest is `0645548733f2866dbb1b1eed03c8df36f88b9a1af5d6d5c0eaee12eb8a8ac18a`. This is an unchanged, stale baseline copied normally into the isolated task, not unexplained task-source drift.

The old adapter lacks the typed pagination observation code present in the installed adapter. `coordinator_workspace.batch_source()` selects the wrapper queue-base (lines12–19); `workspace()` copies its pinned files (lines35–55). `host_server.AmphenolRecipeEnrollment.build_candidate` supplies `coding_tools.root()` (the isolated workspace). `amphenol_recipe_candidate.save_candidate` reads its target (line16). `acquiretm_membership_recipe._transform_source` requires exactly the newer a95953af hash (lines88–90). Production installation did not advance the frozen wrapper baseline.

## Existing choice

The selected exported inference list contains exactly one receipt, request `2b444fe8f48a4c6e9638f1c6a7acb40c`, status COMPLETED, accepted choice `{summary: W1, next_action: listing_membership_change, outcome: phase_done}`.

- Prompt digest: `61070533ede481c8f8a7170127c2b8a70274a193a5d02302f937214489976bb7`
- Tools digest: `bb3967446fe84756a1cc422a7a27d93fad2cb1c28a0b6590c60aeeae98b062a5`
- Response digest: `eaa91c9a741861863d77142cabc01f034a7767f9f43465fdbce4bb1b06d0d514`

The closed choice prompt describes the typed W1 observation and strategy; it does not include the stale source bytes. The existing choice is therefore potentially applicable to deterministic materialization against the exact approved compiler input, subject to authoritative receipt and current owned-input equality. This lane did not independently establish that final current-owner equality. Root owns that separate offline reconstruction.

`Coordinator._step_owned_recipe_choice` (1095–1149) already skips inference if a receipt exists, then requires exactly one completed accepted receipt with identical prompt/tools digests and an unchanged owned input. However, it returns while paused. Ordinary resume is not the answer: `Coordinator.command` and `Store.commit_activation` reject sessions >= max_sessions, which is true here. No budget or receipt should be reset to force it through.

## Smallest replay-safe repair

1. Preserve the failed task, old workspace, old baseline and completed inference as immutable evidence. Do not update the old workspace or global queue-base to conceal the mismatch. Keep the strict a95953af compiler requirement.
2. Before any future choice dispatch, validate/capture a recipe-specific source input at that exact approved source hash, bound to the current approved source deployment and same owned observation. Fail before spending inference if the source input cannot be supplied. The existing task's generic baseline remains historical.
3. Add only an exact post-inference candidate-materialization continuation for this owned recipe: same selected task/repair, authoritative completed choice, current two-sided source/receiver custody, exact same prepared prompt and tools digests, no unresolved inference, appropriate owner/control leases, and separately frozen approved compiler source input. It must neither resume a worker nor gain any inference/session budget. Reuse the deterministic `save_candidate` and identical-existing-candidate behavior, with a durable completion result only after its artifact receipt is reread. No deployment or remote publication authority is added.
4. Prove on a copy of these exact retained inputs that old-source input still fails before candidate publication, approved input builds with the same receipt, a replay returns identical bytes, a changed owner/choice/source holds, and all inference counters/receipts remain unchanged. Root is performing that reconstruction; no duplicate execution was done here.

This is a narrow host coordination repair. It does not justify broad queue processing, a second model call, relaxed source pins, changed frozen provenance, or treating an offline candidate as a live-qualified release.

## Evidence and limits

Live source/read-only exported evidence pins:

- `checkpoint.json`: `893ec953a9e864667b38f9e41410f6cac0f1ce4bfd52ead6f1b40537d4deb310`
- `inference_receipts.json`: `95d867fc3c0dcd56dbac53e94b62c0f4fc2bd187c49bf0535e35763550f31136`
- `receipts.json`: `a91138ac7af035cac035f4df41d237f42f031492db2cf2367fc81066a44a00ac`
- `repo/baseline-manifest.json`: `351965c5bd49551c9ad6a807ef7abffe1071efe70073d75a3e8eb9f7cf62a26c`
- Installed `host_server.py`: `137563add244929e36f53dc0e4b87f2f9a9faaeb22a799102c89e9b939b79eae`
- Installed `amphenol_recipe_candidate.py`: `126b2d4c29e4aa7a26acd0f7f00d813031475bfb7fe07bb30920513c0daf67ae`
- Installed `acquiretm_membership_recipe.py`: `e753da1c44d2bafe8b1d1ce8a5954fd23c113c3eeeced11fa5a2592d8854479a`
- Installed `coordinator.py`: `dcf6f14ea4ff15e6c221ff3f46c29523419d931dfbf0dffe6e2edd6b0f427a91`
- Installed `coordinator_workspace.py`: `c8b56ea7aedd7c9af5bcae87ff072ddf286f45cd7cb46fa58ee1e03c3be6f107`
- Installed `coordinator_store.py`: `9f0a84a626fcf910f24233759ff940ff68db81c97b9b0e7096a3d4b0580ea835`

A single raw SQLite `mode=ro` open of canonical `tasks.sqlite3` failed with `unable to open database file`. No retry, escalation, constructor, lease, write, or cause attribution followed. The receipt/state observations above are from pinned exports, not an independently certified current database row. Root's report of a real 25/39 observation and one sender/receiver receipt is context; this lane did not repeat those live reads. No network, model, provider, Sheets, service, task-control or source mutation occurred. Only this private report was created.

## Separate retained-choice reconstruction

After this diagnosis, root completed `/tmp/jsh-amphenol-retained-choice.ehpkrf0l/RESULT.json`, SHA-256 `322f6f9acbff468923c80996f10b4273ec32617c05f875b2cab052339df68692`. I independently read that result and hashed its candidate. It records the same task, outcome, single completed inference receipt and approved a95953af source; candidate hash is `895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d`, matching the independently hashed candidate file. Its status is OFFLINE_CANDIDATE_FROM_RETAINED_LIVE_CHOICE, with inference_replayed=false and production_state_mutated=false. Root separately reported exact prompt/tools and receipt reread equality. This supplies a concrete retained-choice continuation artifact; it does not repair the production task or turn its paused state into completed acceptance. The forward pre-inference fix and eventual exact operator recovery remain separate owned work.
