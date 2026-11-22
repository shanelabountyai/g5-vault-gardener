"""The long-running worker: a 15-minute loop driven by an injectable clock (PRD G5·C build notes, D-19, D-23).

Start-up: copy-vault guard → G0 health → reconcile half-written changes → refuse if the kill switch is set.
Each tick: Watcher → Classifier (every pending note) → Linker (every classified note), one span per tick, one
`runs` row, one G0 `vault_gardener.tick` event. A trip or the kill switch ends the loop with the state consistent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vault_gardener import agents, safety
from vault_gardener.clock import Clock, RealClock, day_id, iso
from vault_gardener.config import TAXONOMY_FILE, TICK_SECONDS, Limits, g0_db_path
from vault_gardener.layer import Layer
from vault_gardener.llm import ModelCaller, RecordedCaller
from vault_gardener.state import State
from vault_gardener.supervisor import Supervisor, Tripped
from vault_gardener.telemetry import Telemetry


class KillSwitchSet(RuntimeError):
    """The kill switch is set; the owner must run `gardener resume` before the worker starts again."""


@dataclass
class TickResult:
    tick: int
    run_id: str
    status: str  # ok | tripped | killed
    counts: agents.TickCounts
    reason: str | None = None
    detail: str | None = None
    watcher: dict[str, int] = field(default_factory=dict)


class Worker:
    def __init__(self, vault: Path, state_dir: Path, *, clock: Clock | None = None, caller: ModelCaller | None = None,
                 limits: Limits | None = None, layer: Layer | None = None, suggest_only: bool = False,
                 taxonomy_file: Path | None = None, worker_id: str | None = None, check_kill_on_start: bool = True) -> None:
        self.vault = safety.ensure_copy_vault(vault)
        self.state_dir = state_dir
        state_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock or RealClock()
        self.caller = caller or RecordedCaller()
        self.limits = limits or Limits.from_env()
        self._own_layer = layer is None
        self.layer = layer or Layer(g0_db_path(state_dir))
        self.layer.require_healthy()
        self.state = State(state_dir / "state.sqlite", self.vault, self.clock)
        self.state.reconcile()
        if check_kill_on_start and self.state.kill_state() is not None:
            k = self.state.kill_state() or {}
            self.close()
            raise KillSwitchSet(f"kill switch is set ({k.get('reason')}: {k.get('detail')}); run `gardener resume` after reviewing")
        self.telemetry = Telemetry(state_dir / "traces.jsonl")
        self.supervisor = Supervisor(self.state, self.layer, self.limits, self.clock, alerts_file=state_dir / "alerts.log")
        self.taxonomy = agents.Taxonomy.load(taxonomy_file or TAXONOMY_FILE)
        self.suggest_only = suggest_only
        self.worker_id = worker_id or uuid.uuid4().hex[:8]
        self.ticks_run = 0
        self.results: list[TickResult] = []

    def close(self) -> None:
        if hasattr(self, "telemetry"):
            self.telemetry.shutdown()
        self.state.close()
        if self._own_layer:
            self.layer.close()

    def tick(self) -> TickResult:
        tick = self.ticks_run
        self.ticks_run += 1
        day = day_id(self.clock.now())
        run_id = f"{day}-t{tick:03d}-{self.worker_id}"
        counts = agents.TickCounts()
        self.caller.tick = tick
        tracer = self.telemetry.tracer
        with tracer.start_as_current_span("gardener.tick") as span:
            span.set_attribute("gardener.tick", tick)
            span.set_attribute("gardener.run_id", run_id)
            span.set_attribute("gardener.clock", iso(self.clock.now()))
            span.set_attribute("gardener.caller", self.caller.name)
            k = self.state.kill_state()
            if k is not None:
                span.set_attribute("gardener.status", "killed")
                res = TickResult(tick, run_id, "killed", counts, k["reason"], k["detail"])
                self.results.append(res)
                return res
            self.state.start_run(run_id, tick, day)
            ctx = agents.Context(state=self.state, supervisor=self.supervisor, caller=self.caller, tracer=tracer, taxonomy=self.taxonomy,
                                 owner=f"{self.worker_id}", run_id=run_id, tick=tick, counts=counts, suggest_only=self.suggest_only,
                                 suggestions_file=self.state_dir / "suggestions.jsonl")
            status, reason, detail = "ok", None, None
            seen: dict[str, int] = {}
            try:
                seen = agents.watch(ctx)
                with tracer.start_as_current_span("gardener.classifier"):
                    for r in self.state.rows("pending_classify"):
                        agents.classify(ctx, r["path"])
                with tracer.start_as_current_span("gardener.linker"):
                    cat = agents.catalog(self.state)
                    for r in self.state.rows("pending_link"):
                        agents.link(ctx, r["path"], cat)
            except Tripped as t:
                status, reason, detail = "tripped", t.reason, t.detail
                span.add_event("gardener.stopped", {"reason": t.reason})
            except BaseException as e:
                # Never log a crashed tick as "ok" (review 2026-11-22 S6); the exception still propagates.
                status, reason, detail = "crashed", type(e).__name__, str(e)[:500]
                raise
            finally:
                self.state.finish_run(run_id, status, counts.for_db())
                self.layer.record("vault_gardener.tick", {"tick": tick, "status": status, **counts.for_db()}, run_id=day,
                                  agent="worker", occurred_at=iso(self.clock.now()))
                for key, val in counts.for_db().items():
                    span.set_attribute(f"gardener.{key}", val)
                span.set_attribute("gardener.status", status)
        res = TickResult(tick, run_id, status, counts, reason, detail, seen)
        self.results.append(res)
        return res

    def run(self, ticks: int | None = None, interval_s: float = TICK_SECONDS) -> list[TickResult]:
        """The loop. `ticks=None` runs until a trip or the kill switch."""
        out: list[TickResult] = []
        while ticks is None or len(out) < ticks:
            res = self.tick()
            out.append(res)
            if res.status != "ok":
                break
            if ticks is not None and len(out) >= ticks:
                break
            self.clock.sleep(interval_s)
        return out

    def summary(self) -> dict[str, Any]:
        return {"ticks": len(self.results), "statuses": [r.status for r in self.results], "trips": self.supervisor.trips}
