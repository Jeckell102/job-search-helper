# Sprint 3 Samtec admission audit

**HOLD. A genuine Ed25519 activation is necessary for the installed
retained exception, and it would not admit Samtec under the installed
rules.** The public retained command rejects 19 raw unfinished rows before
opening a repository or fetching. The normal scheduler correctly reduces
those rows to one non-superseded local blocker. Independently, that exact
blocker already includes Samtec in its frozen membership. The retained
exception deliberately rejects that overlap.

## Production evidence

- The durable company-only request is `operator-samtec-m1-20261119`, exactly
  `COMP-0739`, with operator provenance and no Company event. Its
  `REQUEST_WRITTEN` receipt matches the canonical request digest and
  Company. The current local Companies table has exactly one matching
  eligible unclaimed row, with the same source revision as the request.
- State, inventory and jobs SQLite reads used immutable read-only handles.
  Their three WALs were empty before and after the check. The effective
  local blocker is `CYC-B639C6D864EC`. The raw State has 19 nonterminal
  rows, 18 of which are superseded by the normal scheduler's rule.
  Independent of any workbook observation, the installed retained public
  command counts all 19 and rejects the scope.
- The handoff under `/tmp/jsh-s3-samtec-preview.viKaEwVh` is a mode-0600
  file in a mode-0700 directory. Its filename and exact bytes share the
  SHA-256 `13e7c2d1993d101d40bc3accc453e2b80d1b681843f7c6cd657e3f10c04c4885`.
  It contains only the manifest and required claims, without a signed
  envelope. Independently rebuilt the exact manifest and claims from the
  live local evidence using immutable SQLite reads, the artifact's original
  creation time and its expiry. They match exactly. The manifest digest is
  `f7f4435e2d581cae8c29561a20a9597e6f40e6c388936ee9fe8c6111f68d7f37`.
  Expiry is November 20 at 9:52:40 p.m. EST. The fresh artifact supersedes
  the earlier displayed manifest digest, which used an earlier preview.
- The frozen cycle is `In Progress`, has 800 members, and contains Samtec
  with stage `queued`. No matching retained Samtec inventory, sync plan,
  exact-local application, or directly bound publication receipt was found.
  The manifest's global dirty-cell check passed. Those facts do not change
  the installed membership rule. They are inputs to a possible separately
  reviewed queued-only policy, not proof that such a policy is safe.
- No retained exception, start journal, retained session, intake-dispatch
  database, or integration-release journal exists at the inspected
  production paths. No remote account or workbook was queried.

## Signature and signer authority

The retained path requires an active signed record. The installed activation
accepts exactly `{manifest,envelope}`, verifies the real Ed25519 signature
before taking the scraper lock, revalidates live evidence and signature
under the lock, and only then freezes the dedicated exception store. The
retained execution command rechecks the signed record and expiry. The
required signed claims bind the historical cycle, workbook identity
digest, exact manifest, cycle/inventory/job evidence digests, and expiry.
They do not name Samtec or authorize the historical cycle's settlement or
publication. Disjointness and request scope are additional controls.

The external signer must possess the private counterpart of a public key the
user or designated signing authority has independently approved for this
purpose. Neither `COMPANY_RETAINED_KEY_ID` nor
`COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64` was configured in this shell
or the production project environment file. No matching unit/config entry
was found among the scoped readable configuration locations checked.
No key values, private key files, or unrelated credentials were inspected.
The audit cannot identify a current private-key holder or prove an
out-of-process signing service exists.

If the user or an authorized signing officer already has an approved external
key, that holder can sign the exact canonical claims off-host and return only
the approval bundle and the independently authenticated public-key pin. An
operator can give the public pin to both installed commands without replacing
an existing configuration. The CLI accepts a caller-supplied key pair of
identity and public bytes, so successful verification by itself does not
establish that the caller's chosen public key was trusted. If no approved key
exists, designating one is a separate trust decision. There is no basis in
the current authority to self-generate a production trust anchor, reuse a
different-purpose key, or substitute a fixture verifier. Do not request a
signature or activate the exception as the next step when the installed
command still cannot admit Samtec.

## Independent follow-on blockers

1. [The retained public command](/home/chris/job-search-helper_old/src/job_search_helper/retained_company_event.py:308)
   requires exactly one raw nonterminal State row. The normal
   [blocker function](/home/chris/job-search-helper_old/src/job_search_helper/scan_request.py:297)
   discounts superseded cycles and finds exactly one effective local
   blocker. The retained command's narrower precheck therefore rejects
   `retained_event_blocker_scope_changed` before factory construction,
   signed-record loading, or any provider request, even after a genuine
   activation. Fix by using the established non-superseded local
   semantics and retaining the later full blocker recheck. Do not edit
   cycle rows to reduce the count.
2. [Disjoint admission](/home/chris/job-search-helper_old/src/job_search_helper/retained_work_exception.py:728)
   rejects Samtec with `retained_exception_company_overlap` whenever its
   ID is in the verified historical membership. Signature or no saved
   inventory cannot waive that rule. Also, the
   [current preflight](/home/chris/job-search-helper_old/src/job_search_helper/retained_work_runner.py:396)
   calls the provider before passing inventory to disjoint admission.
   With the raw-count issue fixed, a signed attempt could therefore fetch
   Samtec before that inevitable rejection. Put every locally knowable
   scope rejection ahead of provider invocation and keep the later
   post-fetch provider-identity check. A queued-only historical member
   policy or alternative bounded route requires separate scope approval
   and evidence that Saronic/history is untouched. A fresh signature
   cannot substitute for that review.
3. The roadmap also requires a release binding through local commit,
   pending sync, and exact confirmed sync. The retained command currently
   only [checks for an unsettled release journal](/home/chris/job-search-helper_old/src/job_search_helper/retained_company_event.py:299).
   Its [frozen start](/home/chris/job-search-helper_old/src/job_search_helper/retained_work_runner.py:495)
   and [session identity](/home/chris/job-search-helper_old/src/job_search_helper/retained_session_store.py:23)
   capture request, company, source revision and historical manifest
   evidence without an installed release or runtime pin. Keep this as a
   distinct Sprint 3 acceptance item before interpreting retained
   receipts as release-bound. No idle/busy measurement, real inventory,
   local commit, sync, or lost-ack proof was performed here.

The normal `start`/resume paths cannot substitute for the retained route.
The pending request and effective unfinished-cycle rule keep normal
admission blocked. Explicit normal resume is refused while the pending
request exists. Normal `start` can do general cleanup and synchronization
before selecting a requested cycle. Its absent-request branch can start a
full scan. Preserve the request and historical evidence. Do not use
normal start, global sync, or a historical recovery command as a probe.

This audit made no database, production configuration, source, service,
request, or historical-cycle change and ran no provider or Google call.
