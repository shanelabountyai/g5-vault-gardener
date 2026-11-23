# g5-vault-gardener — Vault Gardener (G5·C)

Build log G5, Agentic AI track, the capstone. Every 15 minutes three agents tend a notes vault: a **Watcher** finds new or changed notes, a **Classifier** tags and types them, a **Linker** adds related-note links. A **Supervisor** watches cost and errors and stops the job past a limit; a **kill switch** stops everything and leaves the state consistent.

This is a portfolio sample build. It runs on a **synthetic vault** (63 made-up notes; D-1) and **hand-written recorded model responses** (no API key, no live call, $0 spend; D-9). Token counts are estimated as characters / 4. **Every number below describes those fixtures, not a model.** The 24-hour criterion is proved with a 96-tick simulated clock; **a real 24-hour wall-clock run has not been done** (owner step).

Spec: `docs/prd.md` · decisions: `docs/DECISIONS.md` (D-1..D-26) · backlog: `docs/BACKLOG.md` · reports: `docs/daily-report-simulated.md`, `docs/quality-report.md` · state and hand steps: `NEXT.md`. Only the code version is built here; the n8n version (G5·B) is the owner's hand build (D-2).

## At a glance

| | |
|---|---|
| **Who it's for** | Someone with a few hundred notes in an Obsidian-style vault who stopped tagging and linking them, and who will only let an agent near the notes if it provably cannot damage them. Also: anyone evaluating whether an always-on agent can be left alone. |
| **Journey** | Drop a note in `inbox/` (or edit any note) → within 15 minutes it has taxonomy tags, a type, a folder suggestion and a short "Related" list → the daily report says what was touched, what it cost and what failed → any run can be reverted. |
| **Why you'd still use it in week three** | It only adds: tags are a union, an existing type is never overwritten, the body is never touched, links already in the note are never repeated, and it suggests folders instead of moving files. A bad day stops itself (budget, error burst) and stays stopped until you look. Every change is a before/after row you can undo. |
| **Design intent** | Most failures here are process, not model. So the safety lives outside the model: a byte-exact body-hash check inside the only write path, row leases plus compare-and-swap so two agents cannot collide, a supervisor that reads the day's spend from the shared layer, and a copy-vault guard the worker cannot skip. The model only proposes; validation drops tags outside the taxonomy and links to notes that don't exist. |
| **Controls** | Daily cost cap and token budget (provisional defaults: 3× the recorded day, D-4) · error burst (5 in 60 min) · failure share (≥ 80% of at least 3 attempts in 60 min failed, D-34) · safety trip on any invariant breach · kill switch (`gardener kill` / `resume`) · `--suggest-only` Linker · `gardener revert` · copy-vault marker required · OpenTelemetry traces in a local file · G0 `$10` per-run cap underneath. |
| **Cuts** | No n8n version here (owner builds G5·B). No live model run, so no measured cost or quality. No real vault: the synthetic one ships in the public repo. No Gmail inbox (D-3). No file moves (D-13). No per-tick note limit (D-23). No external alerting: alerts go to a local log. |

## How it works

```
gardener run --vault <copy> --state <dir>         (or: gardener simulate, on a temp copy with a simulated clock)
  start: copy-vault guard → G0 health → reconcile half-written changes → refuse if the kill switch is set
  every 15 min (injectable clock):
    Watcher     scan *.md → state table: new / changed → pending_classify           writes: state table only
    Classifier  per pending note, under its lease:
                  supervisor.check → model (recorded | Agent SDK) → validate → tags ∪ taxonomy tags, type if missing
                  → State.write_note: lease held? file unchanged (CAS)? safety.check_change? log pending → write → applied
    Linker      per classified note, same path: up to 5 known note ids → managed "Related" block (or suggestions.jsonl)
    every call  → G0 observability (day run id) → supervisor.after_call: daily cost / tokens / G0 cap
    every error → errors table + G0 → supervisor: 5 in 60 min → trip
    trip        → kill switch (state table) + alerts.log + G0 measurement event; leases released; loop stops
  per tick: one `runs` row, one G0 `vault_gardener.tick` event, one OTel span tree in <state>/traces.jsonl
```

| File | What |
|---|---|
| `src/vault_gardener/safety.py`, `note.py` | The invariants (written and tested first): body = text minus frontmatter minus the managed block, hashed byte-exact; only `tags`/`type` lines may change; tags only grow; type never overwritten; copy-vault guard. |
| `src/vault_gardener/state.py` | One SQLite state table: notes + leases, two-phase change log (whole file before/after), runs, errors, kill switch, `write_note` (the only write path), `revert`, `reconcile`, `check_consistency`. |
| `src/vault_gardener/agents.py` | Watcher, Classifier, Linker; output validation; folder suggestions recorded, never acted on. |
| `src/vault_gardener/supervisor.py` | Budget, error burst, safety trips, kill switch, alert log. Spend is read back from G0. |
| `src/vault_gardener/worker.py`, `clock.py` | The 15-minute loop on an injectable clock. |
| `src/vault_gardener/llm.py` | `RecordedCaller` (used), `AgentSdkCaller` (Claude Agent SDK `query`, structured output; never run here), `FaultInjectingCaller` (AC2/AC3). Prompts carry no shared-layer rule. |
| `src/vault_gardener/layer.py` | The one G0 adapter (in-process, pinned SHA); seeds rubric `g5_note_labels_v1` through G0's loader (D-8). |
| `src/vault_gardener/telemetry.py` | OpenTelemetry SDK, private provider, JSONL file exporter. |
| `src/vault_gardener/simulate.py`, `report.py`, `quality.py`, `demo.py`, `cli.py` | Simulated day, daily report, labeled-sample quality, one-command demo, CLI. |
| `fixtures/` | `make_fixtures.py` (deterministic generator), `vault/` (63 notes), `arrivals/` + `arrivals.json` (6 inbox arrivals, 3 owner edits during the day), `taxonomy.json`, `labels.json` (20 hand-labeled notes), `recorded.json` (hand-written responses with designed mistakes, D-24). |

