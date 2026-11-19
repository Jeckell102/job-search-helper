# Selected-prefix exact-v2 recovery adapter

This nine-file source-and-test overlay adds one signed, selected-company
recovery path for a retained legacy plan with a verified local prefix. It
promotes only the exact approved successor into the existing exact-v2 local,
receipt, remote-intent, readback, local-acknowledgement, and cleanup lifecycle.

There is no alternate receipt table or fake publication path. The public apply
command stops at a locally verified frozen successor. The ordinary exact-v2
publisher refuses expired or mismatched authorization before receipt creation,
freezes its normal remote intent before marking the selected journal, and
archives selected evidence only after durable confirmation and local
acknowledgement.

The package contains five new files and four exact protected replacements. The
baseline manifest requires every new target to be absent and both replacements
to match their current protected hashes. Removed prototype modules are not
included and must remain absent.

The isolated adapter passed 150 focused and adjacent checks with warnings as
errors. Independent QA passed 164 checks and compileall, accepting this source
for protected-package preparation only. Installation and any pilot remain
separate gates.
