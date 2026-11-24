# Demo walk-through — G5·C Vault Gardener

**Not deployed.** This is a local command-line walk-through on a laptop. Everything runs on the synthetic vault (D-1) and hand-written recorded model responses (D-9): no API key, no live model call, $0 spend. Token counts and cost are **estimated** (characters / 4) from those recorded fixtures, and the "day" is a **simulated** 96-tick clock (D-19), not a wall-clock day. There is no screen UI; each stop below is a command and what it shows.

Each stop says how it was checked on 2026-11-24 (branch `portfolio-pack/2026-11-24`, cut from `main` at `6e1f87c`): a named test in `tests/`, a command run in that session, or **not yet clicked through by Shane** where only a person can do it.

## At a glance

| | |
|---|---|
| **Who it is for** | Someone with a few hundred notes in an Obsidian-style vault who stopped tagging and linking them, and who will only let an agent near the notes if it provably cannot damage them. Also anyone judging whether an always-on agent job can be left alone. |
| **What was decided** | Agents may only add frontmatter `tags`/`type` and a managed "Related" block; the note body is hashed byte-exact and must never change (D-11, D-12). Folders are suggested, never moved (D-13). Row leases plus compare-and-swap writes so two agents cannot collide (D-14). A supervisor trips on daily cost/tokens, an error burst, a failure share or any safety refusal, and stays stopped until the owner resumes (D-15, D-33, D-34). Uniform CRLF/BOM notes are edited in their own form (D-35). Synthetic vault and recorded responses with designed mistakes (D-1, D-9, D-24). |
| **What was left out** | The n8n version G5·B (D-2), a Gmail inbox (D-3), file moves (D-13), a per-tick note limit (D-23), any live model call, any real vault, external alerting (alerts go to a local log), any deployment. Still provisional: D-1, D-4, D-5, D-6, D-10; still open: D-36. |
| **The complete journey** | Drop a note in `inbox/` (or edit any note) → on the next 15-minute tick the Watcher queues it → the Classifier adds taxonomy tags and a type (and records a folder suggestion) → the Linker appends up to 5 related links → the daily report gives notes processed, links added, errors and cost → `gardener revert` can undo any run. |
| **Why come back in week three** | It only adds: tags are a union, an existing type is never overwritten, links already in the note are never repeated (D-26). A bad day stops itself and waits for you. Every change is a before/after row you can undo byte for byte. |
| **The design** | The safety lives outside the model. One write path (`State.write_note`) checks the lease, re-checks the file hash, runs `safety.check_change`, logs the change `pending`, writes, marks it `applied`. The model only proposes; tags outside the taxonomy and links to unknown notes are dropped. Cost is read back from the shared layer G0 (D-7, D-16). |

## Walk-through

1. **Install (locked).** `uv sync --frozen`
   Verified by command: exit 0 on 2026-11-24.

2. **The whole story in one command.** `uv run gardener demo` (about 5–10 s, temp dirs). Prints the simulated day, two forced trips, the quality figures and a byte-exact revert, then `Demo passed.`
   Verified by command (exit 0, `Demo passed.`, 2026-11-24) and by test `test_demo_passes`.

3. **A simulated day and its daily report (AC1, AC5).** `uv run gardener simulate --ticks 96 --report out/daily.md`
   Shows 96 ticks, 0 bodies changed, 0 files deleted, 0 consistency problems, 0 trips; the report has notes processed 68, links added 203, errors 3, cost $0.0156 (**estimated, recorded fixtures**).
   Verified by command (exit 0; report byte-identical to `docs/daily-report-simulated.md`) and by tests `test_ac1_96_ticks_no_body_changed_or_deleted`, `test_ac1_untouched_bodies_equal_the_fixture_at_the_end`, `test_ac5_daily_report_has_the_four_figures_and_they_reconcile`.

4. **A forced cost spike stops the job (AC2).** `uv run gardener simulate --inject cost-spike@10`
   Shows the supervisor tripping (`cost`) at tick 18, 0 model calls in the next 3 ticks, an alert line in `alerts.log`.
   Verified by test `test_ac2_cost_spike_trips_and_stops` (also `test_ac2_token_budget_trips_too`), and by the `gardener demo` run above.

