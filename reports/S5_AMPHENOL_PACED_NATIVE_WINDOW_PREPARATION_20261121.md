# Amphenol -06 observer and idle prerequisites

Prepared 2026-11-22T00:43:23.413357+00:00 in a new private mode-0700 directory. Source and read-only host status only. No sudo command, observer socket connection/start, service change, application/database call, provider, Google or Jetson action was performed. The startup script is prepared, not executed; root owns qualification, the user-facing request and release.

## Verified preparation

- Exact adapter: `/tmp/jsh-amphenol-complete-activation-resume/native_window.py`, SHA 9e51c5197f4682fe653685a690481f98645f056d0229d4dfde4ad7ec36494b91.
- Both `/run/jsh-s5-amphenol-release-06` and its observer.sock are absent. Old `/run/jsh-s5-amphenol-two-tool-05` remains, but its socket is absent; it cannot supply -06 authority.
- Existing observer source `/home/chris/.local/state/job-search-helper-maintenance/s5-operator-trigger-20261121-03/site-source/ancillary_process_witness.py` measured SHA f4a82eaed30a46b507c525875418d4ec471b8b9147036adc67061970a5e70819.
- New script changes only the old -05 directory, maintenance ID and duration: `/run/jsh-s5-amphenol-release-06`, `s5-amphenol-qualified-release-20261121-06`, 1800 seconds. UID1000, listener18789, exact helper PIDs1249/4467 and the same seven route spellings are preserved. It refuses an existing observer directory; it does not remove or reuse historical state. Source and installed-copy hashes are checked by the existing recipe.
- Original source `serve` lines186-199 permits 1 through3600 seconds; parser line250 defaults1800. Therefore1800 uses the existing duration policy; no observer source modification.

## Native idle snapshot

Independent actual host read at approximately19:42 Eastern: wrapper active/running/enabled PID653884; bridge active/running/enabled PID612085; scheduled sync service inactive/dead/disabled PID0; sync timer inactive/dead/disabled. Kernel read at approximately19:43 found no held scraper.lock (inode28717085), writer.lock (28706711), or deployment.lock (29130351), all device64513. No locks were acquired. next-scan.json is absent.

Coordinator separately verified current helper identities (1249 sd-pam,4467 ssh-agent), only expected wrapper scheduler/supervision held locks, installed retirement-aware `_cycle_views` effective unfinished cycle list[] and no active application release. These cycle/retirement claims are **coordinator-checked**, not an independent SQLite read in this lane. The intentionally retired historical raw cycle is not reclassified Complete. This lane deliberately did not open live SQLite or copy job data.

The first sandboxed user-bus probe was denied and its process view was a separate PID namespace; that result was not treated as native evidence. The subsequent authorized read-only host service query succeeded. A broad preliminary process text filter also matched its own inspection shell; no scraper/worker absence claim is based on that filter. No automatic approval rejection or UI/display failure occurred.

## Time budget

Old900 seconds leaves only5–7 minutes after an8–10 minute retry. The existing command ceilings for bridge close95 seconds, wrapper close115, wrapper restore75, bridge restore75 and two12-second readiness windows total384 seconds before additional readbacks, file exchanges and handoff overhead. Fifteen minutes is therefore not an adequate conservative envelope for the planned10-minute retry.

Use the prepared1800-second observer only immediately before an already-qualified release, after all private preparations and current state checks. It provides20–22 minutes beyond the estimated retry and about13–16 minutes after the summed service command ceilings. These ceilings are illustrative sequential allowances, not a measured native runtime guarantee. Network slowness or a held application can outlast any estimate; qualification/exclusion/restoration must continue to fail closed if fresh authenticated observation expires. Do not start it while awaiting a long public qualification. Do not automatically extend, replace, delete or reuse its directory from this script.

## Current wrapper-scope measurement recipe

Root's already accepted pinned loader supplies the correct Controller. In the same ordinary chris host identity (no sudo), isolated Python with bytecode disabled:

```python
# After root verifies release_entry.py and invokes its accepted verify_tool_origins():
loaded = verify_tool_origins()
wrapper_scope_sha256 = loaded['controller'].unscoped(
    Path('/home/chris/job-search-helper_old/dev/wrapper-coder/tools'), set())
```

The currently inspected entry is `/tmp/jsh-fresh-amphenol-qualification.FdVVPAdT/release_entry.py` SHA `e83730be7e69dce3e5a787b61d42c70603859ce1dad8df850d8fcc658d96aecd`. Its `verify_tool_origins` checks exact staged/current/historical origins and requires the installed isolated interpreter. Use its reviewed loader, not an unpinned import from cwd. This measurement is read-only and takes no application lock, but must run on the real host identity because Controller includes inode/device/mode/UID/GID and filemtime as well as content, while excluding pycache/pyc. Pass the newly independently reviewed digest via `--wrapper-scope-sha256`; NativeWindow repeats the exact measurement in its admitted window. Do not reuse the older -03 fingerprint or substitute a content-only tree hash. This lane did not measure a fake sandbox fingerprint.

Next action belongs to root: once qualification/release prerequisites are accepted, request the exact prepared script, observe its real ready line/socket and freshly confirm native readiness before entering the guarded window. No request was sent to the user by this lane.
