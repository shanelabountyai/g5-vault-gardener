# Release notes — G5·C Vault Gardener

## Not deployed — portfolio pack 2026-11-24

**Nothing here is deployed, hosted or running anywhere.** G5·C runs locally on a synthetic vault with hand-written recorded model responses: no API key, no live model call, $0 model spend (D-1, D-9). Every figure below is **recorded/synthetic** (estimated tokens, simulated clock) unless it says otherwise.

### What exists, by PR and commit

Each SHA below was checked with `git cat-file` and `git merge-base --is-ancestor <sha> main` on 2026-11-24.

| When | PR / commit | What |
|---|---|---|
| 2026-11-21 | `f376a44` | Kickoff kit: `CLAUDE.md`, `KICKOFF.md`, `docs/prd.md` (PRD v0.1, dated 2026-11-03). |
| 2026-11-21 | PR #1 (`build/g5c`, head `b4bcd19`), merged as `963e15b` | The full G5·C build: safety invariants with tests first, synthetic fixtures, SQLite state table with leases + compare-and-swap + two-phase change log, Watcher/Classifier/Linker, supervisor with cost/token cap, error burst and kill switch, 15-minute loop on an injectable clock, OpenTelemetry to a local file, G0 attached at `6f5e605`, CLI, CI. Decisions D-1..D-26. 77 tests at merge. |
| 2026-11-22 | PR #2 (`review-fixes/2026-11-22`), fixes `0ce71e1`..`02525f8`, decisions `332a1ab` | Overnight review: 2 must-fix + 7 should-fix fixed, each with a failing test first (CRLF/BOM handling, invalid YAML, tag quoting, frontmatter comments, lease renewal, owner-save window, kill switch during a call, reconcile). D-27..D-32. |
| 2026-11-23 | PR #2, `0ebf8d6`, `428e0d1`, `8afcacf`, `d6d342d`; merged as `6e1f87c` | Owner decisions built: resume resets the error window (D-33), failure-share trip (D-34), uniform CRLF/BOM notes edited in their own form (D-35); D-36 open items. 92 tests. |
| 2026-11-24 | this branch, `portfolio-pack/2026-11-24` (docs only) | The pack below. No code, test, fixture, config, CI or report changed. |

### Gate on 2026-11-24 (local, `main` at `6e1f87c`, the same steps as `.github/workflows/ci.yml`)

`uv sync --frozen` exit 0 · `uv run ruff check .` exit 0, "All checks passed!" · `uv run mypy` exit 0, "no issues found in 17 source files" · `uv run pytest` exit 0, 92 passed · 96-tick simulation exit 0, report byte-identical to `docs/daily-report-simulated.md` · quality report exit 0, byte-identical to `docs/quality-report.md` · `uv run gardener demo` exit 0, "Demo passed."

Recorded/synthetic results of that run: 96 simulated ticks, 0 note bodies changed, 68 notes processed, 79 tags and 203 links added, 3 errors (designed), 0 trips, $0.0156 **estimated**; quality on designed mistakes: tag precision 0.9375, recall 0.9091, type accuracy 0.95, link precision 0.9661, 17/20 pass.

### The pack

| Item | Where | State |
|---|---|---|
| Demo walk-through | `docs/DEMO.md` | 13 stops; 11 fully verified by tests/commands, 2 not yet clicked through by Shane |
| Exec brief "G5·C Vault Gardener in Brief" | [Claude Docs (private)](https://claude.ai/artifact/XsLgc72QmmhhhXnv3kd5RL) | Existing 2026-11-23 doc updated in place (as-of date, gate line, cost D-row); not shared |
| LinkedIn drafts | `docs/LINKEDIN_DRAFTS.md` | Two drafts (D-25/D-34, D-24); drafted, unposted |
| Cost note | `docs/DECISIONS.md` D-37 | Build and running cost not measured; $0 model spend; caps listed as limits |
| Release notes | `docs/RELEASE_NOTES.md` | This entry |
| Status and hand steps | `NEXT.md` (2026-11-24 section) | Done / verified / not verified / "You:" steps |

### Not verified

No real 24-hour wall-clock run; no live model call, so no real tokens, cost or quality; `AgentSdkCaller` has never run; no real vault; no deployment.
