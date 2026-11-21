"""`gardener` command line.

  gardener copy-fixture DEST                  copy the synthetic vault to DEST and mark it as a copy
  gardener run --vault V --state S [--ticks N] [--suggest-only] [--live]   the 15-minute loop (real clock)
  gardener simulate [--ticks 96] [--inject cost-spike@10|error-burst@10]   time-compressed day on a temp copy
  gardener report --state S [--day g5-YYYY-MM-DD]                          daily report
  gardener quality [--out docs/quality-report.md]                          labeled-sample quality
  gardener revert --state S --vault V (--run RUN_ID | --all)               undo agent changes
  gardener kill --state S --vault V [--reason TEXT] / resume / status      the kill switch
  gardener demo                                                            one-command walkthrough

Exit codes: 0 ok, 1 error, 2 supervisor tripped / safety problem found, 3 kill switch set.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal, cast

from vault_gardener import report as report_mod
from vault_gardener.clock import RealClock, SimClock, day_id
from vault_gardener.config import DEFAULT_DAILY_CAP_USD, DEFAULT_DAILY_TOKEN_BUDGET, REPO_DIR, TICK_SECONDS, Limits, g0_db_path
from vault_gardener.layer import Layer
from vault_gardener.llm import LiveCallRefused, make_caller
from vault_gardener.safety import ensure_copy_vault
from vault_gardener.simulate import copy_fixture, simulate
from vault_gardener.state import State
from vault_gardener.worker import KillSwitchSet, Worker


def _limits(a: argparse.Namespace) -> Limits:
    window = getattr(a, "error_window_min", None)
    return Limits.from_env(daily_cap_usd=getattr(a, "daily_cap_usd", None), daily_token_budget=getattr(a, "daily_token_budget", None),
                           error_burst=getattr(a, "error_burst", None), error_window_s=None if window is None else int(window * 60))


def _add_limits(p: argparse.ArgumentParser) -> None:
    p.add_argument("--daily-cap-usd", type=float, help=f"daily cost cap (default {DEFAULT_DAILY_CAP_USD}, provisional, D-4)")
    p.add_argument("--daily-token-budget", type=int, help=f"daily token budget (default {DEFAULT_DAILY_TOKEN_BUDGET}, provisional, D-4)")
    p.add_argument("--error-burst", type=int, help="errors within the window that trip the supervisor (default 5)")
    p.add_argument("--error-window-min", type=float, help="error-burst window in minutes (default 60)")


def _inject(spec: str | None) -> tuple[Literal["cost-spike", "error-burst"], int] | None:
    if not spec:
        return None
    kind, _, tick = spec.partition("@")
    if kind not in ("cost-spike", "error-burst"):
        raise SystemExit(f"--inject must be cost-spike@N or error-burst@N, got {spec!r}")
    return cast(Literal["cost-spike", "error-burst"], kind), int(tick or 0)


def _state(a: argparse.Namespace) -> State:
    return State(Path(a.state) / "state.sqlite", ensure_copy_vault(Path(a.vault)), RealClock())


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_copy_fixture(a: argparse.Namespace) -> int:
    dest = copy_fixture(Path(a.dest))
    print(f"copied the synthetic fixture vault to {dest} (marked as a copy)")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    try:
        caller = make_caller(a.live)
    except LiveCallRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    try:
        w = Worker(Path(a.vault), Path(a.state), clock=SimClock() if a.sim_clock else RealClock(), caller=caller, limits=_limits(a),
                   suggest_only=a.suggest_only)
    except KillSwitchSet as e:
        print(str(e), file=sys.stderr)
        return 3
    try:
        results = w.run(ticks=a.ticks, interval_s=a.interval)
    finally:
        w.close()
    for r in results:
        print(f"tick {r.tick} {r.status}: classified {r.counts.notes_classified}, linked {r.counts.notes_linked}, links +{r.counts.links_added}, "
              f"errors {r.counts.errors}, ${r.counts.cost_usd:.4f}" + (f" — {r.reason}: {r.detail}" if r.reason else ""))
    return 2 if results and results[-1].status == "tripped" else 0


def cmd_simulate(a: argparse.Namespace) -> int:
    state_dir = Path(a.state) if a.state else Path(tempfile.mkdtemp(prefix="gardener-sim-"))
    res = simulate(state_dir, ticks=a.ticks, inject=_inject(a.inject), limits=_limits(a), suggest_only=a.suggest_only)
    s = res.summary()
    st = State(state_dir / "state.sqlite", res.vault, SimClock())
    layer = Layer(g0_db_path(state_dir))
    try:
        rep = report_mod.daily_report(st, layer, res.day)
    finally:
        st.close()
        layer.close()
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(report_mod.render_markdown(rep, title=f"Vault Gardener — daily report ({res.ticks_run}-tick simulated day)"), encoding="utf-8")
    out = {"state_dir": str(state_dir), "simulation": s, "daily_report": {k: rep[k] for k in ("notes_processed", "links_added", "tags_added", "errors",
                                                                                            "tokens", "cost_usd", "tokens_estimated")}}
    _print(out)
    print("NOTE: simulated clock, recorded fixtures, estimated tokens. This is not a 24-hour wall-clock run (D-19).", file=sys.stderr)
    bad = s["bodies_changed_by_agents"] or s["files_deleted"] or s["consistency_problems"]
    if bad:
        return 2
    return 2 if (s["supervisor_trips"] and not a.inject) else 0


def cmd_report(a: argparse.Namespace) -> int:
    state_dir = Path(a.state)
    vault = Path(a.vault) if a.vault else state_dir / "vault"
    st = State(state_dir / "state.sqlite", vault, RealClock())
    layer = Layer(g0_db_path(state_dir))
    try:
        day = a.day or (st.conn.execute("SELECT day FROM runs ORDER BY started_at DESC LIMIT 1").fetchone() or [day_id(RealClock().now())])[0]
        rep = report_mod.daily_report(st, layer, day, record=False)
    finally:
        st.close()
        layer.close()
    md = report_mod.render_markdown(rep)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_quality(a: argparse.Namespace) -> int:
    from vault_gardener.quality import render_markdown, run_quality

    state_dir = Path(a.state) if a.state else Path(tempfile.mkdtemp(prefix="gardener-quality-"))
    rep = run_quality(state_dir)
    md = render_markdown(rep)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
    _print({k: rep[k] for k in ("labeled_notes", "tag_precision", "tag_recall", "type_accuracy", "link_precision", "links_written", "g0_rubric_passed")})
    print("NOTE: recorded fixtures with designed mistakes (D-24); not a model measurement.", file=sys.stderr)
    return 0


def cmd_revert(a: argparse.Namespace) -> int:
    if not a.all and not a.run:
        print("give --run RUN_ID or --all", file=sys.stderr)
        return 1
    st = _state(a)
    try:
        if st.kill_state() is None and not a.force:
            print("refused: set the kill switch first (`gardener kill`) so no worker writes during the revert, or pass --force", file=sys.stderr)
            return 1
        out = st.revert(None if a.all else a.run)
    finally:
        st.close()
    _print({"reverted": len(out["reverted"]), "conflicts": out["conflicts"]})
    return 2 if out["conflicts"] else 0


def cmd_kill(a: argparse.Namespace) -> int:
    st = _state(a)
    try:
        first = st.set_killed("manual", a.reason, None)
    finally:
        st.close()
    print("kill switch set" if first else "kill switch was already set")
    return 0


def cmd_resume(a: argparse.Namespace) -> int:
    st = _state(a)
    try:
        cleared = st.clear_killed()
    finally:
        st.close()
    print("kill switch cleared" if cleared else "kill switch was not set")
    return 0


def cmd_status(a: argparse.Namespace) -> int:
    st = _state(a)
    try:
        killed = st.kill_state()
        counts = {r[0]: r[1] for r in st.conn.execute("SELECT status, COUNT(*) FROM notes GROUP BY status").fetchall()}
        _print({"kill_switch": killed, "notes": counts, "consistency_problems": st.check_consistency()})
    finally:
        st.close()
    return 3 if killed else 0


def cmd_demo(a: argparse.Namespace) -> int:
    from vault_gardener.demo import run_demo

    return run_demo(Path(a.out) if a.out else None)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gardener", description="Vault Gardener (G5·C) — synthetic vault, recorded model by default.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("copy-fixture", help="copy the synthetic fixture vault and mark it as a copy")
    s.add_argument("dest")
    s.set_defaults(fn=cmd_copy_fixture)

    s = sub.add_parser("run", help="the 15-minute loop on a copy vault")
    s.add_argument("--vault", required=True)
    s.add_argument("--state", required=True)
    s.add_argument("--ticks", type=int, help="stop after N ticks (default: run until tripped or killed)")
    s.add_argument("--interval", type=float, default=TICK_SECONDS, help="seconds between ticks (default 900)")
    s.add_argument("--sim-clock", action="store_true", help="simulated clock: sleeping advances time instantly")
    s.add_argument("--suggest-only", action="store_true", help="Linker writes suggestions.jsonl instead of notes (D-5)")
    s.add_argument("--live", action="store_true", help="Claude Agent SDK calls; needs ANTHROPIC_API_KEY (not used in this build)")
    _add_limits(s)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("simulate", help="time-compressed day on a temporary copy")
    s.add_argument("--ticks", type=int, default=96)
    s.add_argument("--state", help="state dir (default: a new temp dir)")
    s.add_argument("--inject", help="cost-spike@N or error-burst@N")
    s.add_argument("--report", help="write the daily report markdown here")
    s.add_argument("--suggest-only", action="store_true")
    _add_limits(s)
    s.set_defaults(fn=cmd_simulate)

    s = sub.add_parser("report", help="daily report from a state dir")
    s.add_argument("--state", required=True)
    s.add_argument("--vault")
    s.add_argument("--day")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("quality", help="quality against the labeled sample")
    s.add_argument("--state")
    s.add_argument("--out", default=str(REPO_DIR / "docs" / "quality-report.md"))
    s.set_defaults(fn=cmd_quality)

    s = sub.add_parser("revert", help="undo agent changes")
    s.add_argument("--vault", required=True)
    s.add_argument("--state", required=True)
    s.add_argument("--run")
    s.add_argument("--all", action="store_true")
    s.add_argument("--force", action="store_true", help="revert without the kill switch set")
    s.set_defaults(fn=cmd_revert)

    for name, fn, hlp in (("kill", cmd_kill, "set the kill switch"), ("resume", cmd_resume, "clear the kill switch (owner)"),
                          ("status", cmd_status, "kill switch, note statuses, consistency")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--vault", required=True)
        s.add_argument("--state", required=True)
        if name == "kill":
            s.add_argument("--reason", default="manual stop")
        s.set_defaults(fn=fn)

    s = sub.add_parser("demo", help="one-command walkthrough")
    s.add_argument("--out", help="directory for the demo's state dirs and reports (default: a temp dir)")
    s.set_defaults(fn=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
