"""The shared layer (G0·C), called in-process (D-7), modelled on G3·C's adapter.

Every capability call goes through `_run`, so each is counted and a `Refusal` becomes `Output(ok=False, error=…)`
exactly as G0's MCP server does. One seed is loaded through G0's own idempotent seed loader because the v1
contracts have no register tool (D-8): the rubric `g5_note_labels_v1`. The loader refuses ids not namespaced
`g5_`, so G0's own rubrics can never be overwritten from here.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from shared_layer.capabilities import evaluation, measurement, observability
from shared_layer.capabilities import health as health_cap
from shared_layer.contracts import contract_versions
from shared_layer.errors import Refusal, ToolError
from shared_layer.storage import Database, open_database

from vault_gardener.config import RUBRIC_FILE

RUBRIC_ID = "g5_note_labels_v1"


class LayerDegraded(RuntimeError):
    """health reported `degraded`, or the G5 rubric is missing; the worker must not start."""


class Layer:
    def __init__(self, db_path: str | None = None, rubric_file: Path | None = None) -> None:
        self.db: Database = open_database(db_path)
        self.calls: Counter[str] = Counter()
        self.rubric_file = rubric_file or RUBRIC_FILE
        try:
            self.load_seeds()
        except Exception:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def _run(self, module: Any, **kwargs: Any) -> Any:
        self.calls[module.TOOL] += 1
        output_cls = module.Output
        try:
            inp = module.Input(**kwargs)
        except ValidationError as e:
            return output_cls(ok=False, error=ToolError(code="INVALID_ARGUMENT", message=str(e).splitlines()[0]))
        try:
            return module.run(self.db, inp)
        except Refusal as r:
            return output_cls(ok=False, error=r.envelope)
        except sqlite3.Error as e:
            return output_cls(ok=False, error=ToolError(code="STORAGE_ERROR", message=f"SQLite refused the operation: {e}"))

    def load_seeds(self) -> None:
        doc = json.loads(self.rubric_file.read_text(encoding="utf-8"))
        ids = [r["id"] for r in doc["rubrics"]]
        if not ids or any(not i.startswith("g5_") for i in ids):
            raise LayerDegraded(f"this consumer may only seed rubrics namespaced g5_*, got {ids}")
        with self.db.conn:
            self.db._seed_rubrics(doc)  # G0's own idempotent loader (INSERT OR REPLACE by id)

    def health(self) -> health_cap.Output:
        self.calls[health_cap.TOOL] += 1
        return health_cap.run(self.db, health_cap.Input(), contracts=contract_versions())

    def require_healthy(self) -> health_cap.Output:
        h = self.health()
        if h.status != "ok":
            raise LayerDegraded(f"shared layer degraded: writable={h.db_writable} seeds={h.seeds} at {h.db_path}")
        if RUBRIC_ID not in h.rubrics:
            raise LayerDegraded(f"rubric {RUBRIC_ID} is not in the layer's store (have {h.rubrics})")
        return h

    def log_call(self, *, run_id: str, agent: str, step: str, model: str | None = None, input_tokens: int = 0, output_tokens: int = 0,
                 cost_usd: float = 0.0, status: str = "ok", duration_ms: int | None = None, note: str | None = None) -> observability.Output:
        return self._run(observability, run_id=run_id, agent=agent, step=step, model=model, input_tokens=input_tokens,
                         output_tokens=output_tokens, cost_usd=cost_usd, status=status, duration_ms=duration_ms, note=note)

    def run_total(self, run_id: str) -> observability.RunTotal:
        return observability.run_total(self.db, run_id)

    def record(self, event: str, fields: dict[str, Any], run_id: str, agent: str = "vault-gardener",
               occurred_at: str | None = None) -> measurement.Output:
        return self._run(measurement, event=event, fields=fields, run_id=run_id, agent=agent, occurred_at=occurred_at)

    def evaluate(self, item: dict[str, Any], *, rubric_id: str = RUBRIC_ID, run_id: str | None = None) -> evaluation.Output:
        return self._run(evaluation, rubric_id=rubric_id, item=item, judge="deterministic", run_id=run_id)

    def events(self, event: str, run_id: str | None = None) -> list[dict[str, Any]]:
        """Read back stored measurement events (read-only SELECT; the layer is never written outside a tool)."""
        sql = "SELECT event_id, fields, run_id, occurred_at FROM events WHERE event = ?"
        args: list[Any] = [event]
        if run_id is not None:
            sql += " AND run_id = ?"
            args.append(run_id)
        rows = self.db.conn.execute(sql + " ORDER BY occurred_at, stored_at", args).fetchall()
        return [{"event_id": r["event_id"], "fields": json.loads(r["fields"]), "run_id": r["run_id"], "occurred_at": r["occurred_at"]} for r in rows]

    @staticmethod
    def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
        """G0's price table; this repo has none of its own."""
        p_in, p_out = dict(evaluation.PRICES_PER_MTOK).get(model, (0.0, 0.0))
        return round(float(input_tokens * p_in / 1e6 + output_tokens * p_out / 1e6), 6)

    @staticmethod
    def known_model(model: str) -> bool:
        return model in evaluation.PRICES_PER_MTOK

    @staticmethod
    def run_cap_usd() -> float:
        return float(observability.cap_usd())
