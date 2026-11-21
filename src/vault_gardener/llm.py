"""Agent specs and model callers (D-9, D-10).

- `RecordedCaller` answers from `fixtures/recorded.json`, keyed `<agent>:<path>`. The file is HAND-WRITTEN in each
  agent's output shape; it is not a recording of a live model. Tokens are estimated as ceil(chars / 4) (D-9).
- `AgentSdkCaller` runs one agent turn in a Claude Agent SDK session (`claude_agent_sdk.query`): its own system
  prompt, no tools, structured output, a budget cap. Implemented behind the same interface, **never run in this
  build**; it refuses to construct without `ANTHROPIC_API_KEY`.
- `FaultInjectingCaller` wraps any caller to force a cost spike or an error burst from a given tick (AC2, AC3).

Prompts carry no shared-layer rule: cost caps, logging and evaluation live in G0 and in the supervisor.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from vault_gardener.config import CLASSIFIER_MODEL, LINKER_MODEL, RECORDED_FILE


class ModelCallError(RuntimeError):
    """The caller could not produce a response for this agent turn."""


class NoRecording(ModelCallError):
    """The recorded file has no response for this key."""


class LiveCallRefused(RuntimeError):
    """A live model call was asked for without a key (D-9)."""


@dataclass(frozen=True)
class AgentSpec:
    name: Literal["classifier", "linker"]
    model: str
    system: str
    schema: dict[str, Any]
    max_turns: int = 1


CLASSIFIER = AgentSpec(
    name="classifier",
    model=CLASSIFIER_MODEL,
    system=(
        "You tag one note from a personal notes vault. Choose tags only from the taxonomy given in the message, "
        "exactly one type from the listed types, and the folder that type maps to. Return JSON only."
    ),
    schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["tags", "type", "folder"],
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}, "type": {"type": "string"}, "folder": {"type": "string"}},
    },
)

LINKER = AgentSpec(
    name="linker",
    model=LINKER_MODEL,
    system=(
        "You connect one note to related notes in the same vault. Pick at most five notes from the candidate list "
        "given in the message that a reader of this note would also want; use their ids exactly. Return JSON only."
    ),
    schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["related"],
        "properties": {"related": {"type": "array", "items": {"type": "string"}}},
    },
)


@dataclass
class CallResult:
    agent: str
    model: str
    raw: str | dict[str, Any]  # validated by the agent, never trusted here
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = True  # D-9: recorded responses have no usage block
    duration_ms: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


class ModelCaller(Protocol):
    name: str
    live: bool
    calls: Counter[str]
    tick: int

    def call(self, spec: AgentSpec, user_text: str, key: str) -> CallResult: ...


class RecordedCaller:
    name = "recorded"
    live = False

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or RECORDED_FILE
        self.responses: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))["responses"]
        self.calls: Counter[str] = Counter()
        self.tick = 0

    def call(self, spec: AgentSpec, user_text: str, key: str) -> CallResult:
        if key not in self.responses:
            raise NoRecording(f"no recording for {key!r}; live mode needs a key (D-9)")
        self.calls[spec.name] += 1
        raw = self.responses[key]
        out_text = raw if isinstance(raw, str) else json.dumps(raw)
        return CallResult(agent=spec.name, model=spec.model, raw=raw, input_tokens=estimate_tokens(spec.system + user_text),
                          output_tokens=estimate_tokens(out_text), estimated=True, extra={"recorded_key": key})


class FaultInjectingCaller:
    """Forces a failure mode from `from_tick` on (the worker sets `tick` before each tick)."""

    SPIKE_INPUT_TOKENS = 2_000_000  # a runaway prompt: one call alone is far over any sane daily budget

    def __init__(self, inner: ModelCaller, kind: Literal["cost-spike", "error-burst"], from_tick: int) -> None:
        self.inner, self.kind, self.from_tick = inner, kind, from_tick
        self.name = f"{inner.name}+{kind}@{from_tick}"
        self.live = inner.live
        self.calls = inner.calls
        self.injected = 0

    @property
    def tick(self) -> int:
        return self.inner.tick

    @tick.setter
    def tick(self, value: int) -> None:
        self.inner.tick = value

    def call(self, spec: AgentSpec, user_text: str, key: str) -> CallResult:
        if self.tick < self.from_tick:
            return self.inner.call(spec, user_text, key)
        self.injected += 1
        if self.kind == "error-burst":
            raise ModelCallError(f"injected error-burst failure (tick {self.tick})")
        r = self.inner.call(spec, user_text, key)
        r.input_tokens += self.SPIKE_INPUT_TOKENS
        r.extra["injected"] = "cost-spike"
        return r


class AgentSdkCaller:
    name = "claude-agent-sdk"
    live = True

    def __init__(self, max_budget_usd: float = 1.0) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LiveCallRefused("ANTHROPIC_API_KEY is not set; this build runs on the recorded path only (D-9).")
        self.max_budget_usd = max_budget_usd
        self.calls: Counter[str] = Counter()
        self.tick = 0

    def call(self, spec: AgentSpec, user_text: str, key: str) -> CallResult:  # pragma: no cover - never run here
        import anyio

        return anyio.run(self._call, spec, user_text)

    async def _call(self, spec: AgentSpec, user_text: str) -> CallResult:  # pragma: no cover - never run here
        from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

        options = ClaudeAgentOptions(
            model=spec.model,
            system_prompt=spec.system,
            tools=[],
            allowed_tools=[],
            permission_mode="dontAsk",
            setting_sources=[],
            max_turns=spec.max_turns,
            output_format={"type": "json_schema", "schema": spec.schema},
            max_budget_usd=self.max_budget_usd,
        )
        started = time.monotonic()
        text_parts: list[str] = []
        result: Any = None
        async for message in query(prompt=user_text, options=options):
            if isinstance(message, AssistantMessage):
                text_parts.extend(b.text for b in message.content if isinstance(b, TextBlock))
            elif isinstance(message, ResultMessage):
                result = message
        if result is None or result.is_error:
            raise ModelCallError(f"{spec.name}: the SDK returned no usable result")
        self.calls[spec.name] += 1
        usage = result.usage or {}
        raw: str | dict[str, Any] = result.structured_output if isinstance(result.structured_output, dict) else (
            text_parts[-1] if text_parts else (result.result or ""))
        return CallResult(agent=spec.name, model=spec.model, raw=raw,
                          input_tokens=int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0))
                          + int(usage.get("cache_creation_input_tokens", 0)),
                          output_tokens=int(usage.get("output_tokens", 0)), estimated=False,
                          duration_ms=int((time.monotonic() - started) * 1000), extra={"sdk_cost_usd": result.total_cost_usd})


def make_caller(live: bool, recorded: Path | None = None) -> ModelCaller:
    if live:
        return AgentSdkCaller()
    return RecordedCaller(recorded)
