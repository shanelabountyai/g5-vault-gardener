"""OpenTelemetry traces, exported locally to a JSONL file (D-18). No collector, no network.

Each worker gets a private `TracerProvider` (never the global one) so tests and concurrent workers stay apart.
Span timestamps are wall-clock (OTel's own); the simulated clock time is an attribute (`gardener.clock`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Tracer


def _one_line(span: ReadableSpan) -> str:
    return json.dumps(json.loads(span.to_json()), separators=(",", ":")) + "\n"


class Telemetry:
    def __init__(self, trace_file: Path | None, service: str = "vault-gardener") -> None:
        self.trace_file = trace_file
        self._fh: IO[str] | None = None
        self.provider = TracerProvider(resource=Resource.create({"service.name": service}))
        if trace_file is not None:
            trace_file.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(trace_file, "a", encoding="utf-8")  # noqa: SIM115 - closed in shutdown()
            self.provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=self._fh, formatter=_one_line)))
        self.tracer: Tracer = self.provider.get_tracer("vault_gardener")

    def shutdown(self) -> None:
        self.provider.shutdown()
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def read_spans(trace_file: Path) -> list[dict[str, Any]]:
    if not trace_file.exists():
        return []
    return [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines() if line.strip()]
