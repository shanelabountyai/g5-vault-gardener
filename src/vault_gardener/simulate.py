"""Time-compressed day on a temporary copy of the fixture vault (D-19, AC1–AC3, AC5).

`simulate(ticks=96)` = 24 hours of 15-minute ticks on a simulated clock. Between ticks it applies the scheduled
events in `fixtures/arrivals.json` (inbox arrivals, owner body edits), then hashes every note body before and after
each tick: any difference is an agent changing a body, which must never happen. After every tick it asserts the
state table is consistent. This is NOT a 24-hour wall-clock run; that is an owner step.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from vault_gardener import note, safety
from vault_gardener.clock import SimClock, day_id
from vault_gardener.config import ARRIVALS_FILE, FIXTURE_VAULT, FIXTURES_DIR, TICK_SECONDS, Limits
from vault_gardener.llm import FaultInjectingCaller, ModelCaller, RecordedCaller
from vault_gardener.worker import TickResult, Worker


def copy_fixture(dest: Path, source: Path | None = None) -> Path:
    """Copy the fixture vault to `dest` and mark it as a copy (the only kind of vault the worker accepts)."""
    src = source or FIXTURE_VAULT
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} exists and is not empty")
    shutil.copytree(src, dest, dirs_exist_ok=True)
    (dest / safety.COPY_MARKER).write_text("Copy of the synthetic fixture vault made by `gardener copy-fixture`. Agents may write here.\n",
                                           encoding="utf-8")
    return dest


def body_hashes(vault: Path) -> dict[str, str]:
    return {p.relative_to(vault).as_posix(): note.body_hash(p.read_bytes().decode("utf-8"))
            for p in sorted(vault.rglob("*.md")) if not any(part.startswith(".") for part in p.relative_to(vault).parts)}


def load_events(path: Path | None = None) -> dict[int, list[dict[str, Any]]]:
    doc = json.loads((path or ARRIVALS_FILE).read_text(encoding="utf-8"))
    out: dict[int, list[dict[str, Any]]] = {}
    for e in doc["events"]:
        out.setdefault(int(e["tick"]), []).append(e)
    return out


def apply_event(vault: Path, e: dict[str, Any]) -> None:
    target = vault / e["path"]
    if e["action"] == "add":
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES_DIR / e["source"], target)
    elif e["action"] == "user_edit":
        with open(target, "a", encoding="utf-8") as f:
            f.write(e["append"])
    else:  # pragma: no cover
        raise ValueError(f"unknown event {e['action']}")


@dataclass
class SimResult:
    ticks_run: int
    ticks_requested: int
    vault: Path
    state_dir: Path
    day: str
    bodies_changed: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    consistency_problems: list[str] = field(default_factory=list)
    trips: list[dict[str, Any]] = field(default_factory=list)
    stopped_at: int | None = None
    events_applied: int = 0
    user_body_edits: int = 0
    results: list[TickResult] = field(default_factory=list)
    calls_after_trip: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "ticks_requested": self.ticks_requested, "ticks_run": self.ticks_run, "simulated_hours": self.ticks_run * TICK_SECONDS / 3600,
            "bodies_changed_by_agents": len(self.bodies_changed), "files_deleted": len(self.files_deleted),
            "consistency_problems": len(self.consistency_problems), "supervisor_trips": len(self.trips),
            "trip_reasons": [t["reason"] for t in self.trips], "stopped_at_tick": self.stopped_at,
            "events_applied": self.events_applied, "owner_body_edits": self.user_body_edits,
            "notes_classified": sum(r.counts.notes_classified for r in self.results),
            "notes_linked": sum(r.counts.notes_linked for r in self.results),
            "links_added": sum(r.counts.links_added for r in self.results),
            "tags_added": sum(r.counts.tags_added for r in self.results),
            "errors": sum(r.counts.errors for r in self.results),
            "model_calls": sum(r.counts.model_calls for r in self.results),
            "tokens_estimated": sum(r.counts.input_tokens + r.counts.output_tokens for r in self.results),
            "cost_usd_estimated": round(sum(r.counts.cost_usd for r in self.results), 6),
            "calls_after_trip": self.calls_after_trip,
        }


def simulate(state_dir: Path, *, ticks: int = 96, inject: tuple[Literal["cost-spike", "error-burst"], int] | None = None,
             limits: Limits | None = None, suggest_only: bool = False, caller: ModelCaller | None = None,
             events_file: Path | None = None) -> SimResult:
    state_dir.mkdir(parents=True, exist_ok=True)
    vault = copy_fixture(state_dir / "vault")
    clock = SimClock()
    base: ModelCaller = caller or RecordedCaller()
    the_caller: ModelCaller = FaultInjectingCaller(base, inject[0], inject[1]) if inject else base
    events = load_events(events_file)
    worker = Worker(vault, state_dir, clock=clock, caller=the_caller, limits=limits or Limits.from_env(), suggest_only=suggest_only)
    res = SimResult(ticks_run=0, ticks_requested=ticks, vault=vault, state_dir=state_dir, day=day_id(clock.now()))
    try:
        for t in range(ticks):
            for e in events.get(t, []):
                apply_event(vault, e)
                res.events_applied += 1
                res.user_body_edits += e["action"] == "user_edit"
            before = body_hashes(vault)
            tr = worker.tick()
            res.results.append(tr)
            res.ticks_run += 1
            after = body_hashes(vault)
            res.files_deleted += [f"t{t}:{p}" for p in before if p not in after]
            res.bodies_changed += [f"t{t}:{p}" for p in before if p in after and after[p] != before[p]]
            res.consistency_problems += [f"t{t}: {p}" for p in worker.state.check_consistency()]
            if tr.status != "ok":
                res.stopped_at = t
                calls_before = sum(base.calls.values())
                # Prove it stays stopped: further ticks make no model call while the switch is set.
                for _ in range(3):
                    clock.sleep(TICK_SECONDS)
                    worker.tick()
                res.calls_after_trip = sum(base.calls.values()) - calls_before
                res.consistency_problems += [f"after-stop: {p}" for p in worker.state.check_consistency()]
                break
            clock.sleep(TICK_SECONDS)
        res.trips = list(worker.supervisor.trips)
    finally:
        worker.close()
    return res
