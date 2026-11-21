# Operator-selected bridge: narrow MuleLab deployment plan

## Verdict

There is no already-approved installer manifest that can install the current
operator delta unchanged.  The narrow **mechanism** is already approved: the
current `s5-owner-retirement-20261121-02` guarded maintenance-controller
successor route, with its existing installed-predecessor/current-pin,
parked-tree, marker, service-hold, exchange, verification, and rollback
behavior.  The prior Freeform and current 44-path retirement manifests are
not reusable for this payload because they deliberately reject additions and
changed endpoints outside their exact inventories.

This is a scope-policy dependency, not a reason to create a new launch gate,
data migration, package format, or broad installer.  Reusing the old exact
manifest would be an integrity failure, not a shortcut.

## Evidence

* The approved retirement schema is exactly 44 paths; every omission and
  foreign endpoint is refused.  Its accepted controller permits an
  `INSTALLED` predecessor only for its named consolidated/retirement schemas.
* The current selected-operator stage has three new application modules
  (`operator_selected_observation.py`, `operator_amphenol_fetch.py`, and
  `operator_amphenol_settlement.py`), changed application integration files,
  a changed launcher, and changed host/choice files.  At least its changed
  `runner.py`, `job-search-scraper`, `host_server.py`, and
  `amphenol_recipe_choice_input.py` differ from the approved -02 candidate.
  `scan_request.py` currently matches that candidate, so it should be omitted
  from the mutation list unless the release owner proves a different target
  baseline.
* The selected-observation source slice has independent acceptance only for
  the listed source/observation readback; its report expressly leaves
  settlement recovery, host delivery, and native activation to separate
  acceptance.  It is not deployment authority.

## Smallest route

1. Freeze one exact, nine-endpoint source inventory (the release owner's
   stated five application files, `job-search-scraper`,
   `release_admission_bootstrap.py`, and two host files).  First remove any
   byte-identical endpoint from the mutation set; retain an existing file only
   when both its before and after digest are required by the exact manifest.
   Record mode, owner, before/after digests, and whether it is an addition.
2. Construct one **new exact successor schema** by copying the current -02
   policy mechanics and adding only this nine-path manifest contract.  Preserve
   the existing 38-, 44-, and legacy schemas byte-for-byte.  Do not add a
   generic path glob or permit the unchanged receipt bridge as a mutable
   endpoint.  The predecessor is the actual terminal -02 `RELEASED/INSTALLED`
   receipt, not a relabeled rollback.
3. Independently test the new schema/policy on disposable paths: reject each
   omitted/extra/unchanged endpoint and wrong digest/mode/owner; prove the
   existing -02 predecessor is accepted only with its exact current protected
   pin and terminal receipt; prove install/verify/rollback restore every
   source file.  Re-run the package/launcher/bootstrap no-write probes and
   the two host-file tests on the exact final bytes.
4. Obtain the existing maintenance window, fresh protected-site/current-pin
   observation, owner/controller enrollment, and host/service/process
   exclusion proof.  These are the already required -02 deployment gates;
   do not add an operator-specific daemon, scheduler, migration, or service.
5. Invoke the guarded controller once with that exact sealed successor
   package.  It parks canonical imports, retains marker/holds through
   verification, then either records `RELEASED/INSTALLED` or restores the
   exact predecessor.  The deployment must not open Jobs, State, Inbox,
   Sheets, provider, or queue data for mutation.  No data migration runs at
   install time.
6. Only after installed-source and independent deployed QA pass, separately
   authorize one operator request/normal observation.  That explicit run—not
   the source deployment—is the first permitted data-changing action.  Broad
   queue, campaign, autopilot, generic outcome drain, retry approval, and
   release activation remain disabled.

## Real blockers/dependencies before step 5

1. Final exact pins and independent QA for all five application files, the
   launcher/bootstrap pair, and both host files.  Current source acceptance
   for the reader/fetch pair does not cover the settlement/host final bytes.
2. The narrow successor manifest-policy addition and its independent
   install/rollback rehearsal.  This is a genuine blocker: current accepted
   manifests intentionally refuse this scope.
3. Fresh -02 predecessor and protected-current-pin evidence plus the normal
   host/controller/service observer window.  A disposable rehearsal or stale
   baseline does not substitute.

No native service, source, data, lock, request, provider, Sheets, or network
operation was performed while preparing this plan.

## Inputs read

* `S5_RETIREMENT_MAINTENANCE_HANDOFF_20261121.md`
* `S5_RETIREMENT_MAINTENANCE_INDEPENDENT_QA_20261121.md`
* `S5_S6_OLD_INSTALLER_SCOPE_HOLD_20261121.md`
* `S5_S6_CONSOLIDATED_DEPLOYMENT_PREPARATION_20261121.md`
* `S5_OPERATOR_OBSERVATION_INDEPENDENT_QA_20261121.md`
* `/tmp/jsh-retirement-merged-release.RvLEs074/maintenance_policy/{installer,controller}.py`
* the disposable selected-operator stage and approved -02 candidate, hash
  compared only.
