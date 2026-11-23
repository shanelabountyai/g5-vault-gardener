"""Supervisor: AC2 (cost spike), AC3 (error burst), kill switch, safety trips (D-15)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vault_gardener import note
from vault_gardener.config import Limits
from vault_gardener.llm import CallResult, FaultInjectingCaller, RecordedCaller
from vault_gardener.simulate import simulate
from vault_gardener.worker import KillSwitchSet


def test_ac2_cost_spike_trips_and_stops(tmp_path: Path) -> None:
    res = simulate(tmp_path / "s", ticks=96, inject=("cost-spike", 10))
    assert [t["reason"] for t in res.trips] == ["cost"]
    assert res.stopped_at is not None and res.stopped_at >= 10 and res.ticks_run < 96
    assert res.calls_after_trip == 0, "the job stays stopped"
    assert res.consistency_problems == [] and res.bodies_changed == []
    alert = json.loads((tmp_path / "s" / "alerts.log").read_text().splitlines()[0])
    assert alert["reason"] == "cost" and "cap" in alert["detail"]
    assert res.results[-1].status == "tripped"


def test_ac2_cost_spike_on_the_startup_backlog_trips_on_the_first_spiked_call(tmp_path: Path) -> None:
    res = simulate(tmp_path / "s", ticks=5, inject=("cost-spike", 0))
    assert res.trips[0]["reason"] == "cost" and res.stopped_at == 0
    assert res.results[0].counts.model_calls == 1
    assert res.consistency_problems == []


def test_ac2_token_budget_trips_too(tmp_path: Path) -> None:
    res = simulate(tmp_path / "s", ticks=2, limits=Limits(daily_cap_usd=100, daily_token_budget=20_000))
    assert res.trips[0]["reason"] == "tokens"
    assert res.consistency_problems == []


def test_ac3_error_burst_trips_and_stops(tmp_path: Path) -> None:
    res = simulate(tmp_path / "s", ticks=96, inject=("error-burst", 0))
    assert [t["reason"] for t in res.trips] == ["error_burst"]
    assert res.results[0].counts.errors == 5  # the limit, then stop: no sixth call
    assert res.calls_after_trip == 0
    assert res.consistency_problems == [] and res.bodies_changed == []


def test_ac3_error_burst_mid_day_across_ticks(tmp_path: Path) -> None:
    """Errors spread over several ticks still trip when they fall inside the window."""
    events = {"events": [{"tick": 5, "action": "add", "path": f"inbox/batch-{i}.md", "source": src}
                         for i, src in enumerate(["arrivals/pizza-dough-test.md", "arrivals/saddle-height-fix.md", "arrivals/meteor-shower-dates.md"])]}
    ef = tmp_path / "events.json"
    ef.write_text(json.dumps(events))
    caller = RecordedCaller()
    for i, src in enumerate(["pizza-dough-test", "saddle-height-fix", "meteor-shower-dates"]):
        caller.responses[f"classifier:inbox/batch-{i}.md"] = caller.responses[f"classifier:inbox/{src}.md"]
    res = simulate(tmp_path / "s", ticks=96, inject=("error-burst", 5), events_file=ef, caller=caller)
    assert res.trips and res.trips[0]["reason"] == "error_burst"
    # The malformed fixture note fails at ticks 0, 1, 2 (00:00, 00:15, 00:30; then parked). At tick 5 (01:15) the
    # 60-minute window still holds the 00:15 and 00:30 errors, so the batch's 3rd failure is the 5th → trip at tick 5.
    assert res.stopped_at == 5
    assert res.results[5].status == "tripped" and res.results[5].counts.errors == 3
    assert all(r.status == "ok" for r in res.results[:5])
    assert res.consistency_problems == []


def test_normal_day_does_not_trip_with_default_limits(tmp_path: Path) -> None:
    res = simulate(tmp_path / "s", ticks=96)
    assert res.trips == [] and res.ticks_run == 96


def test_kill_switch_mid_tick_leaves_the_state_consistent(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    class KillAfter(RecordedCaller):
        def __init__(self, state, n: int) -> None:  # type: ignore[no-untyped-def]
            super().__init__()
            self.state, self.n = state, n

        def call(self, spec, user_text, key) -> CallResult:  # type: ignore[no-untyped-def]
            r = super().call(spec, user_text, key)
            if sum(self.calls.values()) == self.n:
                self.state.set_killed("manual", "owner pressed stop", None)  # as `gardener kill` would, from outside
            return r

    w = make_worker()
    caller = KillAfter(w.state, 20)
    w.caller = caller
    r = w.tick()
    assert r.status == "tripped" and r.reason == "manual"
    assert sum(caller.calls.values()) == 20, "no model call after the switch is seen"
    assert w.state.check_consistency() == []
    statuses = {row["status"] for row in w.state.rows()}
    assert statuses <= {"pending_classify", "pending_link"}
    assert w.tick().status == "killed"
    assert sum(caller.calls.values()) == 20


def test_trip_persists_across_restart_until_resume(make_worker, tmp_path: Path, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    w.state.set_killed("cost", "test", None)
    w.close()
    with pytest.raises(KillSwitchSet):
        make_worker()
    from vault_gardener.cli import main

    assert main(["status", "--vault", str(vault), "--state", str(tmp_path / "state")]) == 3
    assert main(["resume", "--vault", str(vault), "--state", str(tmp_path / "state")]) == 0
    assert make_worker().tick().status == "ok"


def test_a_safety_violation_trips_and_writes_nothing(make_worker, vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    real = note.set_related

    def evil(text: str, targets: list[str]) -> str:
        return real(text, targets).replace("# ", "#  ", 1)  # a buggy Linker that also edits the title

    monkeypatch.setattr(note, "set_related", evil)
    w = make_worker()
    before = {p: p.read_text() for p in vault.rglob("*.md")}
    r = w.tick()
    assert r.status == "tripped" and r.reason == "safety"
    assert w.state.conn.execute("SELECT COUNT(*) FROM changes WHERE agent='linker'").fetchone()[0] == 0
    for p, t in before.items():
        assert note.parse(p.read_text()).body == note.parse(t).body
    assert w.state.check_consistency() == []


def test_fault_injector_passes_through_before_its_tick() -> None:
    inner = RecordedCaller()
    f = FaultInjectingCaller(inner, "cost-spike", 3)
    from vault_gardener.llm import CLASSIFIER

    f.tick = 2
    r = f.call(CLASSIFIER, "x", "classifier:reference/vlan-notes.md")
    assert r.input_tokens < 1000 and f.injected == 0
    f.tick = 3
    assert f.call(CLASSIFIER, "x", "classifier:reference/vlan-notes.md").input_tokens > 1_000_000


def test_kill_switch_set_during_a_call_stops_that_calls_write(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    # Review 2026-11-22 S8: the switch was checked only before each call, so a `gardener kill` that landed during a
    # call still let that call's result be written.
    class KillDuring(RecordedCaller):
        def __init__(self, state, n: int) -> None:  # type: ignore[no-untyped-def]
            super().__init__()
            self.state, self.n, self.key = state, n, ""

        def call(self, spec, user_text, key) -> CallResult:  # type: ignore[no-untyped-def]
            if sum(self.calls.values()) == self.n - 1:
                self.state.set_killed("manual", "owner pressed stop", None)
                self.key = key
            return super().call(spec, user_text, key)

    w = make_worker()
    caller = KillDuring(w.state, 5)
    w.caller = caller
    r = w.tick()
    assert r.status == "tripped" and r.reason == "manual"
    killed_path = caller.key.split(":", 1)[1]
    assert w.state.conn.execute("SELECT COUNT(*) FROM changes WHERE path=?", (killed_path,)).fetchone()[0] == 0
    assert w.state.check_consistency() == []


def test_resume_starts_a_fresh_error_window(make_worker) -> None:  # type: ignore[no-untyped-def]
    # D-33 (owner decision 2026-11-22): errors from before a resume no longer count toward the next burst, so the
    # first error after a resume cannot re-trip on its own. The error rows are kept (audit).
    from vault_gardener.supervisor import Tripped

    w = make_worker(limits=Limits(daily_cap_usd=100.0, daily_token_budget=10**9, error_burst=3, error_window_s=3600))
    with pytest.raises(Tripped):
        for i in range(3):
            w.supervisor.record_error(run_id="r", tick=0, agent="classifier", path=f"n{i}.md", kind="X", message="boom")
    assert w.state.clear_killed()
    w.supervisor.record_error(run_id="r", tick=0, agent="classifier", path="n9.md", kind="X", message="after resume")
    assert w.state.kill_state() is None
    assert w.state.conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0] == 4
