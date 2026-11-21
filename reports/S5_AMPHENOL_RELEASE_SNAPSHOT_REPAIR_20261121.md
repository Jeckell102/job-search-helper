# Disposable Amphenol release snapshot correction

The first guarded test installation and retry-queue result is archived under
`/tmp/jsh-s5-amphenol-release-rehearsal/wal-copy-held-attempt`. Its newly
scheduled retry stopped before admission or provider access. The rehearsal
had copied the SQLite main files without their write-ahead logs. Its State
copy therefore lacked the previous settled Company-event checkpoint, and
the normal lifecycle guard correctly held.

Root rebuilt the private fixture using SQLite's backup API for Jobs, State,
and inventory. The new rehearsal rechecked the exact owned predecessor with
the application settlement reader before authorizing its fixture install.
It verified the same exact candidate, release `REL-c4bdcec9fadace26ad764349`,
and one durable request. Replay again returned the identical request bytes.
The fresh activation produced attempt `RTRY-c1e879796b64630e034c7e64`.

- Corrected guarded result SHA `d467cdbc97206cd71b75205db6c2efc0c32e36d3740dcd2cef0d06c8c163e84b`.
- Revised test installer journal SHA `43f7dbe1d301ac4ee1a2abea2dd635fb01f3265a8527edf40f52059d32cdb272`.
- Exact updated request SHA `ae7c537ac1add18d617583b21cb23ffac238d3b2c737691a31c025d1fb5ef08f`.
- Resnapshotted one-shot caller SHA `afab5556592a4666fcbebe5b7d1cc06d12a0f7a521255ff11f6d2665b50590de`.

The corrected workspace admitted `CYC-9512BF1F13C8` from that one request
and started one bounded normal public Amphenol fetch at 01:29 Eastern.
No production database, user workbook, existing job data or deployment
was involved in either private rehearsal.
