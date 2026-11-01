# First-party static careers pages

Ordinary careers pages can publish a full job inventory without an ATS,
requisition number, or posting date. Treat the roles linked from the official
careers index and its career categories as the published inventory. Extract the
entire job article and preserve its canonical first-party URL.

The Annapolis Micro Systems adapter follows the index and every linked career
category, deduplicates canonical aliases, and reads each role's article title
and description. Application controls, navigation, forms, and scripts are
excluded. The canonical careers-relative path supplies a stable posting ID;
the requisition field remains empty when the source does not publish one.

The job count is discovered on every scan. After downloading descriptions, the
adapter rereads the index and categories and compares membership as sets.
Reordering is harmless. A changed role set, failed page, incomplete article,
or ambiguous response produces a partial result while retaining downloaded
jobs. Only an explicit, consistent no-openings statement can establish zero.

Annapolis serves some public pages only when the HTTP request uses an ordinary
browser-style User-Agent. That compatibility setting and conservative request
pacing apply only to its adapter. Other callers keep the existing discovery
client defaults.

The focused tests cover captured article content, category-only roles,
canonical redirects, stable identities, application exclusions, changing
membership, blocked details, and normal pipeline completion/date updates.
