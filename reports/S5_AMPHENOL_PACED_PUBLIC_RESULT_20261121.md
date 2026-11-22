# Sprint 5 Amphenol paced public qualification

The one-time Nov. 21 retry started once at 19:22:50 Eastern and passed at
19:30:54 Eastern. The scheduled floor was 19:22:00 Eastern. The
provider returned the same 39 unique listings over two pages on both
listing reads. All 39 detail attempts returned HTTP 200. The shortest
parsed description had 3,493 characters. There was no HTTP
429 or new Retry-After hold. Each consecutive detail request waited at
least twelve seconds from the preceding response, with a measured minimum
of 12.000079 seconds.

The coordinator verified the terminal exit code, both log digests, listing
membership, response status and coverage, description coverage, and measured
spacing. The private raw evidence is under
`/tmp/jsh-amphenol-paced-192200.bkpRR9Zu` in `RUN_STARTED.json`, `RUN_TERMINAL.json`,
`QA_STDOUT.log`, and `QA_STDERR.log`. Keep the raw provider records local.

- Preparation SHA-256 `b9819940888d60398a2f36e98ab51f4d7bb0baeed242879484772172ab0ad992`
- Candidate source manifest `7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea`
- Listing membership digest `ff45144db9475e3978bd06cf64ec00669f43eaa03da13088849230494e2c6877`
- Verified cohort digest `728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b`
- Standard output SHA-256 `fdb1529fa0c336537a95a45e467fba63e4a3538976e783fb28109b40e2b1b96c`

This qualifies the candidate with the tested paced evaluator. Production
pacing, installation, company-only retry, local and workbook publication,
and independent deployed acceptance remain pending. The run used no
Jetson inference, installation, service action, or job data writes.
