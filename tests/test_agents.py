"""Agents write only what the PRD allows; model output is validated, never trusted (D-12, D-13, D-21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vault_gardener import note, safety
from vault_gardener.cli import main
from vault_gardener.config import FIXTURE_VAULT
from vault_gardener.llm import CLASSIFIER, LINKER, AgentSdkCaller, LiveCallRefused
from vault_gardener.simulate import body_hashes


def _texts(vault: Path) -> dict[str, str]:
    return {p.relative_to(vault).as_posix(): p.read_text() for p in vault.rglob("*.md")}


def test_watcher_writes_the_state_table_only(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    from vault_gardener import agents

    w = make_worker()
    before = _texts(vault)
    ctx = agents.Context(state=w.state, supervisor=w.supervisor, caller=w.caller, tracer=w.telemetry.tracer, taxonomy=w.taxonomy,
                         owner="t", run_id="r", tick=0, counts=agents.TickCounts())
    seen = agents.watch(ctx)
    assert seen["new"] == 63
    assert _texts(vault) == before
    assert sum(w.caller.calls.values()) == 0
    (vault / "logs/moon-phase-log.md").write_text((vault / "logs/moon-phase-log.md").read_text() + "x\n")
    (vault / "reference/vlan-notes.md").unlink()
    seen = agents.watch(ctx)
    assert (seen["changed"], seen["missing"]) == (1, 1)


def test_one_tick_every_change_is_tags_type_or_related_only(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    r = w.tick()
    assert r.status == "ok"
    rows = w.state.conn.execute("SELECT agent, path, before_text, after_text FROM changes").fetchall()
    assert rows
    for ch in rows:
        assert safety.check_change(ch["before_text"], ch["after_text"]) == []
        b, a = note.parse(ch["before_text"]), note.parse(ch["after_text"])
        if ch["agent"] == "classifier":
            assert a.related == b.related
        else:
            assert (a.fm_lines, a.tags(), a.type()) == (b.fm_lines, b.tags(), b.type())
    for path, h in body_hashes(FIXTURE_VAULT).items():
        assert body_hashes(vault)[path] == h


def test_classifier_keeps_owner_tags_and_type(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    w.tick()
    pinned = note.parse((vault / "projects/bread-oven-schedule.md").read_text())
    assert pinned.tags()[0] == "pinned" and "topic/cooking" in pinned.tags()
    owned = note.parse((vault / "reference/seed-starting-calendar.md").read_text())  # owner wrote `type: reference`
    assert owned.type() == "reference"
    assert "created: " in (vault / "reference/seed-starting-calendar.md").read_text().split("---")[1]


def test_tags_outside_the_taxonomy_are_dropped_and_logged(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    r = w.tick()
    p = "reference/sourdough-hydration-table.md"
    assert "topic/baking" not in note.parse((vault / p).read_text()).tags()
    assert json.loads(w.state.row(p)["tags_rejected"]) == ["topic/baking"]
    assert "topic/baking" in r.counts.tags_rejected


def test_unknown_link_targets_and_self_links_are_dropped(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    w.tick()
    p = "ideas/dns-filtering-idea.md"
    assert "pi-hole-setup" not in note.parse((vault / p).read_text()).related
    assert json.loads(w.state.row(p)["links_rejected"]) == ["pi-hole-setup"]
    for f in vault.rglob("*.md"):
        assert f.stem not in note.parse(f.read_text()).related


def test_folder_suggestions_are_recorded_never_moved(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    w.tick()
    assert (vault / "inbox/clipped-mulch-tips.md").exists()
    assert w.state.row("inbox/clipped-mulch-tips.md")["suggested_folder"] == "reference"
    assert sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*.md")) == sorted(
        p.relative_to(FIXTURE_VAULT).as_posix() for p in FIXTURE_VAULT.rglob("*.md"))


def test_suggest_only_writes_no_related_section(make_worker, vault: Path, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker(suggest_only=True)
    w.tick()
    assert all(not note.parse(f.read_text()).has_block for f in vault.rglob("*.md"))
    lines = (tmp_path / "state" / "suggestions.jsonl").read_text().splitlines()
    assert len(lines) == 62  # every note but the malformed one
    assert w.state.conn.execute("SELECT COUNT(*) FROM changes WHERE agent='linker'").fetchone()[0] == 0


def test_malformed_output_is_an_error_and_the_note_is_parked_after_three(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    w = make_worker()
    p = "inbox/router-reboot-again.md"
    original = (vault / p).read_text()
    for _ in range(4):
        w.tick()
        w.clock.sleep(900)
    assert w.state.row(p)["status"] == "error"
    errs = w.state.conn.execute("SELECT kind FROM errors WHERE path=?", (p,)).fetchall()
    assert [e["kind"] for e in errs] == ["MalformedOutput"] * 3
    assert (vault / p).read_text() == original
    (vault / p).write_text(original + "more\n")  # a content change un-parks it
    w.tick()
    assert w.state.row(p)["attempts"] == 1


def test_prompts_carry_no_shared_layer_rules() -> None:
    for spec in (CLASSIFIER, LINKER):
        s = spec.system.lower()
        for banned in ("cost", "cap", "budget", "$", "log every", "token", "rubric", "precision"):
            assert banned not in s, (spec.name, banned)
        assert len(spec.system) < 400


def test_live_caller_refuses_without_a_key(tmp_path: Path) -> None:
    with pytest.raises(LiveCallRefused):
        AgentSdkCaller()
    v = tmp_path / "v"
    assert main(["copy-fixture", str(v)]) == 0
    assert main(["run", "--vault", str(v), "--state", str(tmp_path / "s"), "--ticks", "1", "--live"]) == 1
    assert not (tmp_path / "s").exists()


def test_no_network_client_in_the_package() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "vault_gardener"
    for f in src.glob("*.py"):
        t = f.read_text()
        for mod in ("import requests", "import httpx", "urllib.request", "import smtplib", "import socket"):
            assert mod not in t, (f.name, mod)


def _status(w, path: str) -> str:  # type: ignore[no-untyped-def]
    return str(w.state.row(path)["status"])


def test_crlf_note_is_left_byte_identical(make_worker, vault: Path) -> None:  # type: ignore[no-untyped-def]
    # Overnight review 2026-11-22 M1: universal-newline reads turned \r\n into \n on the first write, and every
    # body-hash check hashed the converted text, so nothing noticed.
    p = vault / "projects/bread-oven-schedule.md"
    raw = p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    p.write_bytes(raw)
    w = make_worker()
    r = w.tick()
    assert r.status == "ok"
    assert p.read_bytes() == raw
    assert _status(w, "projects/bread-oven-schedule.md") == "unsupported"
    assert w.state.check_consistency() == []
    w.state.revert()
    assert p.read_bytes() == raw
