# Sprint 5 Amphenol Aerospace generation pilot

## Current failure and baseline

November 21, 2026. Amphenol Aerospace `COMP-0490` was active in the local
Companies inventory with provider AcquireTM and the employer's configured
careers page `https://amphenol-aerospace.acquiretm.com/home.aspx`. A bounded
read of the live listing showed 39 advertised postings, 25 first-page IDs,
and a second page. A listing-linked detail had the matching employer,
identifier, title, full description, and US location. The existing production
adapter's browser inventory returned partial after 25 with `AcquireTM total
changed or pagination repeated.` at 05:03:15 UTC. The baseline listing count
is a point-in-time observation.

Private evidence is in `/tmp/jsh-s5-amphenol-current.490_viwa`. The listing
capture SHA-256 is
`d9ddf57cf2896fb6bb2a21031256b1b3a8af3ef9aa88773757118b41912d5146` and the
adapter-result SHA-256 is
`5938b33bdf622766230bb18045f856b7d5ff354e8e5f6390accd80df059df35c`.
Raw postings and workbook data stay local. Production and the isolated-task
baseline matched on `src/job_search_helper/acquiretm.py`
`88893583bb01ed0b8878020d9b71ddb9043bbfcdb70d6e0eb6b2475bc8855392` and
`tests/test_acquiretm.py`
`5bace6904b1630871477aa2b5b408a591813a834742a2bcca85c757c8dd5e908`.

## Bounded launch

The existing authenticated Python coordinator reported healthy. Its durable
state showed no pilot, other active task, or unresolved inference. Global
queue, autopilot, and campaign scheduling were off. The coordinator imported
one fresh isolated development assignment in `s5-amphenol-first-generation-20261121`,
verified it held, then accepted one `pilot-start` for `WRAP-9b6f2e2274` at
approximately 00:08 Eastern. The existing isolated workspace was created on
MuleLab, limited to the AcquireTM adapter and its targeted test. The first
activation was `QUEUED` at `baseline`. Python then obtained a durable public
source-read receipt. The pilot uses the existing single Jetson inference lane.

Private request responses are in `/tmp/jsh-s5-amphenol-pilot.a0VY8n5k`.
Batch SHA-256 is `867d71fc9feeb041e88acdf87375ca8f0d01e1e2d9a4452dab8341f7edf00ecb`.
Pilot activation SHA-256 is `42a30d8ead443305ef7bb4f906e3745131db81cfe051d4b5ff65a859279404c1`.

The launch was explicitly selected to test generation and isolated staging.
Automatic failure-to-task activation and the complete repair acceptance gate
remain open. This pilot has made no production source edits, Sheet writes,
release, scrape retry, or job publication. After generation, verify the exact
diff and tests independently and use bounded normal-path live validation
before any release decision.
