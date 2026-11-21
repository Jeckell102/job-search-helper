# S6 independent Company scrape launch control QA

**ACCEPT at the staged source pins.** The actual `./job-search-scraper storage intake-scrape-disable` and `intake-scrape-enable` commands used only the private intake dispatch journal. Each command subprocess loaded a guard allowing SQLite opens only for that journal and rejecting the workbook factory and network. The subprocesses also received a nonexistent Jobs path and blank workbook ID. No prior non-journal application file changed device, inode, mode, size, mtime, ctime or contents across the commands. [Actual shell fixture](/tmp/jsh-s6-launch-control-independent.uHkdtzHt/test_independent_launch_control.py:55) · [Shell result](/tmp/jsh-s6-launch-control-independent.uHkdtzHt/final-test-run/launch-control-shell/RESULT.json)

A missing scrape setting preserved the older intake setting's behavior. With intake enabled and scraping disabled, a rebuilt dispatcher returned `HELD_SCRAPE_DISABLED` for the exact ordinary request. The queued file retained its inode, metadata and bytes, with zero recorded launch ownership or dispatches and zero child/provider/workbook factory calls. Enabling scraping allowed one actual guarded ordinary admission and inventory freeze through the existing offline fixture. The continuation remained `HELD_ORDINARY_PUBLICATION` after disabling future starts again, and reopening the dispatcher returned the same exact publication readback without another launch. [Exact ordinary claim](/tmp/jsh-s6-intake-launch-control.20261121/src/job_search_helper/company_intake_dispatcher.py:277)

A separate narrow fixture exercised the temporary initial and resume claims and retained initial and restart claims directly through the existing journal. All returned a hold while scraping was disabled, and prior dispatch and ownership rows matched in full. Existing retained terminal recording remained available. Source review confirmed ordinary and retained exact receipt/ownership readback occurs before the gate for a new launch. The control applies at the durable claim boundary. [Claim-focused fixture](/tmp/jsh-s6-launch-control-independent.uHkdtzHt/test_independent_launch_control.py:128) · [Retained restart boundary](/tmp/jsh-s6-intake-launch-control.20261121/src/job_search_helper/company_intake_dispatcher.py:515)

Two independent tests passed in 1.64 seconds. The actual configuration commands ran in an isolated Python 3.11 environment. The original ordinary admission fixture used its guarded offline provider and workbook substitutes after enable. The temporary and retained checks covered the durable claim methods. No production, Jetson, network or actual Sheets operation occurred.

| Artifact | SHA-256 |
| --- | --- |
| company_intake_dispatcher.py | `4f7181b4f701fefbb05db3803c53cd1c148832a73cbf6fc415773f9de6f57f85` |
| sync_cli.py | `5af96a0d8abe8496d52824c197e0245207df7ce6e949027f2c392a6bf2d13de2` |
| job-search-scraper | `2556de3371c32be1991273a1ee88d2baa25753dfcdc73a9656d34de6b91de78c` |
| Maintained ordinary dispatch test file | `08d401d979c524f5db97807a96b67ce5614a88482ac573adf1e60b104d16da0c` |
| Independent tests | `6f55c4fd9add2e751056496264421ca15dbbf2799d4eaec5850902190a7cb132` |
| Actual shell result | `138929da7a8d448eb854afd77bcb5cea9aa33d07d97697218b4878245a4a8983` |
