# Vault Gardener (G5)

Agentic AI track, build-log G5. Spec: `docs/prd.md`. Start: `KICKOFF.md`. Status: `NEXT.md`.

Rules for any Claude Code session here:
- Copy vault only until acceptance passes. Agents may only edit frontmatter and append a 'Related' section; never delete or rewrite note bodies. Every change logged before/after.
- No merges to main, deploys, live external writes or account changes without the owner's explicit go.
- Shared capabilities come from ../shared (G0) or local stubs with the same contract; never inline them in prompts.
- Log tokens and cost per run. Keep NEXT.md and docs/DECISIONS.md current.
