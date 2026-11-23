"""AC4: two agents targeting the same note never produce a conflicting write (D-14).

Layers tested separately and together: the lease (row lock), compare-and-swap on the file, two whole workers racing
on one state table in threads, and two worker processes. "No conflicting write" is checked as: every applied change
to a note starts from the previous change's result (no lost update), the state table is consistent, and no note ends
up with two managed blocks or duplicate tags.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from vault_gardener import agents, note
from vault_gardener.clock import SimClock
from vault_gardener.state import State

P = "reference/sqlite-wal-notes.md"


def _ctx(w, owner: str) -> agents.Context:  # type: ignore[no-untyped-def]
    return agents.Context(state=w.state, supervisor=w.supervisor, caller=w.caller, tracer=w.telemetry.tracer, taxonomy=w.taxonomy,
                          owner=owner, run_id=f"r-{owner}", tick=0, counts=agents.TickCounts())


def test_ac4_lease_locks_out_the_second_agent(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    agents.watch(_ctx(w, "x"))
    before = (vault / P).read_text()
    assert w.state.try_lock(P, "linker-A", 120)
    assert agents.classify(_ctx(w, "classifier-B"), P) == "locked"
    assert (vault / P).read_text() == before
    w.state.unlock(P, "linker-A")
    assert agents.classify(_ctx(w, "classifier-B"), P) == "applied"


def test_ac4_stale_read_cannot_overwrite_a_newer_write(tmp_path: Path, vault: Path) -> None:
    """Both agents read version 0; the first writes; the second's write (based on version 0) is refused."""
    st = State(tmp_path / "s.sqlite", vault, SimClock())
    st.observe(P)
    v0 = (vault / P).read_text()
    with st.lock(P, "classifier", 120):
        assert st.write_note(path=P, owner="classifier", run_id="r", tick=0, agent="classifier", based_on=v0,
                             new_text=note.set_frontmatter(v0, tags=["topic/programming"])) == "applied"
    with st.lock(P, "linker", 120):
        assert st.write_note(path=P, owner="linker", run_id="r", tick=0, agent="linker", based_on=v0,
                             new_text=note.set_related(v0, ["regex-cheatsheet"])) == "conflict"
    final = note.parse((vault / P).read_text())
    assert final.tags() == ["topic/programming"] and final.related == ()
    assert st.change_chain_breaks() == []


