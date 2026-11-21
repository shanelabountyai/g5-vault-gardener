"""Daily report (AC5, D-16): notes processed, links added, errors, cost — from the state table and G0.

Counts come from G5's `runs` and `errors` tables; cost and tokens from G0 observability's run total for the day;
the per-tick G0 measurement events are summed as a cross-check. On the recorded path tokens are estimated (D-9).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from vault_gardener.layer import Layer
from vault_gardener.state import State


def daily_report(state: State, layer: Layer, day: str, *, record: bool = True, estimated: bool = True) -> dict[str, Any]:
    runs = state.runs_for_day(day)
    errs = state.errors_for_day(day)
    g0 = layer.run_total(day)
    tick_events = layer.events("vault_gardener.tick", run_id=day)
    trips = layer.events("vault_gardener.supervisor_tripped", run_id=day)
    distinct = state.conn.execute(
        "SELECT COUNT(*) FROM notes WHERE substr(classified_at,1,10)=? OR substr(linked_at,1,10)=?", (day[3:], day[3:])).fetchone()[0]
    inbox_suggestions = [
        {"path": r["path"], "suggested_folder": r["suggested_folder"], "suggested_type": r["suggested_type"]}
        for r in state.rows() if r["path"].startswith("inbox/") and r["suggested_folder"]
    ]
    rejected_tags: list[str] = []
    rejected_links: list[str] = []
    for r in state.rows():
        rejected_tags += json.loads(r["tags_rejected"])
        rejected_links += json.loads(r["links_rejected"])
    rep: dict[str, Any] = {
        "day": day,
        "ticks": len(runs),
        "tick_statuses": dict(Counter(r["status"] for r in runs)),
        "notes_processed": int(distinct),
        "classifier_completions": sum(r["notes_classified"] for r in runs),
        "linker_completions": sum(r["notes_linked"] for r in runs),
        "tags_added": sum(r["tags_added"] for r in runs),
        "links_added": sum(r["links_added"] for r in runs),
        "errors": len(errs),
        "errors_by_kind": dict(Counter(e["kind"] for e in errs)),
        "conflicts_skipped": sum(r["conflicts"] for r in runs),
        "model_calls": sum(r["model_calls"] for r in runs),
        "tokens": g0.input_tokens + g0.output_tokens,
        "cost_usd": round(g0.cost_usd, 6),
        "tokens_estimated": estimated,
        "g0_calls_logged": g0.calls,
        "supervisor_trips": [e["fields"] for e in trips],
        "rejected_tags": rejected_tags,
        "rejected_links": rejected_links,
        "notes_parked_error": [r["path"] for r in state.rows("error")],
        "inbox_folder_suggestions": inbox_suggestions,
        "crosscheck": {
            "g0_tick_events": len(tick_events),
            "links_added_from_g0_events": sum(int(e["fields"].get("links_added", 0)) for e in tick_events),
            "errors_from_g0_events": sum(int(e["fields"].get("errors", 0)) for e in tick_events),
        },
    }
    if record:
        layer.record("vault_gardener.daily_report", {k: rep[k] for k in ("ticks", "notes_processed", "links_added", "tags_added", "errors", "tokens",
                                                                          "cost_usd")}, run_id=day, agent="report")
    return rep


def render_markdown(rep: dict[str, Any], title: str = "Vault Gardener — daily report") -> str:
    est = " (estimated: recorded fixtures, tokens = characters / 4; not a model's usage)" if rep["tokens_estimated"] else ""
    lines = [
        f"# {title}",
        "",
        f"Day `{rep['day']}` · {rep['ticks']} ticks · statuses {rep['tick_statuses']}",
        "",
        "| Figure | Value |",
        "|---|---|",
        f"| Notes processed (distinct notes classified or linked) | {rep['notes_processed']} |",
        f"| Classifier / Linker completions | {rep['classifier_completions']} / {rep['linker_completions']} |",
        f"| Tags added | {rep['tags_added']} |",
        f"| Links added | {rep['links_added']} |",
        f"| Errors | {rep['errors']} {rep['errors_by_kind'] or ''} |",
        f"| Write conflicts skipped | {rep['conflicts_skipped']} |",
        f"| Model calls | {rep['model_calls']} |",
        f"| Tokens{est} | {rep['tokens']:,} |",
        f"| Cost (USD){est} | ${rep['cost_usd']:.4f} |",
        f"| Supervisor trips | {len(rep['supervisor_trips'])} {[t.get('reason') for t in rep['supervisor_trips']] or ''} |",
        "",
        f"Rejected tags (outside taxonomy): {rep['rejected_tags'] or 'none'} · rejected links (unknown target): {rep['rejected_links'] or 'none'}",
        "",
        f"Notes parked after {3} failed attempts: {rep['notes_parked_error'] or 'none'}",
        "",
        "Inbox folder suggestions (recorded, never moved — D-13):",
        "",
    ]
    lines += [f"- `{s['path']}` → `{s['suggested_folder']}/` ({s['suggested_type']})" for s in rep["inbox_folder_suggestions"]] or ["- none"]
    c = rep["crosscheck"]
    lines += ["", f"Cross-check with G0 measurement events: {c['g0_tick_events']} tick events, links added {c['links_added_from_g0_events']}, "
                  f"errors {c['errors_from_g0_events']}; G0 observability logged {rep['g0_calls_logged']} entries for the day.", ""]
    return "\n".join(lines)
