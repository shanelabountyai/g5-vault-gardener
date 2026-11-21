"""State table: leases, compare-and-swap writer, two-phase log, consistency, revert (D-14, D-15, D-17)."""

from __future__ import annotations

import filecmp
from pathlib import Path

import pytest

from vault_gardener import note
from vault_gardener.clock import SimClock
from vault_gardener.config import FIXTURE_VAULT
from vault_gardener.safety import SafetyViolation
from vault_gardener.state import LockLost, State

P = "reference/regex-cheatsheet.md"


@pytest.fixture
def st(tmp_path: Path, vault: Path) -> State:
    s = State(tmp_path / "state.sqlite", vault, SimClock())
    assert s.observe(P) == "new"
    return s


def test_lease_cannot_be_taken_twice_and_expires(st: State) -> None:
    assert st.try_lock(P, "a", 120)
    assert not st.try_lock(P, "b", 120)
    assert isinstance(st.clock, SimClock)
    st.clock.advance(121)
    assert st.try_lock(P, "b", 120), "an expired lease can be taken over"
    st.unlock(P, "a")  # not the holder: no effect
    assert st.holds_lock(P, "b")
    st.unlock(P, "b")
    assert not st.holds_lock(P, "b")


def test_two_connections_see_the_same_lease(tmp_path: Path, vault: Path, st: State) -> None:
    other = State(tmp_path / "state.sqlite", vault, st.clock)
    assert st.try_lock(P, "a", 120)
    assert not other.try_lock(P, "b", 120)
    other.close()


def test_writer_requires_the_lease(st: State, vault: Path) -> None:
    text = (vault / P).read_text()
    with pytest.raises(LockLost):
        st.write_note(path=P, owner="a", run_id="r", tick=0, agent="classifier", based_on=text, new_text=note.set_frontmatter(text, tags=["x"]))


def test_compare_and_swap_refuses_a_stale_write(st: State, vault: Path) -> None:
    text = (vault / P).read_text()
    (vault / P).write_text(text + "owner typed this\n")
    with st.lock(P, "a", 120):
        res = st.write_note(path=P, owner="a", run_id="r", tick=0, agent="classifier", based_on=text,
                            new_text=note.set_frontmatter(text, tags=["topic/programming"]))
    assert res == "conflict"
    assert (vault / P).read_text() == text + "owner typed this\n"
    assert st.conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0


def test_unsafe_write_is_refused_and_nothing_is_written(st: State, vault: Path) -> None:
    text = (vault / P).read_text()
    with st.lock(P, "a", 120), pytest.raises(SafetyViolation):
        st.write_note(path=P, owner="a", run_id="r", tick=0, agent="linker", based_on=text, new_text=text.replace("# Regex", "# regex"))
    assert (vault / P).read_text() == text
    assert st.conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0


def test_applied_write_is_logged_with_before_and_after(st: State, vault: Path) -> None:
    text = (vault / P).read_text()
    new = note.set_related(text, ["sqlite-wal-notes"])
    with st.lock(P, "a", 120):
        assert st.write_note(path=P, owner="a", run_id="r1", tick=0, agent="linker", based_on=text, new_text=new, status="done") == "applied"
    ch = st.conn.execute("SELECT * FROM changes").fetchone()
    assert (ch["before_text"], ch["after_text"], ch["status"]) == (text, new, "applied")
    assert st.row(P)["content_hash"] == note.sha256(new)
    assert st.check_consistency() == []


def test_reconcile_settles_half_written_changes(st: State, vault: Path) -> None:
    text = (vault / P).read_text()
    new = note.set_related(text, ["x"])
    for after_on_disk, expected in ((new, "applied"), (text, "aborted")):
        st.conn.execute("INSERT INTO changes (run_id,tick,agent,path,before_text,after_text,before_hash,after_hash,status,at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        ("r", 0, "linker", P, text, new, note.sha256(text), note.sha256(new), "pending", "t"))
        (vault / P).write_text(after_on_disk)
        assert any("not settled" in p for p in st.check_consistency())
        out = st.reconcile()
        assert out[expected] == 1
        assert st.conn.execute("SELECT status FROM changes ORDER BY change_id DESC").fetchone()[0] == expected
        (vault / P).write_text(text)
        st.conn.execute("UPDATE notes SET content_hash=? WHERE path=?", (note.sha256(text), P))


def test_consistency_catches_held_lock_and_untracked_write(st: State, vault: Path) -> None:
    assert st.check_consistency() == []
    st.try_lock(P, "a", 120)
    assert any("locks still held" in p for p in st.check_consistency())
    st.unlock(P, "a")
    (vault / P).write_text("changed outside the log\n")
    assert any("differs" in p for p in st.check_consistency())


def test_kill_switch_first_reason_wins(st: State) -> None:
    assert st.set_killed("cost", "over", "r1")
    assert not st.set_killed("error_burst", "later", "r2")
    assert st.kill_state()["reason"] == "cost"  # type: ignore[index]
    assert st.clear_killed()
    assert st.kill_state() is None


def _same_tree(a: Path, b: Path) -> bool:
    stack = [filecmp.dircmp(a, b, ignore=[".gardener-copy"])]
    while stack:
        c = stack.pop()
        _, mismatch, errors = filecmp.cmpfiles(c.left, c.right, c.common_files, shallow=False)
        if c.left_only or c.right_only or mismatch or errors:
            return False
        stack.extend(c.subdirs.values())
    return True


def test_revert_all_restores_the_vault_byte_for_byte(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    w.tick()
    assert not _same_tree(vault, FIXTURE_VAULT)
    out = w.state.revert()
    assert out["conflicts"] == [] and len(out["reverted"]) > 100
    assert _same_tree(vault, FIXTURE_VAULT)
    assert w.state.check_consistency() == []
    assert w.state.change_chain_breaks() == []


def test_revert_skips_a_file_the_owner_edited_since(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    r = w.tick()
    edited = vault / P
    edited.write_text(edited.read_text() + "owner note\n")
    out = w.state.revert(r.run_id)
    assert any(P in c for c in out["conflicts"])
    assert edited.read_text().endswith("owner note\n")
