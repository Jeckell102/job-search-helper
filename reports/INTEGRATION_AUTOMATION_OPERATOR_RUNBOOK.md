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

## Start the administrator observer when requested

The current two-file MuleLab update needs a short administrator observer
window. The observer verifies process and listener ownership. Start it
only when the coordinator has the exact maintenance scope ready.

For the current `-05` window, open a regular MuleLab Terminal and run:

```bash
bash /tmp/jsh-amphenol-native-two-tool.HQkjpe8m/start_observer.sh
```

Leave the terminal open and report `Administrator process observer ready.`
The current window lasts 15 minutes. If the script reports an existing
observer directory, send the exact message to the coordinator so it can
check ownership and choose the proper next action.

The coordinator first runs the native preflight. If it passes, the exact
tool update can stop and restart the wrapper host. The live result must
verify the installed bytes, new wrapper process, prior sync controls and
historical receipts before the coordinator uses that version for a pilot.
The actual company run starts later under its own exact request.

## Read the result before moving on

| Status | What to expect |
| --- | --- |
| Waiting or held | A request or repair may be saved. Use the reported reason and keep its evidence. |
| Building or validating | A scoped candidate is under review. A fresh scrape or deployment still awaits qualification and approval. |
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
owns the cycle. The staged manual-start route also prints those values
when a workbook write response is uncertain. The coordinator checks the
saved inventory before resuming publication and verifies the terminal
receipt afterwards.

## Current release boundary

The corrected MuleLab builder is installed, and the fresh Amphenol pilot
produced a candidate with one Jetson decision. Current public qualification,
guarded release and the company-only retry still await verification. Sprint
6 intake can be observed locally. Broad backlog processing and unqualified
automatic releases remain disabled. Sites outside the approved capability
scope go to engineering review.

Use the [current coordinator checkpoint](COORDINATOR_STATUS.md) for the
active request, worker ownership and versioned recovery evidence. Use the
[sprint roadmap](sprint_roadmap.md) for the required acceptance gates.
