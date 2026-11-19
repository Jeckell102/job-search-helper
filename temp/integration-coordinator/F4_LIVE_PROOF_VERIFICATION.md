# F4 live proof verification

Date: 2026-11-19

Status: verified with limits. This report contains no request identity, prompt,
model output, credential, private address, raw receipt, or backup material.

## Scope

An operator ran the independently reviewed, authenticated synthetic HTTP proof
from the existing Jetson F4 record. The proof intentionally interrupted only
the Ollama backend while its synthetic request was in flight. It did not change
Job Search data, Google Sheets, scraper state, source code, model selection, or
broad queue/release settings.

## Independent evidence

- The operator reported: `PASS: real synthetic request was interrupted and
  settled without replay.`
- Post-run read-only verification found the local orchestrator and Ollama
  services active, with the health endpoint returning HTTP 200.
- The sanitized bounded evidence reports a transport failure, `UNCERTAIN`
  observation, `FAILED` settlement, absence of prior process generations, and
  released lane.
- The aggregate control-receipt state is terminal-only: one `CANCELLED`, one
  `COMPLETED`, and one `FAILED`; there are no `RUNNING` or `UNCERTAIN` records.
- Source-level independent QA accepted the proof ordering and persistence
  behavior. The focused staging suite passed 26 checks; the coordinator’s
  added authenticated-route regression raised the focused total to 27.

## Limits and next gate

This verifies the F4 Jetson transport-recovery sub-gate only. It does not
integrate the reviewed M1-M4 candidate into the protected MuleLab checkout,
authorize broad backlog processing, enable unqualified automatic releases, or
complete M5-M6/final acceptance. Those gates remain open.

## Records and backup

The authoritative Jetson record is
`project-records/f4-inference-receipts-20261118`; its documentation backup and
sanitized local mirror entry were recorded after verification. The Job Search
Helper scoped GitHub branch carries this sanitized report and coordinator card.
