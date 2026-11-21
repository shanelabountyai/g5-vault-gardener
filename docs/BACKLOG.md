# Backlog — G5·C Vault Gardener (code version)

G5·B (n8n) is out of scope for this build (D-2); the owner builds it by hand. Each task is one sitting. Safety invariants land with tests **before** any agent code can write (C2 before C5). Acceptance criteria (AC) are the PRD's.

| # | Task | Acceptance | Status |
|---|---|---|---|
| C1 | Skeleton: `pyproject.toml` (Python 3.12, uv), G0 pinned by SHA, `gardener` console script, ruff + mypy + pytest, CI workflow. | `uv sync --frozen`, `ruff check`, `mypy`, `pytest` run locally and in CI. | todo |
| C2 | **Safety first** (`note.py`, `safety.py`): frontmatter/body split, managed Related block, body hash, `check_change(before, after)`; copy-vault guard. | Tests: body hash stable across tag/type/Related edits; any body edit, deletion, non-tags/type frontmatter edit, tag removal or type overwrite is refused; the worker refuses the fixture vault and unmarked vaults. | todo |
| C3 | Synthetic fixtures (`fixtures/make_fixtures.py`): 63-note vault, arrivals, taxonomy, 20-note labeled sample, hand-written recorded responses with designed mistakes (D-24). | Generator is deterministic (test regenerates and diffs); no real names/companies (test scans for an allow-list of words is impractical, so the generator uses only topic vocabulary and the test checks there are no emails/URLs). | todo |
| C4 | State table (`state.py`): notes, runs, changes, errors, supervisor; leases (`BEGIN IMMEDIATE`), two-phase change log, CAS writer, `check_consistency()`, reconcile on start. | Lease can't be taken twice; expired lease can; CAS refuses a stale write; consistency check catches a held lock, a pending change, a file that doesn't match its last change. | todo |
| C5 | Agents (`agents.py`): Watcher, Classifier, Linker behind `ModelCaller` (`llm.py`: `RecordedCaller`, `AgentSdkCaller`, fault injection); prompts with no copied G0 rules. | Watcher writes state only; Classifier writes only tags/type; Linker only the managed block; `--suggest-only` writes no note; unknown tags/targets dropped; malformed output is an error. | todo |
| C6 | Supervisor (`supervisor.py`): daily cost/token budget from G0 run totals, error burst, safety trips, kill switch, alert log; injectable clock (`clock.py`); worker loop (`worker.py`). | **AC2** cost spike trips and stops; **AC3** error burst trips and stops; kill switch leaves the state consistent; trip persists until `resume`. | todo |
| C7 | Concurrency. | **AC4**: two agents on the same note (forced interleaving, threads, two processes) never produce a conflicting write; the per-note change chain is unbroken. | todo |
| C8 | OpenTelemetry (`telemetry.py`): span per tick and per agent call, JSONL file exporter. | Trace file has one tick span per tick with agent-call children carrying tokens/cost. | todo |
| C9 | Simulation + daily report (`simulate.py`, `report.py`): 96 ticks on a temp copy, arrivals, per-tick body hashing; report = notes processed, links added, errors, cost. | **AC1** 0 bodies changed over 96 ticks; **AC5** report has the four figures and they reconcile with the state table and G0. | todo |
| C10 | Revert (`gardener revert`). | Revert of all runs restores the copy vault byte-for-byte; a file edited after the change is reported as a conflict and left alone. | todo |
| C11 | Quality report (`quality.py`) against the labeled sample via G0 `evaluation`. | Tag precision/recall, type accuracy, link precision; recomputed in a test from the fixtures' designed mistakes. | todo |
| C12 | Defaults from the recorded day (D-4), README, demo command, NEXT.md, PR. | Test re-derives the default cap; gate results recorded verbatim. | todo |

## Later (not in this build)

- A real 24-hour wall-clock run on the copy vault (owner).
- First live run with a key (`--live`) to replace hand-written responses and measure a real day's cost; then reset the D-4 defaults.
- G0 `rubric.register` tool so consumers stop seeding through the loader.
- Pointing the worker at a copy of the real Lab vault (owner decision; the copy guard stays).
- G5·B in n8n (owner, by hand).

## Owner hand steps

See NEXT.md, section 2026-11-21 ("You:" steps).
