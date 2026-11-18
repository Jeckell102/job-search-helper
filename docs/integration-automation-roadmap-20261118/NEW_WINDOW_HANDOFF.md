You are the senior engineering coordinator and release owner for my Job Search Helper integration-automation project. Start implementing the project now, not merely reviewing or rewriting the plan.

Read and follow the authoritative roadmap:
/home/chris/job-search-helper_old/temp/integration-automation-roadmap-20261118/AUTOMATION_ROADMAP.md

The main project is /home/chris/job-search-helper_old on MuleLab. The existing Python coordinator is in dev/wrapper-coder/tools, with durable state under dev/wrapper-coder/tasks. Read the applicable AGENTS.md instructions and current project documentation before changing code. Preserve unrelated dirty files.

My intended outcome:
- Adding an eligible company automatically schedules a scrape of only that company.
- If its integration is missing or broken, Python queues repair work, the Jetson assists with development, MuleLab validates and installs the integration, and a fresh company-only scraper run saves the applicable jobs through the normal Job Search Helper pipeline.
- Integration failures during ordinary scrape runs enter the same repair workflow.
- Temporary outages, access blocks and storage failures receive appropriate handling instead of unnecessary wrapper rewrites.

Create a new persistent goal, or resume a genuinely matching unfinished goal, covering all six roadmap milestones and the final acceptance demonstration. Track elapsed time and work until the completion contract is met. Do not reopen the completed Samtec pilot goal, impose an arbitrary project token budget, or close the goal after a partial milestone. If goal/timer tools are unavailable, record that limitation and maintain durable progress without pretending a background goal was created.

You are the coordinator lane. Follow and update the project plan, assign bounded jobs, check worker progress, reconcile their changes and review evidence. Use up to three worker lanes when useful and available: scraping/intake implementation, coordinator/repair/release implementation, and independent QA. Give each worker explicit ownership and acceptance criteria. Avoid overlapping file edits; use isolated worktrees when appropriate. Use fewer workers when dependencies require it.

The Jetson must have exactly one inference lane. Offload coordination, page retrieval/rendering, coding tools, tests, validation, storage and GitHub backups to MuleLab. Do not store wrapper development files or job inventories on Jetson. Extend the existing Python coordinator rather than creating a competing scheduler.

Maintain the roadmap's short coordinator restart card. Refresh your role/current focus, milestone status, worker assignments, goal/timer reference, latest verified evidence, blockers and next action at meaningful checkpoints and before handoff. Reread it after any context reset. Keep detailed task history and receipts separately in the same MuleLab temporary project folder. Save progress incrementally, not only when you think the context limit is near; never save private chain-of-thought.

Begin with a fresh read-only check of the repository, processes, locks, coordinator controls and existing receipts. Then implement Milestone 1: prove a supported company-only scrape through normal filtering, durable storage and synchronization. Samtec is the starting known-good integration. Its prior 148-job live results and 60 installed test passes are historical evidence, not a required current job count or proof that the full automation already works.

Continue through intake detection, failure classification, bounded AI development, automatic validation/install/retry and sequential recovery testing. I authorize implementation, relevant tests, bounded real-company pilot runs through normal storage/synchronization, and guarded deployment within the roadmap. Keep broad backlog processing and unqualified automatic repair types disabled until their gates pass. Put synthetic records and deliberately induced breakages in isolated tests. Preserve manual choices, existing Opportunities, active scrape cycles, locks and unrelated edits.

Success requires the complete company-event-to-saved-jobs chain, not just a generated wrapper or fixture tests. Verify full descriptions, pagination, company identity, stable unique job identities, actual storage results and synchronization status. Use fresh workers to load new releases. Test restarts, duplicate events, budget exhaustion, source drift, user pause and rollback. Runtime task budgets remain bounded and cannot silently reset.

Give meaningful progress updates about every five minutes and promptly when a milestone passes or a material blocker appears. Use the app's supported update mechanism if available. Stop if I ask you to pause. If an external blocker prevents all remaining useful work, checkpoint and explain exactly what needs my input; do not loop indefinitely or report completion.

Finish with independent QA of the deployed system against every roadmap acceptance gate. If it fails, save a new QA report, assign repair work and verify again without weakening the criteria. Back up scoped source, tests, plans and reports to my GitHub at meaningful checkpoints, excluding secrets and unrelated changes. The previous backup branch is backup/wrapper-pilot-20261118; verify the current repository and branch before using it.

Only mark the project complete after the roadmap's completion contract is satisfied. Report what is enabled, which integration families are supported, which cases remain blocked or unsupported, where evidence is saved, and the verified GitHub backup. Correctly holding an external access block is a valid system behavior; it does not mean that company's integration was completed.
