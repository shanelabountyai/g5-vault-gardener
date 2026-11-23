# NEXT

## 2026-11-23 — owner decisions built (branch `review-fixes/2026-11-22`, PR #2 still draft, unmerged)

Shane approved the review's recommendations. Built, each with tests first:
- `0ebf8d6` **D-33** `gardener resume` starts a fresh error-burst window (old errors kept, no longer counted).
- `428e0d1` **D-34** failure-share trip: ≥ 80% of at least 3 attempts failed in 60 min → `failure_rate`. A forced outage from tick 10 now trips (it never did, D-25); the normal recorded day still has 0 trips.
- `8afcacf` **D-35** uniform CRLF and BOM notes are edited in their own form (BOM and `\r\n` kept, body hashed as on disk, revert byte-exact; safety refuses a line-ending/BOM change). Mixed endings and unreadable frontmatter stay `unsupported`. The two review tests for skip-only behaviour were replaced by stronger ones; a mixed-endings test keeps the skip guarantee.
- `d6d342d` decisions D-33..D-36.

**Gate (local, head `d6d342d`, `G0_DB_PATH` unset):** ruff All checks passed! · mypy no issues in 17 files · pytest 92 passed · simulate and quality reports identical to the committed ones · **CI:** push and pull_request runs on `d6d342d`: success.

**Still open (D-36):** copy-vault guard is a marker file (needs your real vault root path to also refuse it); filename-stem collisions; provisional D-1, D-4, D-5, D-6, D-10. Merge stays yours.

## 2026-11-22 — overnight review of merged PR #1 (branch `review-fixes/2026-11-22`, draft PR "G5·C: review fixes (2026-11-22)")

**Review** (fresh review agent on the merged PR #1 diff + PRD/backlog/decisions): **2 must-fix, 7 should-fix, 1 nit**, plus owner calls. Every README and report number reproduced (145 calls, 68 / 79 / 203 / 3 errors, 144,796 est. tokens, $0.0156; 0.9375 / 0.9091 / 0.95 / 0.9661, 17/20; spike trips at tick 18). Fixtures look synthetic (generated filler, "(fictional title)", no emails/URLs/phones/real names). G0 pinned by SHA, not copied; no secrets; no skipped tests; live calls need `--live` and a key.

**Fixed (9, each with a failing test first; D-27..D-31):**
- `0ce71e1` M1 notes are read as bytes; a CRLF note is `unsupported` and left byte-identical (was silently converted to LF, with every body-hash check passing on the converted text).
- `7b541bf` M2 frontmatter that is not valid YAML (or tags/type of an odd shape) → `unsupported`; owner tags were being replaced.
- `22ae605` S5 a note starting with a UTF-8 BOM → `unsupported` (was given a second frontmatter block).
- `1f6c2d1` S3 tags that would not read back as themselves (`#garden`, `null`, `yes`) are quoted; one such owner tag used to trip the whole job.
- `72cbd3b` S4 top-level frontmatter comments and blank lines survive a tags/type rewrite.
- `667dac3` S6 lease renewed after a slow model call; a lost lease is a conflict, not a crash; a crashed tick is recorded `crashed`, not `ok`.
- `5384585` S7 the file is re-checked after fsync, right before the rename; an owner save in that window wins (change aborted).
- `4a98584` S8 a kill switch set during a model call stops that call's write.
- `02525f8` S9 a half-written change overtaken by an owner edit is `superseded`, so the note is no longer stuck "busy".

Simulated daily report and quality report are byte-identical before and after every fix (no number moved). Tests 77 → 87.

**Left (nit, D-32):** `test_ac5_…` fails if `G0_DB_PATH` is exported in your shell (module-scoped fixture runs before env cleanup); CI doesn't set it.

**Decisions for Shane:**
1. CRLF / BOM notes: skip (now) or support (write frontmatter in the file's own line ending, keep the BOM). *Recommend support* before any vault edited on Windows; skip is safe meanwhile (D-27).
2. Error-burst count is not reset by `resume`: the first error after a resume can re-trip if older errors are still in the 60-min window. *Recommend* reset the window at resume.
3. A full API outage never trips the supervisor in steady state (notes are parked after 3 attempts, D-25). *Recommend* an alert when most calls in a window fail, not only on a count.
4. The copy-vault guard is a marker file; `touch .gardener-copy` in a live vault defeats it. Decide if that is enough before PRD decision 1 (a copy of the real Lab vault). *Recommend* also refusing a vault path under your real vault root.
5. Linking is by filename stem; two notes with one stem in different folders collide in the catalog (not in the fixtures, not reproduced).
6. Still provisional: D-1, D-4 (placeholder caps from estimated tokens), D-5 (Linker write vs suggest), D-6, D-10.

**Gate (local, 2026-11-22, head `332a1ab`, `G0_DB_PATH` unset):** `uv sync --frozen` ok · `uv run ruff check .` All checks passed! · `uv run mypy` Success: no issues found in 17 source files · `uv run pytest` 87 passed · `gardener simulate --ticks 96` exit 0, report identical to `docs/daily-report-simulated.md` · `gardener quality` exit 0, identical to `docs/quality-report.md`. **CI:** run 4 (push, `332a1ab`): success.

**Not verified:** still no live model call and no real 24-hour wall-clock run; the S7 fix narrows the owner-save window to the instant before `os.replace` but cannot close it on a plain filesystem; lease renewal was tested with a simulated slow clock, not a real slow SDK call or a sleeping laptop; `unsupported` notes are not listed in the daily report (see `gardener status` / the state table).

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
