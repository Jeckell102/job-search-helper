# Operator retained recovery

Post-settlement consumption recovery now accepts the two canonical
one-company request forms already admitted by retained work: Company events
and operator-company requests. It round-trips every archive through the normal
request parser, derives the immutable provenance identity through the retained
runner helper, and compares that identity against both frozen admission and
released publication evidence. Repair, legacy, malformed, and mixed formats
remain held. Newer queued requests are preserved.

Recovery also rereads the original operator or bridge provenance receipt and
requires its exact canonical fields and digest to equal the frozen admission
payload before consuming the archived request.

Focused retained route tests passed with warnings treated as errors; formatting
check passed. No live state or service was touched.
