# NEXT

State (2026-11-04): PRD only (`docs/prd.md`, v0.1). No code, no git repo yet.

Next: owner creates the repo if wanted, then pastes `KICKOFF.md` into Claude Code. The session plans first and stops for review.

Order: G1 -> G0 (shared layer) -> G2 -> G3 -> G4 -> G5 (see ../README.md). If G0 isn't built when this starts, use stubs with the same contract shape.

## 2026-11-21 — G5·C built unattended (branch `build/g5c`, draft PR)

**State:** G5·C (Python 3.12 + Claude Agent SDK worker) is built end to end on a **synthetic vault** and the **recorded model path**, attached to G0 at `6f5e605`. G5·B (n8n) was not built (D-2; owner's hand build). Nothing is merged; no API key was used; no model was called ($0); nothing touched a real vault.

**Done** (backlog C1–C12, `docs/BACKLOG.md`): safety invariants with tests first (body hash, frontmatter limits, copy-vault guard); synthetic fixture vault (63 notes, 6 arrivals, 3 owner edits, taxonomy, 20-note labeled sample, hand-written recorded responses with designed mistakes); SQLite state table with row leases, compare-and-swap writes and a two-phase before/after change log; Watcher, Classifier, Linker (`--suggest-only` too); supervisor (daily cost cap, token budget, error burst, safety trips, kill switch, alert log); 15-minute loop on an injectable clock; OpenTelemetry traces to a local JSONL file; `gardener simulate / report / quality / revert / kill / resume / status / demo`; CI workflow (lint, typecheck, tests, 96-tick simulation, quality report). Gate results: see the PR's "Gate results" section.

**Provisional decisions for Shane** (`docs/DECISIONS.md`): D-1 synthetic vault; D-4 daily cap $0.05 / 440,000 tokens (3× the recorded day's *estimated* cost — a placeholder until a measured day); D-5 Linker writes (vs suggest-only); D-6 synthetic taxonomy; D-10 Haiku 5.5 for both agents.

**Not verified:** no real 24-hour wall-clock run (AC1 is a 96-tick simulation); no live model call, so real tokens, cost and tagging/linking quality are unmeasured (the quality figures describe designed fixture mistakes); `AgentSdkCaller` has never run; G0's price table has no Haiku long-prompt (>100K) tier, so a giant runaway prompt would be under-priced (the cap still trips, just later); lease takeover after expiry mid-write is covered by CAS but not by a test that kills a writer mid-write.

**Next / You:**
1. Review the draft PR and the provisional decisions (D-1, D-4, D-5, D-6, D-10); say which to change. Decide Linker **write vs `--suggest-only`** (D-5) before any non-synthetic vault.
2. Real 24-hour run on the copy vault (wall clock, recorded model, no key needed): `uv run gardener copy-fixture ~/gardener/vault && uv run gardener run --vault ~/gardener/vault --state ~/gardener/state` — leave it a day, then `uv run gardener report --state ~/gardener/state` and `uv run gardener status --vault ~/gardener/vault --state ~/gardener/state`. (Arrivals are not scheduled in a wall-clock run; drop a note in `~/gardener/vault/inbox/` by hand to see it picked up — it needs a recorded response or `--live`.)
3. For real numbers: put `ANTHROPIC_API_KEY` in a gitignored `.env`, export it, and run one measured day with `--live` on the copy vault (63 notes ≈ 125 calls on the first tick). Keep the $0.05 default cap or raise it explicitly with `--daily-cap-usd`; G0's $10 per-run cap and the track's $10 build cap still apply. Then reset `RECORDED_DAY_*` / defaults in `config.py` from the measured day (D-4).
4. Build G5·B in n8n by hand from `docs/prd.md` (Schedule Trigger 15 min → Watcher/Classifier/Linker sub-workflows on one state table; separate supervisor workflow).
5. Decide whether ever to point it at a **copy of the real Lab vault** (PRD decision 1). The worker only runs on a folder with a `.gardener-copy` marker; a copy of the real vault must never be committed to this public repo.
6. Merge the PR yourself when satisfied (no one else will); tag G0 `v0.1.0` if you want the pin moved off the SHA.
