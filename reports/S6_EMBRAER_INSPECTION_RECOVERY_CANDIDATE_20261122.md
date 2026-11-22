# Embraer inspection checkpoint recovery

The paused Embraer worker had completed the inspection evidence without
returning the plan checkpoint. The isolated host change offers only the
existing checkpoint tool for the exact stalled work order when fresh
evidence satisfies the original inspection gate and the plan has no work
remaining. Normal checkpoint validation still decides whether work advances.

Independent source QA accepted coordinator SHA-256
`3d5d42249f4e8b277e3d86de57658c2275214629b78aff9cd61fbcb8d65680d4`.
The test file SHA-256 is
`54ca14e8878a8218e47035aef5cc84924de7e1813bf0dc4351fde59264184615`.
All six focused tests passed. The direct session fixture verified one
inference request, the checkpoint-only schema and instruction, the
existing phase transition, and preservation of counters. The first draft
lost the instruction when rebuilding history. The accepted version appends
the instruction after the rebuild. Root then reproduced the potential
requeue on a plain-text or continue result and changed the recovery path
to hold after that one offer. Independent QA verified both responses hold
without another call. The supported same-task resume keeps the existing
pilot slot and authoritatively rechecks the task budget and identity.

At about 14:00 Eastern, a read-only test against the actual task
`WRAP-fbb9ff24d3` returned true for the checkpoint offer. The workspace
matched the task exactly, all tool and inference receipts were settled,
three stalled turns were saved, the task still owned its pilot slot,
and no other task was active. About 46 minutes remained of the task's
original hour. Reassess source evidence freshness and lifetime immediately
before any supported resume. No production change or model call was made
for this verification. No repair candidate yet exists.

Root owns the scoped backup and authenticated resume. Release engineering
owns the private one-file maintenance entry. Independent QA must check the
entry and exact installed result before the live task continues.
