"""The shared state table (one SQLite file) and the only code path that writes a note (D-14, D-15, D-17).

Tables
- `notes`      one row per vault note: content/body hash, status, attempts, suggestions, and the row lock (lease).
- `changes`    every note write, whole file before and after, two-phase (`pending` → `applied`), revertible.
- `runs`       one row per tick: counts, tokens, cost, how it ended.
- `errors`     every agent error (the supervisor counts these for the error-burst limit).
- `supervisor` the kill switch.

Every connection is its own (one per agent, thread or process), WAL mode, `BEGIN IMMEDIATE` for writes.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from vault_gardener import note, safety
from vault_gardener.clock import Clock, iso

STATUSES = ("pending_classify", "pending_link", "done", "error", "missing", "reverted", "unsupported")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    suggested_folder TEXT,
    suggested_type TEXT,
    tags_rejected TEXT NOT NULL DEFAULT '[]',
    links_rejected TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_changed TEXT NOT NULL,
    classified_at TEXT,
    linked_at TEXT,
    lock_owner TEXT,
    lock_expires REAL
);
CREATE TABLE IF NOT EXISTS changes (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    agent TEXT NOT NULL,
    path TEXT NOT NULL,
    before_text TEXT NOT NULL,
    after_text TEXT NOT NULL,
    before_hash TEXT NOT NULL,
    after_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    at TEXT NOT NULL,
    reverts INTEGER
);
CREATE INDEX IF NOT EXISTS changes_by_path ON changes(path, change_id);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    tick INTEGER NOT NULL,
    day TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    notes_seen INTEGER NOT NULL DEFAULT 0,
    notes_classified INTEGER NOT NULL DEFAULT 0,
    notes_linked INTEGER NOT NULL DEFAULT 0,
    tags_added INTEGER NOT NULL DEFAULT 0,
    links_added INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    conflicts INTEGER NOT NULL DEFAULT 0,
    model_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    agent TEXT NOT NULL,
    path TEXT,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    at TEXT NOT NULL,
    at_epoch REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS supervisor (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

WriteResult = Literal["applied", "noop", "conflict"]


class LockLost(RuntimeError):
    """The writer no longer holds the note's lease; it must not write."""


def read_text(path: Path) -> str | None:
    try:
        # Bytes in, no newline translation: a CRLF note must hash (and be compared) as it is on disk (review M1).
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None


def atomic_write(path: Path, text: str, expect_hash: str | None = None) -> bool:
    """Write via a temp file and rename. With `expect_hash`, re-check the file right before the rename and give up
    (temp file removed, False) if it changed: an owner save during the write wins (review 2026-11-22 S7). This
    narrows the window to the instant between that read and `os.replace`; a plain filesystem offers no atomic
    compare-and-rename."""
    tmp = path.with_name(f".{path.name}.gardener-tmp-{uuid.uuid4().hex[:8]}")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if expect_hash is not None:
        current = read_text(path)
        if current is None or note.sha256(current) != expect_hash:
            tmp.unlink(missing_ok=True)
            return False
    os.replace(tmp, path)
    return True


