"""AC1 (a simulated 24 h with no body changed or deleted), AC5 (daily report), traces, defaults (D-4, D-18, D-19).

AC1 here is a time-compressed simulation: 96 ticks of 15 minutes on a simulated clock. A real 24-hour wall-clock
run was not done in this build (owner step, NEXT.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import BIG
from vault_gardener import note
from vault_gardener.clock import SimClock
from vault_gardener.config import (
    DEFAULT_DAILY_CAP_USD,
    DEFAULT_DAILY_TOKEN_BUDGET,
    FIXTURE_VAULT,
    RECORDED_DAY_COST_USD,
    RECORDED_DAY_TOKENS,
    derive_cap_usd,
    derive_token_budget,
)
from vault_gardener.layer import Layer
from vault_gardener.report import daily_report, render_markdown
from vault_gardener.simulate import SimResult, body_hashes, simulate
from vault_gardener.state import State
from vault_gardener.telemetry import read_spans


@pytest.fixture(scope="module")
def day(tmp_path_factory: pytest.TempPathFactory) -> SimResult:
    return simulate(tmp_path_factory.mktemp("day") / "s", ticks=96)


def test_ac1_96_ticks_no_body_changed_or_deleted(day: SimResult) -> None:
    s = day.summary()
    assert s["ticks_run"] == 96 and s["simulated_hours"] == 24
    assert day.bodies_changed == [], "an agent changed a note body"
    assert day.files_deleted == []
    assert day.consistency_problems == []
    assert day.trips == []
    assert s["events_applied"] == 9 and s["owner_body_edits"] == 3


def test_ac1_untouched_bodies_equal_the_fixture_at_the_end(day: SimResult) -> None:
    final = body_hashes(day.vault)
    edited = {"logs/sourdough-starter-log.md", "projects/tomato-bed-rotation.md", "projects/cli-todo-tool.md"}
    for path, h in body_hashes(FIXTURE_VAULT).items():
        if path not in edited:
            assert final[path] == h, path
    for path in edited:
        assert final[path] != body_hashes(FIXTURE_VAULT)[path]  # the owner's edits are kept, not undone


def test_ac1_arrivals_and_owner_edits_were_processed(day: SimResult) -> None:
    for slug in ("pizza-dough-test", "aphids-on-the-kale", "typing-tip-protocols", "meteor-shower-dates", "saddle-height-fix",
                 "novel-recommendation"):
        n = note.parse((day.vault / "inbox" / f"{slug}.md").read_text())
        assert n.tags() and n.type() and n.related, slug
    st = State(day.state_dir / "state.sqlite", day.vault, SimClock())
    for p in ("logs/sourdough-starter-log.md", "projects/tomato-bed-rotation.md", "projects/cli-todo-tool.md"):
        assert st.conn.execute("SELECT COUNT(*) FROM changes WHERE path=? AND agent='classifier'", (p,)).fetchone()[0] >= 1
        assert note.parse((day.vault / p).read_text()).body.count(note.RELATED_START) <= 1
    st.close()


def test_ac5_daily_report_has_the_four_figures_and_they_reconcile(day: SimResult) -> None:
    st = State(day.state_dir / "state.sqlite", day.vault, SimClock())
    layer = Layer(str(day.state_dir / "g0.sqlite"))
    rep = daily_report(st, layer, day.day, record=False)
    s = day.summary()
    assert rep["ticks"] == 96
    assert rep["notes_processed"] == 68  # 69 notes at day end, one parked after a malformed response
    assert rep["links_added"] == s["links_added"] == rep["crosscheck"]["links_added_from_g0_events"]
    assert rep["errors"] == s["errors"] == rep["crosscheck"]["errors_from_g0_events"] == 3
    assert rep["cost_usd"] == pytest.approx(s["cost_usd_estimated"])
    assert rep["tokens"] == s["tokens_estimated"]
    assert rep["crosscheck"]["g0_tick_events"] == 96
    assert rep["notes_parked_error"] == ["inbox/router-reboot-again.md"]
    md = render_markdown(rep)
    for label in ("Notes processed", "Links added", "Errors", "Cost (USD)", "estimated"):
        assert label in md
    st.close()
    layer.close()


def test_traces_one_span_per_tick_with_agent_call_children(day: SimResult) -> None:
    spans = read_spans(day.state_dir / "traces.jsonl")
    ticks = [s for s in spans if s["name"] == "gardener.tick"]
    calls = [s for s in spans if s["name"] in ("gardener.classifier.call", "gardener.linker.call")]
    assert len(ticks) == 96
    assert len(calls) == day.summary()["model_calls"]
    tick_traces = {s["context"]["trace_id"] for s in ticks}
    assert all(c["context"]["trace_id"] in tick_traces for c in calls)
    c = calls[0]["attributes"]
    assert c["gen_ai.usage.input_tokens"] > 0 and "gardener.cost_usd" in c and c["gardener.tokens_estimated"] is True
    assert ticks[0]["attributes"]["gardener.status"] == "ok"


def test_trip_is_a_span_event(tmp_path: Path) -> None:
    res = simulate(tmp_path / "s", ticks=3, inject=("error-burst", 0))
    spans = read_spans(tmp_path / "s" / "traces.jsonl")
    events = [e["name"] for s in spans for e in s.get("events", [])]
    assert "supervisor.trip" in events and res.trips


def test_default_limits_match_the_recorded_day(tmp_path: Path) -> None:
    """D-4: the defaults are HEADROOM x a fresh recorded 96-tick day; this fails if fixtures or prompts change."""
    res = simulate(tmp_path / "s", ticks=96, limits=BIG)
    s = res.summary()
    assert s["cost_usd_estimated"] == pytest.approx(RECORDED_DAY_COST_USD, abs=1e-6)
    assert s["tokens_estimated"] == RECORDED_DAY_TOKENS
    assert derive_cap_usd(RECORDED_DAY_COST_USD) == DEFAULT_DAILY_CAP_USD
    assert derive_token_budget(RECORDED_DAY_TOKENS) == DEFAULT_DAILY_TOKEN_BUDGET


def test_suggest_only_day_changes_no_note(tmp_path: Path) -> None:
    res = simulate(tmp_path / "s", ticks=96, suggest_only=True)
    assert res.bodies_changed == [] and res.trips == []
    assert not any(note.parse(f.read_text()).has_block for f in res.vault.rglob("*.md"))
