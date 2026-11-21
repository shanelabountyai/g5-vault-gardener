# Kickoff — Vault Gardener (Build Log G5, Agentic AI track)

Paste the block below into Claude Code started in `~/Projects/agentic-track/g5-vault-gardener`, on Fable (`/model`).

```
You are starting a new build: Vault Gardener (Build Log G5, Agentic AI track,
graphic row "Duration"). The spec is docs/prd.md. Read it fully before doing anything.
Also read ../README.md for the track order and the shared-layer (G0) contract rule.

The project is built twice, in this order:
- G5·B (n8n first): n8n: Schedule Trigger every 15 min -> Watcher, Classifier, Linker sub-workflows sharing one state table; separate supervisor workflow deactivates the main one past error/cost limits.
  Deliver it as importable workflow JSON in n8n/, with a README on how to import it
  into the owner's self-hosted n8n.
- G5·C (code second): Python 3.12 + Claude Agent SDK long-running worker: 15-min loop, row locks on the state table, supervisor with daily token budget and kill switch, OpenTelemetry traces.
  Start G5·C only after G5·B passes its acceptance criteria.

Test data: A COPY of the vault (never the live vault) plus a vault inbox folder; a hand-labeled sample of notes for tagging/linking quality.

Safety invariants (land with tests BEFORE any code path can reach a live system):
Copy vault only until acceptance passes. Agents may only edit frontmatter and append a 'Related' section; never delete or rewrite note bodies. Every change logged before/after.

Shared layer (G0): the PRD lists the shared capabilities this project calls
(claims.registry, brand.policy, audience.consent, measurement, evaluation,
observability). If ../shared/ does not exist yet, build local stubs with the same
input and output shape, in one clearly named module, so they can be swapped for G0
later. Never copy rules into an agent's prompt that belong in the shared layer.

Open decisions in the PRD: Which vault copy, inbox source (PRD recommends vault inbox folder, not Gmail), daily cost cap (set after a measured day), Linker suggest vs write, existing tag taxonomy.
Take the PRD's recommendation for each unless I say otherwise, and record each as a
D- entry in docs/DECISIONS.md before writing code.

Working rules:
- Confirm current Claude model IDs and prices from Anthropic's docs before using them.
  Confirm current n8n node names and options from n8n's docs; record what you found.
- Log tokens and cost per run from the first live call. Hard cap: $10 of live model
  calls for the whole build unless I raise it.
- Keep NEXT.md current, matching the other build-log repos: what is done, what is
  next, and exact hand steps for the owner.
- Commit at the end of every task with a clear message. Never commit secrets; keys
  live in a gitignored .env.
- Work on a branch named `kickoff`. No merges to main, no deploys, no live external
  writes, and no account changes without my explicit go.

Step 1, plan first: write docs/BACKLOG.md breaking G5·B then G5·C into tasks
you can finish and test in one sitting, each with acceptance criteria taken from the
PRD. List owner hand steps separately. Then stop and show me the backlog and
DECISIONS.md before building.
```
