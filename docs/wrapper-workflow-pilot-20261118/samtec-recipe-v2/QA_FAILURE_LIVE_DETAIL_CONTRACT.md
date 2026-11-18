# Independent live failure report

The isolated integration test failed. All 154 captured HTTP responses and their saved hashes were verified: 148 job details plus all three listing pages read twice. The scraper returned zero jobs with partial status because each detail lacked the structured JSON-LD required by its generic Jobvite detail handler.

All 148 actual detail pages instead contain one HTML description container, one job heading, and application links matching the requested employer and job ID. Their complete visible descriptions are at least 1,164 characters. The source was accessible; the missing capability is extraction from this verified HTML detail format.

The offline pagination tests used synthetic structured descriptions. They verified traversal and reconciliation but did not represent Samtec's actual detail format. Passing them never certified live completion; this live gate correctly stopped acceptance. The earlier assumption that this employer supplied JSON-LD must be replaced.

Next: add and independently test a Samtec-only HTML detail contract, requiring unique complete description, matching listing title, employer cues and exact application identity. Preserve other employers' detail behavior. Replay all 148 captured pages and reject conflicting/missing identity or truncated containers before another live run. Update independent full-description comparison to the real HTML contract, without lowering complete-description requirements.

No integration certification, production installation or publication is granted. Detailed page hashes and structure findings are in QA_FAILURE_LIVE_DETAIL_CONTRACT.json.
