"""The synthetic fixtures (D-1, D-24): deterministic, synthetic, complete."""

from __future__ import annotations

import filecmp
import json
import re
import subprocess
import sys
from pathlib import Path

from vault_gardener.config import FIXTURES_DIR, LABELS_FILE, RECORDED_FILE, TAXONOMY_FILE


def test_generator_is_deterministic(tmp_path: Path) -> None:
    subprocess.run([sys.executable, str(FIXTURES_DIR / "make_fixtures.py"), str(tmp_path)], check=True, capture_output=True)
    for name in ("arrivals.json", "taxonomy.json", "labels.json", "recorded.json"):
        assert (tmp_path / name).read_text() == (FIXTURES_DIR / name).read_text(), name
    for sub in ("vault", "arrivals"):
        cmp = filecmp.dircmp(tmp_path / sub, FIXTURES_DIR / sub)
        stack = [cmp]
        while stack:
            c = stack.pop()
            assert not (c.left_only or c.right_only or c.diff_files), (sub, c.left_only, c.right_only, c.diff_files)
            stack.extend(c.subdirs.values())


def test_shape_and_counts() -> None:
    notes = sorted((FIXTURES_DIR / "vault").rglob("*.md"))
    assert len(notes) == 63
    assert {p.parent.name for p in notes} == {"projects", "reference", "ideas", "logs", "inbox"}
    assert len(list((FIXTURES_DIR / "vault" / "inbox").glob("*.md"))) == 6
    assert len(list((FIXTURES_DIR / "arrivals").glob("*.md"))) == 6
    assert len(json.loads(LABELS_FILE.read_text())["notes"]) == 20
    slugs = [p.stem for p in notes] + [p.stem for p in (FIXTURES_DIR / "arrivals").glob("*.md")]
    assert len(slugs) == len(set(slugs)), "note ids must be unique"


def test_synthetic_only() -> None:
    """No emails, URLs or phone-like numbers anywhere in the vault or arrivals."""
    texts = [p.read_text() for p in FIXTURES_DIR.rglob("*.md")]
    for t in texts:
        assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", t)
        assert "http" not in t
        assert not re.search(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b", t)


def test_recorded_covers_every_note_and_carries_designed_mistakes() -> None:
    rec = json.loads(RECORDED_FILE.read_text())["responses"]
    tax = json.loads(TAXONOMY_FILE.read_text())
    paths = [p.relative_to(FIXTURES_DIR / "vault").as_posix() for p in (FIXTURES_DIR / "vault").rglob("*.md")]
    paths += [f"inbox/{p.name}" for p in (FIXTURES_DIR / "arrivals").glob("*.md")]
    for p in paths:
        assert f"classifier:{p}" in rec
    assert isinstance(rec["classifier:inbox/router-reboot-again.md"], str)  # the malformed one
    assert "linker:inbox/router-reboot-again.md" not in rec
    assert "topic/baking" in rec["classifier:reference/sourdough-hydration-table.md"]["tags"]
    assert "topic/baking" not in tax["tags"]
    assert "pi-hole-setup" in rec["linker:ideas/dns-filtering-idea.md"]["related"]
    assert "HAND-WRITTEN" in json.loads(RECORDED_FILE.read_text())["_about"]