## Shared layer (G0)

Pinned to `shanelabountyai/g0-shared-layer@6f5e605` exactly as G3·C (D-7). **observability**: every agent call (tokens, cost) under run id `g5-<date>`, so G0's run total *is* the day's spend the supervisor reads. **measurement**: `vault_gardener.tick`, `vault_gardener.supervisor_tripped`, `vault_gardener.daily_report`. **evaluation**: each labeled note is scored by G0 with rubric `g5_note_labels_v1`, seeded through G0's own loader because v1 has no register tool (D-8, the documented G2/G3 exception). Prices are G0's table; this repo has none.

## Acceptance (PRD) — where each is proved

| AC | Evidence |
|---|---|
| 1 24 h on the copy vault, no body changed or deleted | `test_ac1_96_ticks_no_body_changed_or_deleted` (96 ticks × 15 min simulated, 9 scheduled events, bodies hashed before/after every tick: 0 changed, 0 deleted, 0 consistency problems), `test_ac1_untouched_bodies_equal_the_fixture_at_the_end`, `test_ac1_arrivals_and_owner_edits_were_processed`. **Simulated, not wall-clock.** |
| 2 Forced cost spike trips the supervisor and stops the job | `test_ac2_cost_spike_trips_and_stops` (spike from tick 10 → trips at tick 18, 0 calls in the next 3 ticks, alert written), `test_ac2_cost_spike_on_the_startup_backlog_…`, `test_ac2_token_budget_trips_too` |
| 3 Forced error burst trips it | `test_ac3_error_burst_trips_and_stops` (5th error → stop, no 6th call), `test_ac3_error_burst_mid_day_across_ticks` (D-25) |
| 4 Two agents on one note never write in conflict | `test_ac4_lease_locks_out_the_second_agent`, `test_ac4_stale_read_cannot_overwrite_a_newer_write` (CAS), `test_ac4_two_threads_hammering_one_note` (60 + 60 writes, none lost), `test_ac4_two_workers_race_on_one_state_table`, `test_ac4_two_worker_processes` |
| 5 Daily report: notes processed, links added, errors, cost | `test_ac5_daily_report_has_the_four_figures_and_they_reconcile` (runs table = G0 events = G0 run total); sample: `docs/daily-report-simulated.md` |
| Safety rules | `tests/test_safety.py` (written first), `test_a_safety_violation_trips_and_writes_nothing`, `test_kill_switch_mid_tick_leaves_the_state_consistent`, `test_revert_all_restores_the_vault_byte_for_byte` |

On the recorded fixtures (`gardener simulate`, `gardener quality`, 2026-11-21): a 96-tick day made 145 model calls, 68 notes processed, 79 tags and 203 links added, 3 errors (one designed malformed response, retried and parked), 0 trips, ~144.8k estimated tokens, $0.0156 estimated. Against the 20-note labeled sample: tag precision 0.9375, tag recall 0.9091, type accuracy 0.95, link precision 0.9661, 17/20 notes pass the G0 rubric. These come from mistakes written into the fixtures on purpose (D-24); they say the measuring works, not how good a model is.

## Running it

```bash
uv sync --frozen
uv run ruff check . && uv run mypy && uv run pytest
uv run gardener demo                                   # the whole story in one command (temp dirs, ~10 s)

uv run gardener simulate --ticks 96 --report out/daily.md        # AC1 + AC5 on a temp copy
uv run gardener simulate --inject cost-spike@10                  # AC2 (exit 0 when it trips as intended)
uv run gardener simulate --inject error-burst@0                  # AC3
uv run gardener quality --out docs/quality-report.md             # labeled-sample quality

uv run gardener copy-fixture ~/gardener/vault                    # a marked copy; the worker refuses anything else
uv run gardener run --vault ~/gardener/vault --state ~/gardener/state             # the real 15-minute loop
uv run gardener kill   --vault ~/gardener/vault --state ~/gardener/state          # stop; then: status / revert --all / resume
```

`--suggest-only` makes the Linker write `<state>/suggestions.jsonl` instead of notes (D-5). `--live` needs `ANTHROPIC_API_KEY` and was not used in this build. Limits: `--daily-cap-usd`, `--daily-token-budget`, `--error-burst`, `--error-window-min` (or `G5_*` environment variables). `G0_DB_PATH` overrides the shared layer's file (default `<state>/g0.sqlite`).
