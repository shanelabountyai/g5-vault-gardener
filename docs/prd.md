# G5 Vault Gardener — PRD v0.1

Nov 3, 2026 · @Shane LaBounty

## Summary

Agentic AI track, build-log G5, and the capstone. Every 15 minutes, three agents tend your Obsidian vault and inbox: a Watcher finds new or changed notes, a Classifier tags and files them, and a Linker connects related notes. A supervisor watches errors and cost and shuts the job off when either passes a limit.

Built twice: **G5·B in n8n first**, then **G5·C in Python with the Claude Agent SDK** as a long-running worker.

**From the build-log card (already set):** continuous operation; Watcher → Classifier → Linker sharing one state table; supervisor with error and cost limits plus a kill switch; graphic row "Duration". The C version adds locks so agents don't collide on shared state, a token budget, and OpenTelemetry traces. Framed as your thesis in practice: most failures here are process, not model.

**Everything else here is a proposal.**

## Why it's in the portfolio

Most agent demos run once and stop. This one runs all day, shares state, and has to be safe to leave alone. That is the hardest row on the graphic, and the one closest to what clients actually worry about: cost runaway, bad writes, and nobody watching.

## Agents

| Agent | Job | Writes |
| --- | --- | --- |
| Watcher | Find notes and inbox items new or changed since the last run | State table only |
| Classifier | Tag, set type, and suggest a folder | Frontmatter tags and type |
| Linker | Find related notes and add links | A "Related" section only |
| Supervisor | Track errors, cost and run time; stop the job past limits | State table + alert |

## Safety rules (proposed)

- **Run against a copy of the vault first,** never your live vault, until the acceptance criteria pass.
- **Agents only append or edit frontmatter and a "Related" section.** They never delete or rewrite note bodies.
- **Every change is logged** with before and after, so any run can be reverted.
- **The kill switch** stops all agents and leaves the state table consistent.

## Shared-layer hooks (proposed)

- **observability:** traces and per-run cost.
- **measurement:** notes processed, links added, errors per day.
- **evaluation:** a hand-labeled sample to check tagging and linking quality.

## G5·B (n8n) build notes

- Schedule Trigger every 15 minutes
- Watcher → Classifier → Linker as sub-workflows reading and writing one state table
- A separate supervisor workflow checks error and cost totals and deactivates the main workflow past limits
- Vault access through your existing vault setup (see your obsidian-vault infrastructure)

## G5·C (code) build notes

- Long-running worker process with a 15-minute loop
- Locks on state-table rows so two agents can't edit the same note at once
- Supervisor with a daily token budget and a kill switch
- OpenTelemetry traces for each run and each agent call

## Acceptance criteria (proposed)

1. Runs for 24 hours on the copy vault with no note bodies changed or deleted.
2. A forced cost spike trips the supervisor and stops the job.
3. A forced error burst trips the supervisor and stops the job.
4. **C only:** two agents targeting the same note never produce a conflicting write.
5. Daily report: notes processed, links added, errors, cost.

## Decisions needed (one at a time)

**1. Which vault to run against** *Recommendation: a copy of your Lab vault* until all acceptance criteria pass, then decide on the live vault.

**2. Which inbox** Options: a vault inbox folder / Gmail. *Recommendation: the vault inbox folder first.* Gmail adds permission and privacy risk to a public portfolio demo.

**3. Cost limit** *Recommendation:* set a daily dollar cap after a one-day measured run, rather than guessing now.

## Questions for you

1. Should the Linker suggest links for you to approve, or write them directly?
2. Does your vault already have a tag taxonomy the Classifier should follow?
3. Is the public repo for this built from the copy vault only, so no personal notes ship?
