# Selected-prefix normal-lock repair

This exact two-file source-and-test overlay corrects the local apply lock for
selected-prefix recovery. SQLite scraper maintenance must own the normal
`scraper.lock`; `writer.lock` is the separate Google Sheets publisher boundary.

The repair derives the lock filename through the existing
`scraper_lock_name()` policy and adds a regression that proves the default
apply path requests the normal SQLite scraper lock. It changes no plan,
authorization, journal, receipt, remote-intent, readback, or cleanup semantics.

Any authorization envelope produced before this repair was discovered is
superseded and must not be used. Source installation and a fresh independent
authorization remain separate gates.