class State:
    def __init__(self, db_file: Path, vault: Path, clock: Clock) -> None:
        self.db_file, self.vault, self.clock = db_file, vault, clock
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_file), timeout=30, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA synchronous=NORMAL")  # WAL + NORMAL: no corruption on crash; reconcile() settles the rest
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def now(self) -> datetime:
        return self.clock.now()

    def now_iso(self) -> str:
        return iso(self.clock.now())

    def epoch(self) -> float:
        return self.clock.now().timestamp()

    # -- notes ---------------------------------------------------------------

    def row(self, path: str) -> sqlite3.Row | None:
        r: sqlite3.Row | None = self.conn.execute("SELECT * FROM notes WHERE path = ?", (path,)).fetchone()
        return r

    def rows(self, status: str | None = None) -> list[sqlite3.Row]:
        if status is None:
            return list(self.conn.execute("SELECT * FROM notes ORDER BY path"))
        return list(self.conn.execute("SELECT * FROM notes WHERE status = ? ORDER BY path", (status,)))

    def observe(self, path: str) -> Literal["new", "changed", "same", "busy", "gone"]:
        """Watcher: read the note inside a write transaction and record it as new or changed (→ pending_classify).
        A row that is leased, or has a change in flight, is left alone ("busy"): its writer owns it."""
        with self.tx() as c:
            r = c.execute("SELECT content_hash, status, lock_owner, lock_expires FROM notes WHERE path = ?", (path,)).fetchone()
            if r is not None and r["lock_owner"] is not None and (r["lock_expires"] or 0) >= self.epoch():
                return "busy"
            if c.execute("SELECT 1 FROM changes WHERE path=? AND status='pending'", (path,)).fetchone():
                return "busy"
            text = read_text(self.vault / path)
            if text is None:
                return "gone"
            content_hash, body_hash = note.sha256(text), note.body_hash(text)
            now = self.now_iso()
            if r is None:
                c.execute("INSERT INTO notes (path, content_hash, body_hash, status, first_seen, last_changed) VALUES (?,?,?,?,?,?)",
                          (path, content_hash, body_hash, "pending_classify", now, now))
                return "new"
            if r["content_hash"] == content_hash and r["status"] not in ("missing",):
                return "same"
            if r["content_hash"] == content_hash and r["status"] == "missing":
                c.execute("UPDATE notes SET status='pending_classify', attempts=0, last_changed=? WHERE path=?", (now, path))
                return "changed"
            c.execute("UPDATE notes SET content_hash=?, body_hash=?, status='pending_classify', attempts=0, last_changed=? WHERE path=?",
                      (content_hash, body_hash, now, path))
            return "changed"

    def mark_missing(self, path: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE notes SET status='missing' WHERE path=? AND status != 'missing'", (path,))

    def set_fields(self, path: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE notes SET {cols} WHERE path=?", (*fields.values(), path))

    # -- row locks (D-14) ----------------------------------------------------

    def try_lock(self, path: str, owner: str, lease_s: float) -> bool:
        now = self.epoch()
        with self.tx() as c:
            cur = c.execute(
                "UPDATE notes SET lock_owner=?, lock_expires=? WHERE path=? AND (lock_owner IS NULL OR lock_expires < ? OR lock_owner = ?)",
                (owner, now + lease_s, path, now, owner),
            )
            return cur.rowcount == 1

    def unlock(self, path: str, owner: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE notes SET lock_owner=NULL, lock_expires=NULL WHERE path=? AND lock_owner=?", (path, owner))

    def holds_lock(self, path: str, owner: str) -> bool:
        r = self.conn.execute("SELECT lock_owner, lock_expires FROM notes WHERE path=?", (path,)).fetchone()
        return r is not None and r["lock_owner"] == owner and (r["lock_expires"] or 0) >= self.epoch()

    @contextmanager
    def lock(self, path: str, owner: str, lease_s: float) -> Iterator[bool]:
        got = self.try_lock(path, owner, lease_s)
        try:
            yield got
        finally:
            if got:
                self.unlock(path, owner)

    def release_all_locks(self) -> int:
        with self.tx() as c:
            return c.execute("UPDATE notes SET lock_owner=NULL, lock_expires=NULL WHERE lock_owner IS NOT NULL").rowcount

    # -- the writer (D-12, D-14, D-17) ---------------------------------------

    def write_note(self, *, path: str, owner: str, run_id: str, tick: int, agent: str, based_on: str, new_text: str,
                   **row_updates: Any) -> WriteResult:
        """Write `new_text` over `based_on`, only under the lease, only if the file still equals `based_on`,
        only if every safety invariant holds. Logs the change before the write (two-phase)."""
        if not self.holds_lock(path, owner):
            raise LockLost(f"{owner} does not hold the lease on {path}")
        file = self.vault / path
        current = read_text(file)
        if current is None or note.sha256(current) != note.sha256(based_on):
            return "conflict"
        if new_text == based_on:
            self.set_fields(path, **row_updates)
            return "noop"
        safety.assert_safe(based_on, new_text, path)  # raises SafetyViolation: nothing is written
        b_hash, a_hash = note.sha256(based_on), note.sha256(new_text)
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO changes (run_id, tick, agent, path, before_text, after_text, before_hash, after_hash, status, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, tick, agent, path, based_on, new_text, b_hash, a_hash, "pending", self.now_iso()),
            )
            change_id = cur.lastrowid
        if not atomic_write(file, new_text, expect_hash=b_hash):
            with self.tx() as c:
                c.execute("UPDATE changes SET status='aborted' WHERE change_id=?", (change_id,))
            return "conflict"
        updates = {"content_hash": a_hash, "body_hash": note.body_hash(new_text), **row_updates}
        cols = ", ".join(f"{k}=?" for k in updates)
        with self.tx() as c:
            c.execute("UPDATE changes SET status='applied' WHERE change_id=?", (change_id,))
            c.execute(f"UPDATE notes SET {cols} WHERE path=?", (*updates.values(), path))
        return "applied"

    def reconcile(self) -> dict[str, int]:
        """Settle `pending` changes left by a crash between log and write (D-14)."""
        out = {"applied": 0, "aborted": 0, "inconsistent": 0}
        for ch in list(self.conn.execute("SELECT * FROM changes WHERE status='pending' ORDER BY change_id")):
            current = read_text(self.vault / ch["path"])
            h = note.sha256(current) if current is not None else None
            if h == ch["after_hash"]:
                with self.tx() as c:
                    c.execute("UPDATE changes SET status='applied' WHERE change_id=?", (ch["change_id"],))
                    c.execute("UPDATE notes SET content_hash=?, body_hash=? WHERE path=?", (h, note.body_hash(current or ""), ch["path"]))
                out["applied"] += 1
            elif h == ch["before_hash"]:
                with self.tx() as c:
                    c.execute("UPDATE changes SET status='aborted' WHERE change_id=?", (ch["change_id"],))
                out["aborted"] += 1
            else:
                out["inconsistent"] += 1
        return out

    # -- revert (D-17) ---------------------------------------------------------

    def revert(self, run_id: str | None = None, owner: str = "revert") -> dict[str, list[str]]:
        """Undo applied agent changes newest-first. Only where the file still equals the logged 'after'."""
        sql = "SELECT * FROM changes WHERE status='applied' AND agent != 'revert'"
        args: tuple[Any, ...] = ()
        if run_id is not None:
            sql += " AND run_id=?"
            args = (run_id,)
        done: list[str] = []
        conflicts: list[str] = []
        for ch in list(self.conn.execute(sql + " ORDER BY change_id DESC", args)):
            path = ch["path"]
            with self.lock(path, owner, 600) as got:
                current = read_text(self.vault / path)
                if not got or current is None or note.sha256(current) != ch["after_hash"]:
                    conflicts.append(f"{path} (change {ch['change_id']})")
                    continue
                with self.tx() as c:
                    cur = c.execute(
                        "INSERT INTO changes (run_id, tick, agent, path, before_text, after_text, before_hash, after_hash, status, at, reverts) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (ch["run_id"], ch["tick"], "revert", path, ch["after_text"], ch["before_text"], ch["after_hash"], ch["before_hash"],
                         "pending", self.now_iso(), ch["change_id"]),
                    )
                    rid = cur.lastrowid
                atomic_write(self.vault / path, ch["before_text"])
                with self.tx() as c:
                    c.execute("UPDATE changes SET status='applied' WHERE change_id=?", (rid,))
                    c.execute("UPDATE changes SET status='reverted' WHERE change_id=?", (ch["change_id"],))
                    c.execute("UPDATE notes SET content_hash=?, body_hash=?, status='reverted' WHERE path=?",
                              (ch["before_hash"], note.body_hash(ch["before_text"]), path))
                done.append(f"{path} (change {ch['change_id']})")
        return {"reverted": done, "conflicts": conflicts}

    # -- runs, errors ----------------------------------------------------------

    def start_run(self, run_id: str, tick: int, day: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO runs (run_id, tick, day, started_at, status) VALUES (?,?,?,?,?)", (run_id, tick, day, self.now_iso(), "running"))

    def finish_run(self, run_id: str, status: str, counts: dict[str, Any]) -> None:
        cols = ", ".join(f"{k}=?" for k in counts)
        with self.tx() as c:
            c.execute(f"UPDATE runs SET status=?, finished_at=?{', ' + cols if cols else ''} WHERE run_id=?",
                      (status, self.now_iso(), *counts.values(), run_id))

    def add_error(self, run_id: str, tick: int, agent: str, path: str | None, kind: str, message: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO errors (run_id, tick, agent, path, kind, message, at, at_epoch) VALUES (?,?,?,?,?,?,?,?)",
                      (run_id, tick, agent, path, kind, message[:500], self.now_iso(), self.epoch()))

    def errors_since(self, epoch: float) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM errors WHERE at_epoch >= ?", (epoch,)).fetchone()[0])

    # -- kill switch (D-15) ----------------------------------------------------

    def kill_state(self) -> dict[str, Any] | None:
        r = self.conn.execute("SELECT value FROM supervisor WHERE key='killed'").fetchone()
        return json.loads(r["value"]) if r else None

    def set_killed(self, reason: str, detail: str, run_id: str | None) -> bool:
        """Set the switch. Returns False if it was already set (the first reason wins)."""
        with self.tx() as c:
            if c.execute("SELECT 1 FROM supervisor WHERE key='killed'").fetchone():
                return False
            c.execute("INSERT INTO supervisor (key, value) VALUES ('killed', ?)",
                      (json.dumps({"reason": reason, "detail": detail, "at": self.now_iso(), "run_id": run_id}),))
            return True

    def clear_killed(self) -> bool:
        with self.tx() as c:
            return c.execute("DELETE FROM supervisor WHERE key='killed'").rowcount == 1

    # -- consistency (D-15) ----------------------------------------------------

    def check_consistency(self) -> list[str]:
        """Empty when: no lease held, no half-written change, every status valid, and every tracked file on disk
        equals the hash the state table holds for it (so nothing was written outside the log)."""
        problems: list[str] = []
        held = [r["path"] for r in self.conn.execute("SELECT path FROM notes WHERE lock_owner IS NOT NULL")]
        if held:
            problems.append(f"locks still held: {held[:5]}")
        pending = self.conn.execute("SELECT COUNT(*) FROM changes WHERE status='pending'").fetchone()[0]
        if pending:
            problems.append(f"{pending} change(s) logged but not settled")
        for r in self.rows():
            if r["status"] not in STATUSES:
                problems.append(f"{r['path']}: bad status {r['status']!r}")
            if r["status"] == "missing":
                continue
            current = read_text(self.vault / r["path"])
            if current is None:
                problems.append(f"{r['path']}: file missing")
            elif note.sha256(current) != r["content_hash"]:
                problems.append(f"{r['path']}: file differs from the state table's hash")
        running = self.conn.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone()[0]
        if running:
            problems.append(f"{running} run(s) still marked running")
        return problems

    def change_chain_breaks(self) -> list[str]:
        """For each note, every applied agent change must start from the previous one's result (no lost update)."""
        breaks: list[str] = []
        last: dict[str, str] = {}
        for ch in self.conn.execute("SELECT * FROM changes WHERE status IN ('applied','reverted') ORDER BY change_id"):
            prev = last.get(ch["path"])
            if prev is not None and prev != ch["before_hash"]:
                breaks.append(f"{ch['path']}: change {ch['change_id']} did not start from the previous change's result")
            last[ch["path"]] = ch["after_hash"]
        return breaks

    def lost_updates(self) -> list[str]:
        """Two applied agent changes to one note that started from the same version: the later one overwrote the
        earlier one's work. Owner edits between changes are allowed (they legitimately break the strict chain)."""
        rows = self.conn.execute(
            "SELECT path, before_hash, COUNT(*) n, GROUP_CONCAT(change_id) ids FROM changes WHERE status IN ('applied','reverted') "
            "AND agent != 'revert' GROUP BY path, before_hash HAVING n > 1").fetchall()
        return [f"{r['path']}: changes {r['ids']} all started from the same version" for r in rows]

    # -- reporting helpers -----------------------------------------------------

    def runs_for_day(self, day: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM runs WHERE day=? ORDER BY tick", (day,)))

    def errors_for_day(self, day: str) -> list[sqlite3.Row]:
        return list(self.conn.execute(
            "SELECT e.* FROM errors e JOIN runs r ON r.run_id = e.run_id WHERE r.day=? ORDER BY e.error_id", (day,)))
