# Job Search Helper integration pilot operator guide

## Check status on MuleLab

In a regular MuleLab Terminal, run these from the production folder.
They check the local intake and queue without starting a scrape or publishing.

```bash
cd /home/chris/job-search-helper_old
./job-search-scraper storage intake-observe
./job-search-scraper company-queue-status --local-only
```

An empty intake list means the local bridge sees no currently pending
Company event. “No pending request” means the one-company scan slot is
empty. A busy or held result should be read with its reported blocker.
Retain existing queue files, locks, and cycle receipts when investigating.

For the current model task, use `/wrapper status WRAP-…` in the wrapper
interface with the exact task ID from the coordinator. The persistent
project goal and the live wrapper task have separate status.

## Run one existing Company explicitly

For a reviewed existing Company, use one stable request ID beginning
with `operator-company:`. Run these commands from the production folder
only when that name and source have been selected for the pilot.

```bash
./job-search-scraper queue-company --company-id COMPANY-ID --request-id operator-company:stable-request
./job-search-scraper operator-company admit-fetch --request-id operator-company:stable-request
./job-search-scraper operator-company publish --request-id operator-company:stable-request --cycle-id CYC-EXACT
```

Replace the Company, request suffix and cycle placeholders with their
exact values. Use publish only when the named fetch reports a complete
frozen inventory. If publication is interrupted, repeat the same
publish command for the same request and cycle. It uses saved jobs and
checks the existing write before allowing another action. Keep a
held fetch or incomplete inventory for reconciliation. The positive
operator command leaves broad Start, automatic repair and the separate
new-Company event path under their existing controls.

## Pause and resume

Ask the coordinator to pause the integration project when you need the
release work to stop. If a company run is at a write or inference boundary,
the coordinator saves its current receipt and identifies when it is safe
to stop. Resume by naming the same project or asking the coordinator to
continue. Keep the existing task ID and request ID.

For a single identified wrapper task, `/wrapper pause WRAP-…` requests
a safe boundary. Check the task status before assuming it stopped.
If an inference receipt is unresolved, the coordinator reconciles it
before another model request. The reviewed scoped pilot is resumed using
the recorded ownership and recovery steps in the current checkpoint.
Leave broad queue resume and autopilot controls off during pilot work.

## Guarded maintenance on MuleLab

MuleLab has a standing administrator observer. The coordinator uses it
to verify process and listener ownership before a guarded release and
checks that the services and checkout locations are restored afterwards.
A working observer requires no Terminal setup from you. If its check
fails, the coordinator will tell you which prerequisite needs attention.

A guarded update may briefly restart the wrapper host or assistant
bridge. The coordinator verifies the installed files, restored services,
sync settings and existing receipts before starting any new company run.
A company run uses its own exact request.

## Read the result before moving on

| Status | What to expect |
| --- | --- |
| Waiting or held | A request or repair may be saved. Use the reported reason and keep its evidence. |
| Building or validating | A scoped candidate is under review. A fresh scrape or deployment still awaits qualification and approval. |
| `PAUSED_TEST_FAILURE` | The edit failed verification. Keep its saved evidence. Another report of the same defect does not automatically restart an exhausted repair. |
| Installed and retrying | The released version and the new request have separate receipts. Check the named retry for progress. |
| `LOCAL_COMMITTED` | The company result and exact job records were durably saved locally. |
| `SYNC_PENDING` | Workbook publication or confirmation is pending. Reconcile the saved records for the same request. |
| `SYNC_CONFIRMED` | The exact workbook rows were read back and matched to the saved company result. |

A fresh scoped retry has its own request ID and links back to the original
failure and installed version. A real publication failure is handled from
the existing local receipts so the jobs need not be fetched again.
Manual workbook decisions and Opportunities retain their own ownership.

If an ordinary Company run stops after saving its inventory, the supported
continuation is the existing `ordinary-company-event publish` command
with the exact request digest and cycle ID. If the run was interrupted
before printing those values, the coordinator reads them from the local
receipts. A subsequent bare Start can report that the ordinary event
owns the cycle. The manual-start route also prints those values
when a workbook write response is uncertain. The coordinator checks the
saved inventory before resuming publication and verifies the terminal
receipt afterwards.

On the active release, the first manual Start can discover one new active
Company that exists only in Sheets when the compact workbook has an
established Company baseline. The row needs a stable Company ID, a
careers source and an unambiguous company name. Start uses the scoped
Company route when it finds exactly one eligible addition. Multiple
additions or ambiguous or incomplete ownership require reconciliation.
Read-only discovery found no genuine new row after deployment, so live
first-Start publication remains to be verified.
[Deployed source evidence](S7_FIRST_START_DEPLOYED_ACCEPTANCE_20261122.md).

## Current release boundary

The bounded Amphenol repair and scoped retry passed independent deployed
verification. Sprint 6 intake can be observed locally. The GA-ASI case
demonstrated a deployed employer-scope hold without launching a scrape or
repair. Allen has a verified source correction and saved Ashby inventory.
The two exact ATS attempts failed offline and their edits never reached
production. The installed coordinator preserved both attempts and
refused a third owner in a disposable replay. Read the active checkpoint
for the current company, repair and publication status.

Broad backlog processing and unqualified automatic releases remain disabled.
Sites outside the approved capability scope go to engineering review. Sprint 7
requires current deployed proof and final independent acceptance.

Use the [current coordinator checkpoint](COORDINATOR_STATUS.md) for the
active request, worker ownership and versioned recovery evidence. Use the
[sprint roadmap](sprint_roadmap.md) for the required acceptance gates.
