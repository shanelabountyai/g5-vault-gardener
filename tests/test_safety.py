"""Safety invariants, written before any agent code path could write (BACKLOG C2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vault_gardener import note, safety

NOTE = """---
created: 2026-10-02
aliases: [Starter log]
tags:
  - topic/cooking
---
# Sourdough starter log

Fed the starter at 1:5:5.

## Related

- [[my-own-link]]
"""

NO_FM = "# Bare note\n\nNo frontmatter here.\n"
NO_TRAILING_NL = "---\ntype: idea\n---\n# Ends abruptly\n\nlast line"


@pytest.mark.parametrize("text", [NOTE, NO_FM, NO_TRAILING_NL, "", "---\n---\n", "---\nfoo: 1\n---\n\n\n\n"])
def test_body_survives_every_allowed_edit(text: str) -> None:
    h = note.body_hash(text)
    t1 = note.set_frontmatter(text, tags=["topic/cooking", "status/active"], type_="log" if "type:" not in text else None)
    t2 = note.set_related(t1, ["a-note", "b-note"])
    t3 = note.set_related(t2, ["c-note"])
    for t in (t1, t2, t3):
        assert note.body_hash(t) == h
        assert safety.check_change(text, t) == []
    assert note.parse(t3).related == ("c-note",)


def test_removing_block_restores_bytes_exactly() -> None:
    for text in (NOTE, NO_TRAILING_NL, "---\ntags: []\n---\nbody\n\n"):
        linked = note.set_related(text, ["x"])
        assert note.set_related(linked, []) == text


def test_other_frontmatter_lines_are_byte_identical() -> None:
    after = note.set_frontmatter(NOTE, tags=["topic/cooking", "status/done"], type_="log")
    assert "created: 2026-10-02\naliases: [Starter log]\n" in after
    assert note.parse(after).tags() == ["topic/cooking", "status/done"]
    assert note.parse(after).type() == "log"


def test_user_related_heading_is_body_and_untouched() -> None:
    linked = note.set_related(NOTE, ["sourdough-hydration"])
    assert "## Related\n\n- [[my-own-link]]\n" in linked
    assert note.parse(linked).body == note.parse(NOTE).body
    assert note.parse(linked).related == ("sourdough-hydration",)


def test_no_frontmatter_gets_one_with_only_tags_and_type() -> None:
    after = note.set_frontmatter(NO_FM, tags=["topic/reading"], type_="reference")
    assert after.startswith("---\ntags:\n  - topic/reading\ntype: reference\n---\n# Bare note")
    assert safety.check_change(NO_FM, after) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda t: t.replace("Fed the starter", "Fed the  starter"), "body changed"),
        (lambda t: t.replace("# Sourdough starter log\n", ""), "body changed"),
        (lambda t: t + "extra line\n", "body changed"),
        (lambda t: t.split("---\n", 2)[0] + "---\n" + t.split("---\n", 2)[1] + "---\n", "body changed"),  # body deleted
        (lambda t: t.replace("created: 2026-10-02", "created: 2026-10-03"), "frontmatter outside tags/type changed"),
        (lambda t: t.replace("aliases: [Starter log]\n", ""), "frontmatter outside tags/type changed"),
        (lambda t: t.replace("  - topic/cooking\n", "  - topic/gardening\n"), "tags removed"),
        (lambda t: t.replace("---\ncreated", "---\nsource: web\ncreated"), "frontmatter outside tags/type changed"),
    ],
)
def test_forbidden_edits_are_caught(mutate, expected) -> None:  # type: ignore[no-untyped-def]
    after = mutate(NOTE)
    assert after != NOTE
    problems = safety.check_change(NOTE, after)
    assert any(expected in p for p in problems), problems
    with pytest.raises(safety.SafetyViolation):
        safety.assert_safe(NOTE, after)


def test_type_overwrite_is_refused() -> None:
    after = note.set_frontmatter(NO_TRAILING_NL, type_="project")
    assert any("type overwritten" in p for p in safety.check_change(NO_TRAILING_NL, after))


def test_frontmatter_removal_is_refused() -> None:
    assert "frontmatter removed" in safety.check_change(NOTE, note.parse(NOTE).body)


def test_fake_block_in_the_middle_is_body() -> None:
    """A marker that is not at the very end is ordinary body text; replacing it is a body change."""
    text = "# T\n\n" + note.RELATED_START + "\n- [[x]]\n" + note.RELATED_END + "\n\nmore owner text\n"
    assert note.parse(text).has_block is False
    after = text.replace("- [[x]]", "- [[y]]")
    assert "body changed" in safety.check_change(text, after)


def test_worker_refuses_fixture_vault_and_unmarked_vaults(tmp_path: Path) -> None:
    with pytest.raises(safety.NotACopyVault):
        safety.ensure_copy_vault(safety.FIXTURES_DIR / "vault")
    with pytest.raises(safety.NotACopyVault):
        safety.ensure_copy_vault(tmp_path)
    (tmp_path / safety.COPY_MARKER).write_text("copy\n")
    assert safety.ensure_copy_vault(tmp_path) == tmp_path.resolve()
    with pytest.raises(safety.NotACopyVault):
        safety.ensure_copy_vault(tmp_path / "missing")
