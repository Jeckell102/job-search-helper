# v3.2 efficiency changes

## Google Sheets/API
- Queue scan: only Job Key, Review Status, Review Started At.
- Selected job: one Job History row.
- Cycle completion: only Cycle ID and Cycle Status.
- Company lookup: Company column + selected row.
- Opportunity lookup: Company + Job URL columns.
- Schema validation: header rows only instead of full operational tabs.
- Absence reconciliation: only the Job History columns required for closure logic.
- Full fresh tab reads remain in the safe writer before batch updates because they preserve formulas, validation, user fields, and concurrency checks.

## AI
- Python rejects obvious titles without any model call.
- Python sends obvious target functions directly to full review, skipping Luna.
- Luna sees only ambiguous titles and receives only the title.
- Clear annual USD base maximum below $120k rejects in Python before Sol.
- Sol gets a conservatively cleaned job description and no routine previous review notes.
- Previous posting context is sent only for actual reassessments.
- Initial Sol output no longer asks for repetitive material_change/base_max fields.
- Historical snapshot evaluations no longer retain repeated full posting copies.

## Models
- Title ambiguity: GPT-5.6 Luna.
- Full responsibility review: GPT-5.6 Sol.
- No model change to Terra in this release; optimize routing first, then measure actual usage.
