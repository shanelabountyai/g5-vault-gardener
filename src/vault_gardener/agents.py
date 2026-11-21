"""The three agents (PRD agent table, D-12, D-13, D-21, D-23).

| Agent      | Writes                                               |
|------------|------------------------------------------------------|
| Watcher    | the state table only                                 |
| Classifier | frontmatter `tags` (union) and `type` (if missing)   |
| Linker     | the managed Related block (or suggestions.jsonl)     |

Every note write goes through `State.write_note` under the note's lease. Model output is validated here and never
trusted: tags outside the taxonomy and unknown link targets are dropped and logged; a malformed response is an error.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opentelemetry.trace import Tracer

from vault_gardener import note
from vault_gardener.config import LEASE_SECONDS, MAX_ATTEMPTS, MAX_LINKS
from vault_gardener.llm import CLASSIFIER, LINKER, AgentSpec, CallResult, ModelCaller, ModelCallError
from vault_gardener.safety import SafetyViolation
from vault_gardener.state import State, read_text
from vault_gardener.supervisor import Supervisor


class MalformedOutput(ValueError):
    """The model's response does not fit the agent's output shape."""


@dataclass
class Taxonomy:
    tags: list[str]
    types: list[str]
    type_folder: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> Taxonomy:
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(tags=list(d["tags"]), types=list(d["types"]), type_folder=dict(d["type_folder"]))


@dataclass
class TickCounts:
    notes_seen: int = 0
    notes_classified: int = 0
    notes_linked: int = 0
    tags_added: int = 0
    links_added: int = 0
    errors: int = 0
    conflicts: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    skipped_locked: int = 0
    tags_rejected: list[str] = field(default_factory=list)
    links_rejected: list[str] = field(default_factory=list)

    def for_db(self) -> dict[str, Any]:
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.__dict__.items()
                if k not in ("skipped_locked", "tags_rejected", "links_rejected")}


@dataclass
class Context:
    state: State
    supervisor: Supervisor
    caller: ModelCaller
    tracer: Tracer
    taxonomy: Taxonomy
    owner: str
    run_id: str
    tick: int
    counts: TickCounts
    suggest_only: bool = False
    suggestions_file: Path | None = None
    lease_s: float = LEASE_SECONDS


def slug_of(path: str) -> str:
    return Path(path).stem


# -- Watcher ---------------------------------------------------------------------


def watch(ctx: Context) -> dict[str, int]:
    """Find notes new or changed since the last run; writes the state table only."""
    seen = {"new": 0, "changed": 0, "same": 0, "busy": 0, "gone": 0, "missing": 0}
    with ctx.tracer.start_as_current_span("gardener.watcher") as span:
        vault = ctx.state.vault
        paths = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*.md")
                       if not any(part.startswith(".") for part in p.relative_to(vault).parts))
        for rel in paths:
            seen[ctx.state.observe(rel)] += 1
        present = set(paths)
        for r in ctx.state.rows():
            if r["path"] not in present and r["status"] != "missing":
                ctx.state.mark_missing(r["path"])
                seen["missing"] += 1
        ctx.counts.notes_seen = len(paths)
        for k, v in seen.items():
            span.set_attribute(f"gardener.watcher.{k}", v)
    return seen


# -- shared call path --------------------------------------------------------------


def _call(ctx: Context, spec: AgentSpec, path: str, user_text: str) -> CallResult:
    """One model call: supervisor check, the call, G0 observability, counts and a span. Raises ModelCallError."""
    ctx.supervisor.check(ctx.run_id)
    with ctx.tracer.start_as_current_span(f"gardener.{spec.name}.call") as span:
        span.set_attribute("gardener.note", path)
        span.set_attribute("gen_ai.request.model", spec.model)
        span.set_attribute("gardener.tick", ctx.tick)
        result = ctx.caller.call(spec, user_text, f"{spec.name}:{path}")
        cost = ctx.supervisor.log_call(tick=ctx.tick, agent=spec.name, path=path, result=result)
        ctx.counts.model_calls += 1
        ctx.counts.input_tokens += result.input_tokens
        ctx.counts.output_tokens += result.output_tokens
        ctx.counts.cost_usd += cost
        span.set_attribute("gen_ai.usage.input_tokens", result.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", result.output_tokens)
        span.set_attribute("gardener.cost_usd", cost)
        span.set_attribute("gardener.tokens_estimated", result.estimated)
        if "recorded_key" in result.extra:
            span.set_attribute("gardener.recorded_key", str(result.extra["recorded_key"]))
        ctx.supervisor.after_call(run_id=ctx.run_id, agent=spec.name, path=path, result=result, cost=cost)
        return result


def _fail(ctx: Context, agent: str, path: str, kind: str, message: str, model: str) -> str:
    """Count an error; park the note after MAX_ATTEMPTS (D-21). May raise Tripped (error burst)."""
    row = ctx.state.row(path)
    attempts = (row["attempts"] if row else 0) + 1
    ctx.state.set_fields(path, attempts=attempts, **({"status": "error"} if attempts >= MAX_ATTEMPTS else {}))
    ctx.counts.errors += 1
    ctx.supervisor.record_error(run_id=ctx.run_id, tick=ctx.tick, agent=agent, path=path, kind=kind, message=message, model=model)
    return "error"


def _write(ctx: Context, agent: str, path: str, based_on: str, new_text: str, **row_updates: Any) -> str:
    try:
        res = ctx.state.write_note(path=path, owner=ctx.owner, run_id=ctx.run_id, tick=ctx.tick, agent=agent, based_on=based_on,
                                   new_text=new_text, **row_updates)
    except SafetyViolation as e:
        ctx.counts.errors += 1
        ctx.state.add_error(ctx.run_id, ctx.tick, agent, path, "safety", str(e))
        ctx.supervisor.trip("safety", str(e), ctx.run_id)
        raise  # pragma: no cover - trip() always raises
    if res == "conflict":
        ctx.counts.conflicts += 1
    return res


# -- Classifier ----------------------------------------------------------------------


def classifier_message(tax: Taxonomy, path: str, text: str) -> str:
    return json.dumps({"taxonomy": {"tags": tax.tags, "types": tax.types, "type_folder": tax.type_folder},
                       "note": {"path": path, "text": text}}, ensure_ascii=False)


def parse_classifier(raw: str | dict[str, Any], tax: Taxonomy) -> tuple[list[str], str, str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise MalformedOutput(f"not JSON: {str(raw)[:80]!r}") from e
    if not isinstance(raw, dict) or set(raw) != {"tags", "type", "folder"}:
        raise MalformedOutput(f"expected keys tags/type/folder, got {sorted(raw) if isinstance(raw, dict) else type(raw).__name__}")
    tags, ntype, folder = raw["tags"], raw["type"], raw["folder"]
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise MalformedOutput("tags must be a list of strings")
    if not isinstance(ntype, str) or ntype not in tax.types:
        raise MalformedOutput(f"type {ntype!r} is not one of {tax.types}")
    if not isinstance(folder, str):
        raise MalformedOutput("folder must be a string")
    return tags, ntype, folder


def classify(ctx: Context, path: str) -> str:
    with ctx.state.lock(path, ctx.owner, ctx.lease_s) as got:
        if not got:
            ctx.counts.skipped_locked += 1
            return "locked"
        row = ctx.state.row(path)
        text = read_text(ctx.state.vault / path)
        if row is None or row["status"] != "pending_classify" or text is None:
            return "skip"
        if note.sha256(text) != row["content_hash"]:
            return "stale"  # changed since the Watcher saw it; next tick
        try:
            result = _call(ctx, CLASSIFIER, path, classifier_message(ctx.taxonomy, path, text))
            tags, ntype, folder = parse_classifier(result.raw, ctx.taxonomy)
        except (ModelCallError, MalformedOutput) as e:
            return _fail(ctx, "classifier", path, type(e).__name__, str(e), CLASSIFIER.model)
        accepted = [t for t in dict.fromkeys(tags) if t in ctx.taxonomy.tags]
        rejected = [t for t in tags if t not in ctx.taxonomy.tags]
        parsed = note.parse(text)
        existing = parsed.tags()
        add = [t for t in accepted if t not in existing]
        new_type = ntype if parsed.type() is None else None
        new_text = note.set_frontmatter(text, tags=existing + add if add else None, type_=new_type)
        res = _write(ctx, "classifier", path, text, new_text, status="pending_link", attempts=0, classified_at=ctx.state.now_iso(),
                     suggested_folder=folder, suggested_type=ntype, tags_rejected=json.dumps(rejected))
        if res in ("applied", "noop"):
            ctx.counts.notes_classified += 1
            ctx.counts.tags_added += len(add) if res == "applied" else 0
            ctx.counts.tags_rejected.extend(rejected)
        return res


# -- Linker ------------------------------------------------------------------------------


def catalog(state: State) -> dict[str, dict[str, Any]]:
    """id → {path, title, tags} for every present note (built once per tick, after the Classifier)."""
    out: dict[str, dict[str, Any]] = {}
    for r in state.rows():
        if r["status"] == "missing":
            continue
        text = read_text(state.vault / r["path"])
        if text is None:
            continue
        n = note.parse(text)
        out.setdefault(slug_of(r["path"]), {"path": r["path"], "title": n.title(), "tags": n.tags()})
    return out


def linker_message(path: str, text: str, cat: dict[str, dict[str, Any]]) -> str:
    me = slug_of(path)
    candidates = [{"id": k, "title": v["title"], "tags": v["tags"]} for k, v in cat.items() if k != me]
    return json.dumps({"note": {"id": me, "text": text}, "candidates": candidates, "max_links": MAX_LINKS}, ensure_ascii=False)


def parse_linker(raw: str | dict[str, Any]) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as e:
            raise MalformedOutput(f"not JSON: {str(raw)[:80]!r}") from e
    if not isinstance(raw, dict) or set(raw) != {"related"} or not isinstance(raw["related"], list) \
            or not all(isinstance(s, str) for s in raw["related"]):
        raise MalformedOutput("expected {\"related\": [ids]}")
    return list(raw["related"])


def link(ctx: Context, path: str, cat: dict[str, dict[str, Any]]) -> str:
    with ctx.state.lock(path, ctx.owner, ctx.lease_s) as got:
        if not got:
            ctx.counts.skipped_locked += 1
            return "locked"
        row = ctx.state.row(path)
        text = read_text(ctx.state.vault / path)
        if row is None or row["status"] != "pending_link" or text is None:
            return "skip"
        if note.sha256(text) != row["content_hash"]:
            return "stale"
        try:
            result = _call(ctx, LINKER, path, linker_message(path, text, cat))
            related = parse_linker(result.raw)
        except (ModelCallError, MalformedOutput) as e:
            return _fail(ctx, "linker", path, type(e).__name__, str(e), LINKER.model)
        me = slug_of(path)
        accepted = [s for s in dict.fromkeys(related) if s in cat and s != me][:MAX_LINKS]
        rejected = [s for s in related if s not in cat or s == me]
        ctx.counts.links_rejected.extend(rejected)
        parsed = note.parse(text)
        existing = parsed.related
        in_body = parsed.body_links()  # the owner's own links (or a block the owner typed below) are never repeated
        if ctx.suggest_only:
            if ctx.suggestions_file is not None:
                with open(ctx.suggestions_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"at": ctx.state.now_iso(), "run_id": ctx.run_id, "note": path, "related": accepted,
                                        "rejected": rejected}) + "\n")
            ctx.state.set_fields(path, status="done", attempts=0, linked_at=ctx.state.now_iso(), links_rejected=json.dumps(rejected))
            ctx.counts.notes_linked += 1
            return "suggested"
        merged = list(existing) + [s for s in accepted if s not in existing and s not in in_body]
        new_text = note.set_related(text, merged) if merged else text
        res = _write(ctx, "linker", path, text, new_text, status="done", attempts=0, linked_at=ctx.state.now_iso(),
                     links_rejected=json.dumps(rejected))
        if res in ("applied", "noop"):
            ctx.counts.notes_linked += 1
            ctx.counts.links_added += (len(merged) - len(existing)) if res == "applied" else 0
        return res