def test_ac4_two_threads_hammering_one_note(tmp_path: Path, vault: Path) -> None:
    """A tagging thread and a linking thread, each with its own connection, 150 writes each on the same note."""
    db = tmp_path / "s.sqlite"
    State(db, vault, SimClock()).observe(P)
    n = 60
    stats = {"A": {"applied": 0, "locked": 0, "conflict": 0}, "B": {"applied": 0, "locked": 0, "conflict": 0}}

    def worker(name: str) -> None:
        st = State(db, vault, SimClock())
        i = 0
        while i < n:
            with st.lock(P, name, 120) as got:
                if not got:
                    stats[name]["locked"] += 1
                    time.sleep(0.0005)
                    continue
                text = (vault / P).read_text()
                parsed = note.parse(text)
                new = (note.set_frontmatter(text, tags=parsed.tags() + [f"t{i}"]) if name == "A"
                       else note.set_related(text, list(parsed.related) + [f"n{i}"]))
                res = st.write_note(path=P, owner=name, run_id=name, tick=i, agent=name, based_on=text, new_text=new)
                stats[name][res] += 1
                i += 1
        st.close()

    threads = [threading.Thread(target=worker, args=(x,)) for x in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    st = State(db, vault, SimClock())
    final = note.parse((vault / P).read_text())
    assert final.tags() == [f"t{i}" for i in range(n)], "no tag write was lost"
    assert final.related == tuple(f"n{i}" for i in range(n)), "no link write was lost"
    assert stats["A"]["applied"] == n and stats["B"]["applied"] == n
    assert stats["A"]["conflict"] == stats["B"]["conflict"] == 0
    assert st.change_chain_breaks() == [] and st.lost_updates() == []
    assert st.check_consistency() == []
    assert final.body == note.parse((Path(__file__).resolve().parents[1] / "fixtures" / "vault" / P).read_text()).body


def _check_vault(vault: Path, st: State, owner_edited: tuple[str, ...] = ()) -> None:
    assert st.lost_updates() == []
    assert all(b.split(":")[0] in owner_edited for b in st.change_chain_breaks()), st.change_chain_breaks()
    assert st.check_consistency() == []
    for f in vault.rglob("*.md"):
        t = f.read_text()
        assert t.count(note.RELATED_START) <= 1, f
        tags = note.parse(t).tags()
        assert len(tags) == len(set(tags)), f


def test_ac4_two_workers_race_on_one_state_table(vault: Path, tmp_path: Path) -> None:
    """Two whole workers (Watcher → Classifier → Linker), each built in its own thread, tick in lock-step on one
    state table and one vault for three rounds, with owner edits before round 2."""
    from tests.conftest import BIG
    from vault_gardener.worker import Worker

    state_dir = tmp_path / "state"
    Worker(vault, state_dir, clock=SimClock(), limits=BIG).close()  # create schemas once
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    classified: list[int] = []

    def run(worker_id: str) -> None:
        try:
            w = Worker(vault, state_dir, clock=SimClock(), limits=BIG, worker_id=worker_id)
            for round_ in range(3):
                barrier.wait()
                if round_ == 1 and worker_id == "w1":
                    for p in ("reference/vlan-notes.md", "logs/moon-phase-log.md", P):
                        (vault / p).write_text((vault / p).read_text() + f"owner edit {round_}\n")
                barrier.wait()
                w.tick()
                w.clock.sleep(900)
            classified.append(sum(r.counts.notes_classified for r in w.results))
            w.close()
        except BaseException as e:  # pragma: no cover - surfaced below
            errors.append(e)
            barrier.abort()

    ts = [threading.Thread(target=run, args=(x,)) for x in ("w1", "w2")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    st = State(state_dir / "state.sqlite", vault, SimClock())
    _check_vault(vault, st, owner_edited=("reference/vlan-notes.md", "logs/moon-phase-log.md", P))
    per_path = st.conn.execute("SELECT path, COUNT(*) c FROM changes WHERE agent='classifier' GROUP BY path HAVING c > 2").fetchall()
    assert per_path == [], "a note was classified more than once per content version"
    assert sum(classified) >= 62 + 3
    assert st.conn.execute("SELECT COUNT(*) FROM notes WHERE status='done'").fetchone()[0] == 62


def test_ac4_two_worker_processes(tmp_path: Path) -> None:
    vault, state = tmp_path / "vault", tmp_path / "state"
    gardener = [sys.executable, "-m", "vault_gardener.cli"]
    subprocess.run([*gardener, "copy-fixture", str(vault)], check=True, capture_output=True)
    cmd = [*gardener, "run", "--vault", str(vault), "--state", str(state), "--ticks", "2", "--sim-clock",
           "--daily-cap-usd", "100", "--daily-token-budget", "100000000"]
    state.mkdir()
    procs = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outs = [p.communicate(timeout=180) for p in procs]
    for p, (_out, err) in zip(procs, outs, strict=True):
        assert p.returncode == 0, err
    st = State(state / "state.sqlite", vault, SimClock())
    _check_vault(vault, st)
    done = st.conn.execute("SELECT COUNT(*) FROM notes WHERE status='done'").fetchone()[0]
    assert done == 62  # every note but the malformed one, each linked exactly once between the two processes
    dup = st.conn.execute("SELECT path FROM changes WHERE agent='linker' GROUP BY path HAVING COUNT(*) > 1").fetchall()
    assert dup == []


def test_slow_model_call_past_the_lease_renews_instead_of_crashing(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    # Overnight review 2026-11-22 S6: a call longer than the 120 s lease (slow SDK call, laptop asleep) raised an
    # uncaught LockLost, the process died and the run row still said "ok".
    from vault_gardener.clock import SimClock
    from vault_gardener.llm import CallResult, RecordedCaller

    clock = SimClock()

    class Slow(RecordedCaller):
        def call(self, spec, user_text, key) -> CallResult:  # type: ignore[no-untyped-def]
            clock.advance(200)
            return super().call(spec, user_text, key)

    w = make_worker(clock=clock, caller=Slow())
    r = w.tick()
    assert r.status == "ok" and r.counts.notes_classified > 0
    assert w.state.check_consistency() == []


def test_lease_taken_over_during_a_call_is_a_conflict_not_a_crash(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    from vault_gardener.clock import SimClock
    from vault_gardener.llm import CallResult, RecordedCaller

    clock = SimClock()
    holder: dict[str, object] = {}

    class Thief(RecordedCaller):
        def call(self, spec, user_text, key) -> CallResult:  # type: ignore[no-untyped-def]
            if sum(self.calls.values()) == 0:
                clock.advance(200)  # our lease expires ...
                path = key.split(":", 1)[1]
                assert holder["w"].state.try_lock(path, "other-worker", 120)  # type: ignore[attr-defined]  # ... and is taken
                holder["path"] = path
            return super().call(spec, user_text, key)

    w = make_worker(clock=clock, caller=Thief())
    holder["w"] = w
    r = w.tick()
    assert r.status == "ok" and r.counts.conflicts == 1
    w.state.unlock(str(holder["path"]), "other-worker")
    assert w.state.row(str(holder["path"]))["status"] == "pending_classify"  # retried next tick


def test_owner_save_during_the_write_is_not_overwritten(tmp_path: Path, vault: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Review 2026-11-22 S7: the CAS read happened before the change-log insert and the fsync; an owner save in that
    # window was overwritten and appeared in no before_text, so revert could not bring it back.
    import os as _os

    from vault_gardener import state as state_mod

    st = State(tmp_path / "s.sqlite", vault, SimClock())
    st.observe(P)
    v0 = (vault / P).read_text()
    real_fsync = _os.fsync
    fired: list[int] = []

    def owner_saves_mid_write(fd: int) -> None:
        real_fsync(fd)
        if not fired:
            fired.append(fd)
            with open(vault / P, "a", encoding="utf-8") as f:
                f.write("owner typed this\n")

    monkeypatch.setattr(state_mod.os, "fsync", owner_saves_mid_write)
    with st.lock(P, "classifier", 120):
        res = st.write_note(path=P, owner="classifier", run_id="r", tick=0, agent="classifier", based_on=v0,
                            new_text=note.set_frontmatter(v0, tags=["topic/programming"]))
    assert fired and res == "conflict"
    assert (vault / P).read_text() == v0 + "owner typed this\n"
    assert st.conn.execute("SELECT COUNT(*) FROM changes WHERE status='pending'").fetchone()[0] == 0
    assert not list(vault.glob(f"**/.{Path(P).name}.gardener-tmp-*"))
