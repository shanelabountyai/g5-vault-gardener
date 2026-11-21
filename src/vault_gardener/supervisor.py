"""Supervisor (D-15, D-16): daily cost and token budget, error-burst limit, safety trips, kill switch.

Every model call goes `check()` → call → `record_call()`; every agent error goes through `record_error()`.
Costs are logged to G0 observability under the day's run id, and the day's spend is read back from G0's
`run_total`, so the cost ledger lives in one place. A trip sets the kill switch in the state table, writes an
alert line (local file, no external send), records a G0 measurement event, and raises `Tripped` so the worker
unwinds through its `finally` blocks (leases released, run row closed).
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from opentelemetry import trace

from vault_gardener.clock import Clock, day_id, iso
from vault_gardener.config import Limits
from vault_gardener.layer import Layer
from vault_gardener.llm import CallResult
from vault_gardener.state import State


class Tripped(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"supervisor tripped: {reason}: {detail}")
        self.reason, self.detail = reason, detail


class Supervisor:
    def __init__(self, state: State, layer: Layer, limits: Limits, clock: Clock, alerts_file: Path | None = None) -> None:
        self.state, self.layer, self.limits, self.clock = state, layer, limits, clock
        self.alerts_file = alerts_file
        self.trips: list[dict[str, Any]] = []

    def day(self) -> str:
        return day_id(self.clock.now())

    def spend(self) -> tuple[float, int]:
        t = self.layer.run_total(self.day())
        return t.cost_usd, t.input_tokens + t.output_tokens

    def check(self, run_id: str | None = None) -> None:
        """Before a model call: stop if the switch is set or today's budget is already used up."""
        k = self.state.kill_state()
        if k is not None:
            raise Tripped(k["reason"], k["detail"])
        cost, tokens = self.spend()
        if cost >= self.limits.daily_cap_usd:
            self.trip("cost", f"day {self.day()} spend ${cost:.4f} reached the ${self.limits.daily_cap_usd:.2f} cap", run_id)
        if tokens >= self.limits.daily_token_budget:
            self.trip("tokens", f"day {self.day()} used {tokens} tokens, budget {self.limits.daily_token_budget}", run_id)

    def log_call(self, *, tick: int, agent: str, path: str, result: CallResult) -> float:
        """Log one model call to G0 observability under the day's run id; return its cost (G0 prices)."""
        cost = self.layer.cost_usd(result.model, result.input_tokens, result.output_tokens)
        note = f"{path}; tokens {'estimated' if result.estimated else 'measured'}"
        if "injected" in result.extra:
            note += f"; injected {result.extra['injected']}"
        out = self.layer.log_call(run_id=self.day(), agent=agent, step=f"t{tick:03d}.{agent}", model=result.model,
                                  input_tokens=result.input_tokens, output_tokens=result.output_tokens, cost_usd=cost,
                                  duration_ms=result.duration_ms, note=note)
        self._g0_over_cap = bool(out.ok and out.over_cap)
        self._g0_cap = float(out.cap_usd)
        return cost

    def after_call(self, *, run_id: str, agent: str, path: str, result: CallResult, cost: float) -> None:
        """Trip if the call just logged crossed a limit."""
        if getattr(self, "_g0_over_cap", False):
            self.trip("g0_run_cap", f"G0 reports run {self.day()} over its ${self._g0_cap:.2f} cap", run_id)
        spent, tokens = self.spend()
        if spent > self.limits.daily_cap_usd:
            self.trip("cost", f"day {self.day()} spend ${spent:.4f} passed the ${self.limits.daily_cap_usd:.2f} cap "
                              f"(last call {agent} on {path}: {result.input_tokens}+{result.output_tokens} tokens, ${cost:.4f})", run_id)
        if tokens > self.limits.daily_token_budget:
            self.trip("tokens", f"day {self.day()} used {tokens} tokens, budget {self.limits.daily_token_budget}", run_id)

    def record_error(self, *, run_id: str, tick: int, agent: str, path: str | None, kind: str, message: str, model: str | None = None) -> None:
        self.state.add_error(run_id, tick, agent, path, kind, message)
        self.layer.log_call(run_id=self.day(), agent=agent, step=f"t{tick:03d}.{agent}", model=model, status="error",
                            note=f"{path}: {kind}: {message[:200]}")
        since = (self.clock.now() - timedelta(seconds=self.limits.error_window_s)).timestamp()
        n = self.state.errors_since(since)
        if n >= self.limits.error_burst:
            self.trip("error_burst", f"{n} errors in the last {self.limits.error_window_s // 60} min (limit {self.limits.error_burst}); "
                                     f"last: {agent} on {path}: {kind}", run_id)

    def trip(self, reason: str, detail: str, run_id: str | None) -> None:
        first = self.state.set_killed(reason, detail, run_id)
        if first:
            entry = {"at": iso(self.clock.now()), "reason": reason, "detail": detail, "run_id": run_id}
            self.trips.append(entry)
            if self.alerts_file is not None:
                self.alerts_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.alerts_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"alert": "vault-gardener stopped", **entry}) + "\n")
            self.layer.record("vault_gardener.supervisor_tripped", {"reason": reason, "detail": detail}, run_id=self.day(),
                              agent="supervisor", occurred_at=iso(self.clock.now()))
            span = trace.get_current_span()
            span.add_event("supervisor.trip", {"reason": reason, "detail": detail})
        k = self.state.kill_state() or {"reason": reason, "detail": detail}
        raise Tripped(k["reason"], k["detail"])
