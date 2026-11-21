# Recipe-choice interface rejection, November 21

The first bounded recipe-choice probe `WRAP-888acebf40` completed exactly
one Jetson call. It cited the same-click evidence and named
`listing_membership_change` as the next action. It returned a narrative in
`summary`, where the probe required the strategy ID, and omitted `W1` from
`next_action`, where the probe required the evidence ID. The generic
checkpoint prompt itself asks for a narrative summary and then the next
action, and the offered string schema had no enumerated IDs. The exact
result is `HELD_NO_VALID_CHOICE`. The candidate was not materialized.

The local hold receipt hash is
`27e3860840ba0b00c0aff2637a43f5f548185ca6096c8b80cad6564981004881`;
completed remote response hash
`5ab1dc209c1f887e1eb0c99315e4ff266504f778bb3765631ad35465e2791a9b`.
The exact failed payload and generated-code rejection remain held. One new
isolated interface check will use an enumerated tool schema with strategy
in `next_action` and `W1` as the explicit evidence value, preserving all
recipe, witness, source, and inference ownership gates. The prior response
cannot pass by reinterpreting its text. No model configuration or production
release is part of this experiment.
