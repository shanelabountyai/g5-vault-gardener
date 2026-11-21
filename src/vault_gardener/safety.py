"""Safety invariants (D-11, D-12, D-20). These run inside the writer before every write, and in the tests.

1. The body (everything but frontmatter and the managed Related block) is byte-identical.
2. Frontmatter: every key other than `tags` and `type` keeps its exact lines, in order.
3. Tags only grow (an agent never removes or rewrites an owner's tag).
4. An existing `type` is never overwritten.
5. Agents only ever run on a marked copy of the vault, never the repo's fixture vault.
"""

from __future__ import annotations

from pathlib import Path

from vault_gardener import note

COPY_MARKER = ".gardener-copy"
REPO_DIR = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_DIR / "fixtures"


class SafetyViolation(RuntimeError):
    """A write would break a safety invariant. Refused; the supervisor trips (D-12, D-15)."""


class NotACopyVault(RuntimeError):
    """The worker was pointed at something other than a marked copy vault (D-20)."""


def check_change(before: str, after: str) -> list[str]:
    """Return the list of invariant violations going from `before` to `after` (empty = safe)."""
    problems: list[str] = []
    b, a = note.parse(before), note.parse(after)
    if b.body_hash != a.body_hash:
        problems.append("body changed")
    b_blocks = note.key_blocks(b.fm_lines) if b.fm_lines is not None else []
    a_blocks = note.key_blocks(a.fm_lines) if a.fm_lines is not None else []
    keep_b = [(k, lines) for k, lines in b_blocks if k not in note.EDITABLE_KEYS]
    keep_a = [(k, lines) for k, lines in a_blocks if k not in note.EDITABLE_KEYS]
    if keep_b != keep_a:
        problems.append("frontmatter outside tags/type changed")
    for key in note.EDITABLE_KEYS:
        if sum(1 for k, _ in a_blocks if k == key) > 1:
            problems.append(f"duplicate '{key}' key")
    if b.fm_lines is not None and a.fm_lines is None:
        problems.append("frontmatter removed")
    missing = [t for t in b.tags() if t not in a.tags()]
    if missing:
        problems.append(f"tags removed: {missing}")
    if b.type() is not None and a.type() != b.type():
        problems.append(f"type overwritten: {b.type()!r} -> {a.type()!r}")
    return problems


def assert_safe(before: str, after: str, path: str = "") -> None:
    problems = check_change(before, after)
    if problems:
        raise SafetyViolation(f"{path or 'note'}: " + "; ".join(problems))


def ensure_copy_vault(vault: Path) -> Path:
    """Refuse anything but a marked copy outside the repo's fixtures (D-1, D-20)."""
    v = vault.resolve()
    if not v.is_dir():
        raise NotACopyVault(f"{vault} is not a directory")
    if v == FIXTURES_DIR or FIXTURES_DIR in v.parents:
        raise NotACopyVault(f"{vault} is inside the repo's fixtures; the worker only runs on a copy (gardener copy-fixture)")
    if not (v / COPY_MARKER).is_file():
        raise NotACopyVault(f"{vault} has no {COPY_MARKER} marker; make a copy with `gardener copy-fixture <dest>` first")
    return v
