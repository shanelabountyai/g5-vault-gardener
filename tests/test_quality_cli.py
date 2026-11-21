"""Quality report against the labeled sample (D-8, D-24) and the command line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fixtures import make_fixtures as mf

from vault_gardener.cli import main
from vault_gardener.config import LABELS_FILE
from vault_gardener.quality import render_markdown, run_quality


@pytest.fixture(scope="module")
def q(tmp_path_factory: pytest.TempPathFactory) -> dict:  # type: ignore[type-arg]
    return run_quality(tmp_path_factory.mktemp("q") / "s")


def test_quality_findings_are_exactly_the_designed_mistakes(q: dict) -> None:  # type: ignore[type-arg]
    labels = json.loads(LABELS_FILE.read_text())["notes"]
    per = {p["path"]: p for p in q["per_note"]}
    for path in labels:
        m = mf.CLASSIFIER_MISTAKES.get(path, {})
        assert per[path]["missing_tags"] == ([m["drop"]] if "drop" in m else []), path
        assert per[path]["wrong_tags"] == ([m["add"]] if m.get("add", "").startswith("topic/") and m["add"] != "topic/baking" else []), path
        assert (per[path]["type"] == per[path]["type_expected"]) == ("type" not in m), path
        lm = mf.LINKER_MISTAKES.get(path, {})
        assert per[path]["wrong_links"] == ([lm["replace_last"]] if "replace_last" in lm else []), path


def test_quality_arithmetic(q: dict) -> None:  # type: ignore[type-arg]
    tc = q["tags_counts"]
    assert q["tag_precision"] == round(tc["correct"] / tc["on_notes"], 4)
    assert q["tag_recall"] == round(tc["correct"] / tc["expected"], 4)
    assert tc["on_notes"] - tc["correct"] == 2  # sqlite-wal-notes + commute-route-options extra topic tags
    assert tc["expected"] - tc["correct"] == 3  # three dropped status tags
    assert q["type_accuracy"] == round(19 / 20, 4)  # moon-phase-log typed as reference
    wrong_links = sum(len(p["wrong_links"]) for p in q["per_note"])
    assert wrong_links == 2
    assert q["link_precision"] == round((q["links_written"] - 2) / q["links_written"], 4)
    # G0 rubric: type and clean tags are required → moon-phase-log, sqlite-wal-notes, commute-route-options fail.
    failing = sorted(p["path"] for p in q["per_note"] if not p["g0_passed"])
    assert failing == ["logs/moon-phase-log.md", "reference/commute-route-options.md", "reference/sqlite-wal-notes.md"]
    assert q["g0_rubric_passed"] == 17
    md = render_markdown(q)
    assert "not a measurement of any model" in md


def test_cli_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    v, s = tmp_path / "v", tmp_path / "s"
    assert main(["copy-fixture", str(v)]) == 0
    base = ["--vault", str(v), "--state", str(s)]
    assert main(["run", *base, "--ticks", "2", "--sim-clock"]) == 0
    assert main(["status", *base]) == 0
    assert main(["report", "--state", str(s), "--vault", str(v), "--out", str(tmp_path / "r.md")]) == 0
    assert "Links added" in (tmp_path / "r.md").read_text()
    assert main(["revert", *base, "--all"]) == 1, "revert refuses while the switch is off"
    assert main(["kill", *base, "--reason", "test"]) == 0
    assert main(["run", *base, "--ticks", "1", "--sim-clock"]) == 3
    assert main(["revert", *base, "--all"]) == 0
    assert main(["resume", *base]) == 0
    with pytest.raises(SystemExit):
        main(["simulate", "--inject", "nonsense@1"])


def test_cli_run_on_the_fixture_itself_is_refused(tmp_path: Path) -> None:
    from vault_gardener.config import FIXTURE_VAULT
    from vault_gardener.safety import NotACopyVault

    with pytest.raises(NotACopyVault):
        main(["run", "--vault", str(FIXTURE_VAULT), "--state", str(tmp_path / "s"), "--ticks", "1", "--sim-clock"])


def test_cli_simulate_and_quality_write_reports(tmp_path: Path) -> None:
    assert main(["simulate", "--ticks", "4", "--state", str(tmp_path / "a"), "--report", str(tmp_path / "d.md")]) == 0
    assert main(["simulate", "--ticks", "4", "--state", str(tmp_path / "b"), "--inject", "cost-spike@0"]) == 0
    assert main(["quality", "--state", str(tmp_path / "q"), "--out", str(tmp_path / "q.md")]) == 0
    assert "Tag precision" in (tmp_path / "q.md").read_text()


def test_demo_passes(tmp_path: Path) -> None:
    assert main(["demo", "--out", str(tmp_path / "demo")]) == 0
    for f in ("daily-report.md", "quality-report.md"):
        assert (tmp_path / "demo" / f).exists()
