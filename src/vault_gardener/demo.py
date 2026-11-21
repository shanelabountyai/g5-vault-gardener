"""`gardener demo`: the whole story in one command, on temporary copies of the synthetic vault.

1. A 96-tick simulated day (AC1, AC5): bodies changed must be 0; daily report.
2. A forced cost spike (AC2) and a forced error burst (AC3): the supervisor trips and the job stays stopped.
3. Quality against the labeled sample.
4. Revert: every agent change undone, the copy vault byte-identical to the fixture again.
Everything runs on recorded fixtures with estimated tokens and a simulated clock; nothing leaves the machine.
"""

from __future__ import annotations

import filecmp
import tempfile
from pathlib import Path

from vault_gardener import report as report_mod
from vault_gardener.clock import SimClock
from vault_gardener.config import FIXTURE_VAULT, g0_db_path
from vault_gardener.layer import Layer
from vault_gardener.quality import render_markdown as quality_md
from vault_gardener.quality import run_quality
from vault_gardener.simulate import simulate
from vault_gardener.state import State


def _trees_equal(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b, ignore=[".gardener-copy"])
    stack = [cmp]
    while stack:
        c = stack.pop()
        if c.left_only or c.right_only or c.diff_files or c.funny_files:
            return False
        _, mismatch, errors = filecmp.cmpfiles(c.left, c.right, c.common_files, shallow=False)
        if mismatch or errors:
            return False
        stack.extend(c.subdirs.values())
    return True


def run_demo(out: Path | None = None) -> int:
    root = out or Path(tempfile.mkdtemp(prefix="gardener-demo-"))
    root.mkdir(parents=True, exist_ok=True)
    ok = True
    print(f"Vault Gardener demo — working in {root}\n(recorded fixtures, estimated tokens, simulated clock; no model is called)\n")

    print("1) 96 ticks x 15 min on a copy of the synthetic vault (time-compressed day, not a wall-clock run)")
    day = simulate(root / "day", ticks=96)
    s = day.summary()
    print(f"   ticks {s['ticks_run']} ({s['simulated_hours']:.0f} simulated hours) · bodies changed by agents {s['bodies_changed_by_agents']} · "
          f"files deleted {s['files_deleted']} · consistency problems {s['consistency_problems']} · trips {s['supervisor_trips']}")
    st, layer = State(root / "day" / "state.sqlite", day.vault, SimClock()), Layer(g0_db_path(root / "day"))
    rep = report_mod.daily_report(st, layer, day.day)
    st.close()
    layer.close()
    (root / "daily-report.md").write_text(report_mod.render_markdown(rep), encoding="utf-8")
    print(f"   daily report: notes processed {rep['notes_processed']}, links added {rep['links_added']}, errors {rep['errors']}, "
          f"cost ${rep['cost_usd']:.4f} (estimated) → {root / 'daily-report.md'}")
    ok &= s["bodies_changed_by_agents"] == 0 and s["files_deleted"] == 0 and s["consistency_problems"] == 0 and s["supervisor_trips"] == 0

    for kind in ("cost-spike", "error-burst"):
        print(f"\n2) forced {kind} from tick 10")
        r = simulate(root / kind, ticks=96, inject=(kind, 10))  # type: ignore[arg-type]
        rs = r.summary()
        trip = r.trips[0] if r.trips else {}
        print(f"   tripped: {bool(r.trips)} ({trip.get('reason')}) at tick {rs['stopped_at_tick']} · model calls in the 3 ticks after: "
              f"{rs['calls_after_trip']} · consistency problems {rs['consistency_problems']} · bodies changed {rs['bodies_changed_by_agents']}")
        print(f"   alert: {(root / kind / 'alerts.log').read_text().strip() if (root / kind / 'alerts.log').exists() else 'none'}")
        ok &= bool(r.trips) and rs["calls_after_trip"] == 0 and rs["consistency_problems"] == 0 and rs["bodies_changed_by_agents"] == 0

    print("\n3) quality against the hand-labeled sample (designed mistakes in the recorded responses)")
    q = run_quality(root / "quality")
    (root / "quality-report.md").write_text(quality_md(q), encoding="utf-8")
    print(f"   tag precision {q['tag_precision']} · tag recall {q['tag_recall']} · type accuracy {q['type_accuracy']} · "
          f"link precision {q['link_precision']} · G0 rubric passed {q['g0_rubric_passed']}/{q['labeled_notes']}")

    print("\n4) revert every agent change from the quality run")
    st = State(root / "quality" / "state.sqlite", root / "quality" / "vault", SimClock())
    st.set_killed("manual", "demo: stop before revert", None)
    rv = st.revert()
    st.close()
    same = _trees_equal(root / "quality" / "vault", FIXTURE_VAULT)
    print(f"   reverted {len(rv['reverted'])} changes, conflicts {len(rv['conflicts'])}; copy vault byte-identical to the fixture: {same}")
    ok &= same and not rv["conflicts"]

    print(f"\nDemo {'passed' if ok else 'FAILED'}.")
    return 0 if ok else 2