5. **A forced error burst stops the job (AC3).** `uv run gardener simulate --inject error-burst@0`
   Shows a trip (`error_burst`) at tick 0 after 5 errors, no 6th call. A steady-state outage trips on failure share instead (D-34).
   Verified by tests `test_ac3_error_burst_trips_and_stops`, `test_ac3_error_burst_mid_day_across_ticks`, `test_steady_state_outage_trips_on_failure_share`, and by the `gardener demo` run above.

6. **Two agents on one note never conflict (AC4).** No command; this is a test-only behaviour.
   Verified by tests `test_ac4_lease_locks_out_the_second_agent`, `test_ac4_stale_read_cannot_overwrite_a_newer_write`, `test_ac4_two_threads_hammering_one_note`, `test_ac4_two_workers_race_on_one_state_table`, `test_ac4_two_worker_processes`.

7. **Quality against the labeled sample.** `uv run gardener quality --out out/quality.md`
   Shows tag precision 0.9375, tag recall 0.9091, type accuracy 0.95, link precision 0.9661, 17 of 20 notes passing the G0 rubric. These come from mistakes written into the recorded responses on purpose (D-24); they are **synthetic**, not a model measurement.
   Verified by command (exit 0; report byte-identical to `docs/quality-report.md`) and by test `test_quality_findings_are_exactly_the_designed_mistakes`.

8. **The copy-vault guard.** `uv run gardener copy-fixture ~/gardener/vault` makes a marked copy; `gardener run --vault fixtures/vault …` is refused.
   Verified by command (copy exit 0; run on the fixture exit 1 with `NotACopyVault`, printed as a Python traceback) and by tests `test_cli_run_on_the_fixture_itself_is_refused`, `test_worker_refuses_fixture_vault_and_unmarked_vaults`.

9. **The 15-minute loop on the copy.** `uv run gardener run --vault ~/gardener/vault --state ~/gardener/state` (add `--ticks 2 --sim-clock` for a fast check).
   Verified with the simulated clock by command (`--ticks 2 --sim-clock`: tick 0 classified 62, links +185, 1 error; exit 0) and by test `test_cli_end_to_end`. **The real wall-clock loop: not yet clicked through by Shane.**

10. **Drop a note in the inbox and watch it get tended.** Put a `.md` file in `~/gardener/vault/inbox/` while the loop runs.
    The scheduled arrivals of the simulated day are verified by test `test_ac1_arrivals_and_owner_edits_were_processed`. **By hand: not yet clicked through by Shane.** A new note needs a recorded response or `--live` (NEXT.md, 2026-11-21).

11. **Status, report, kill switch, revert, resume.** `gardener status`, `gardener report --state … --out r.md`, `gardener kill --reason …`, `gardener run …` (refused while killed, exit 3), `gardener revert --all`, `gardener resume`.
    Verified by command (each exit code as stated; revert restored 124 changes, 0 conflicts) and by tests `test_cli_end_to_end`, `test_trip_persists_across_restart_until_resume`, `test_kill_switch_mid_tick_leaves_the_state_consistent`, `test_revert_all_restores_the_vault_byte_for_byte`, `test_revert_skips_a_file_the_owner_edited_since`.

12. **Suggest-only Linker.** `gardener run … --suggest-only` writes `<state>/suggestions.jsonl` and leaves notes without a Related block (D-5).
    Verified by tests `test_suggest_only_writes_no_related_section`, `test_suggest_only_day_changes_no_note`. Not run by command in this session.

13. **Traces.** `<state>/traces.jsonl` holds one span tree per tick (OpenTelemetry, local file only, D-18).
    Verified by test `test_traces_one_span_per_tick_with_agent_call_children`; the file was produced by the stop 9 command.

## What this walk-through does not show

- A real 24-hour wall-clock run, a live model call, real tokens or a real bill.
- A real vault: only the synthetic one in `fixtures/` (D-1).
- Any hosted or deployed version: there is none.
