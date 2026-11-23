"""Note anatomy (D-11, D-12): frontmatter lines, body, and the managed Related block.

A note's text is `---\\n<frontmatter lines>\\n---\\n<body>[\\n\\n<managed block>]`. The managed block is the only
thing an agent may append, and it is always at the very end, preceded by exactly two newlines, so stripping it
gives back the body byte for byte.

Frontmatter is edited line by line: only the `tags` and `type` key blocks may change; every other line is
carried over untouched. YAML is parsed for *reading* values only, never re-serialised.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import yaml

RELATED_START = "<!-- gardener:related:start -->"
RELATED_END = "<!-- gardener:related:end -->"
BLOCK_SEP = "\n\n"
EDITABLE_KEYS = ("tags", "type")

_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Note:
    """A parsed note. `fm_lines` is None when the note has no frontmatter."""

    fm_lines: tuple[str, ...] | None
    body: str  # the owner's body: managed block removed (in \n form; see `form`)
    related: tuple[str, ...]  # targets in the managed block, in order ([] if none)
    has_block: bool
    form: tuple[bool, bool] = (False, False)  # (starts with a BOM, CRLF line endings) of the file on disk (D-35)

    @property
    def body_hash(self) -> str:
        """Hash of the body as it is on disk (BOM and \r\n restored), so a line-ending change is a body change."""
        return sha256(_restore(self.body, self.form))

    def frontmatter(self) -> dict[str, Any]:
        return self._fm

    @cached_property
    def _fm(self) -> dict[str, Any]:
        if not self.fm_lines:
            return {}
        try:
            data = yaml.load("\n".join(self.fm_lines), Loader=_Loader)  # noqa: S506 - a SafeLoader
        except yaml.YAMLError:
            return {}
        return data if isinstance(data, dict) else {}

    def frontmatter_problem(self) -> str | None:
        """Why tags/type cannot be read reliably (None = fine). Unreadable means an owner's tags would look absent."""
        if not self.fm_lines:
            return None
        try:
            data = yaml.load("\n".join(self.fm_lines), Loader=_Loader)  # noqa: S506 - a SafeLoader
        except yaml.YAMLError:
            return "frontmatter is not valid YAML"
        if data is None:
            return None
        if not isinstance(data, dict):
            return "frontmatter is not a key: value mapping"
        tags, ntype = data.get("tags"), data.get("type")
        if tags is not None and not isinstance(tags, (str, list)):
            return "tags has an unexpected shape"
        if isinstance(tags, list) and not all(isinstance(t, (str, int, float)) and not isinstance(t, bool) for t in tags):
            return "a tag is not a plain value"
        if ntype is not None and not isinstance(ntype, (str, int, float)):
            return "type has an unexpected shape"
        return None

    def body_links(self) -> set[str]:
        """Wiki-link targets written anywhere in the owner's body."""
        return {m.group(1).strip() for m in re.finditer(r"\[\[([^\]|#]+)", self.body)}

    def tags(self) -> list[str]:
        raw = self.frontmatter().get("tags")
        if raw is None:
            return []
        if isinstance(raw, str):
            return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
        if isinstance(raw, list):
            return [str(t) for t in raw if t is not None]
        return []

    def type(self) -> str | None:
        v = self.frontmatter().get("type")
        return str(v) if v not in (None, "") else None

    def title(self) -> str:
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return ""


Form = tuple[bool, bool]  # (BOM, CRLF)


def file_form(text: str) -> Form | None:
    """(starts with a UTF-8 BOM, uses \r\n) — or None for mixed or bare-\r line endings, which cannot be edited
    without choosing an ending for the new lines (D-35)."""
    bom = text.startswith("\ufeff")
    t = text[1:] if bom else text
    if "\r" not in t:
        return (bom, False)
    rest = t.replace("\r\n", "")
    if "\r" in rest or "\n" in rest:
        return None
    return (bom, True)


def _normalize(text: str, form: Form) -> str:
    t = text[1:] if form[0] else text
    return t.replace("\r\n", "\n") if form[1] else t


def _restore(text: str, form: Form) -> str:
    t = text.replace("\n", "\r\n") if form[1] else text
    return "\ufeff" + t if form[0] else t


def unsupported(text: str) -> str | None:
    """Why the agents must leave this note alone (None = they may edit it). BOM and uniform CRLF notes are edited in
    their own form (D-35); mixed endings and unreadable frontmatter are skipped, never "fixed" (review 2026-11-22)."""
    if file_form(text) is None:
        return "mixed or bare-CR line endings"
    return parse(text).frontmatter_problem()


def split_frontmatter(text: str) -> tuple[tuple[str, ...] | None, str]:
    """Return (frontmatter lines, rest). Frontmatter must open on line 1 with `---` and close with `---`."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 3)
    if end == -1:
        if text.endswith("\n---"):
            end = len(text) - 4
            return tuple(text[4:end].split("\n")) if end > 4 else (), ""
        return None, text
    inner = text[4:end]
    lines = tuple(inner.split("\n")) if inner else ()
    return lines, text[end + 5:]


def strip_block(rest: str) -> tuple[str, tuple[str, ...], bool]:
    """Remove the managed block (and its two-newline separator) from the end of `rest`."""
    if not rest.endswith(RELATED_END + "\n"):
        return rest, (), False
    start = rest.rfind(BLOCK_SEP + RELATED_START)
    if start == -1:
        return rest, (), False
    block = rest[start + len(BLOCK_SEP):]
    targets = tuple(m.group(1) for m in re.finditer(r"^- \[\[([^\]|#]+)\]\]$", block, re.MULTILINE))
    return rest[:start], targets, True


def parse(text: str) -> Note:
    form = file_form(text)
    t = _normalize(text, form) if form is not None else text  # mixed endings: parsed raw (and never edited)
    fm, rest = split_frontmatter(t)
    body, related, has_block = strip_block(rest)
    return Note(fm_lines=fm, body=body, related=related, has_block=has_block, form=form or (False, False))


def _editable(text: str) -> tuple[str, Form]:
    form = file_form(text)
    if form is None:
        raise ValueError("mixed or bare-CR line endings: not editable (D-35)")
    return _normalize(text, form), form


def body_hash(text: str) -> str:
    return parse(text).body_hash


# -- frontmatter key blocks ---------------------------------------------------


def key_blocks(fm_lines: tuple[str, ...]) -> list[tuple[str | None, tuple[str, ...]]]:
    """Group frontmatter lines into (top-level key, lines) blocks. Leading lines before any key get key None."""
    blocks: list[tuple[str | None, list[str]]] = []
    for line in fm_lines:
        m = _KEY_RE.match(line)
        if m and not line[:1].isspace():
            blocks.append((m.group(1), [line]))
        elif not line.strip() or line.startswith("#"):
            # A top-level comment or blank line belongs to no key: it must survive a tags/type rewrite (review S4).
            blocks.append((None, [line]))
        elif blocks:
            blocks[-1][1].append(line)
        else:
            blocks.append((None, [line]))
    return [(k, tuple(v)) for k, v in blocks]


def _scalar(t: str) -> str:
    """`t` as a YAML list item that reads back as exactly `t`: plain when it round-trips, JSON-quoted otherwise
    ("#tag" would be a comment, null/yes/1 would change type). Review 2026-11-22 S3."""
    try:
        if yaml.load(f"- {t}", Loader=_Loader) == [t]:  # noqa: S506 - a SafeLoader
            return t
    except yaml.YAMLError:
        pass
    return json.dumps(t, ensure_ascii=False)


def render_tags(tags: list[str]) -> tuple[str, ...]:
    return ("tags:", *(f"  - {_scalar(t)}" for t in tags))


def set_frontmatter(text: str, *, tags: list[str] | None = None, type_: str | None = None) -> str:
    """Return `text` with the `tags` and/or `type` key blocks replaced (or added). Nothing else changes; the file's
    BOM and line endings are kept (D-35)."""
    text, form = _editable(text)
    fm, rest = split_frontmatter(text)
    blocks = key_blocks(fm) if fm is not None else []
    out: list[tuple[str | None, tuple[str, ...]]] = []
    done: set[str] = set()
    for key, lines in blocks:
        if key == "tags" and tags is not None:
            out.append((key, render_tags(tags)))
            done.add("tags")
        elif key == "type" and type_ is not None:
            out.append((key, (f"type: {type_}",)))
            done.add("type")
        else:
            out.append((key, lines))
    if tags is not None and "tags" not in done:
        out.append(("tags", render_tags(tags)))
    if type_ is not None and "type" not in done:
        out.append(("type", (f"type: {type_}",)))
    new_lines = [line for _, lines in out for line in lines]
    return _restore("---\n" + "\n".join(new_lines) + "\n---\n" + rest, form)


# -- managed Related block ----------------------------------------------------


def render_block(targets: list[str]) -> str:
    items = "\n".join(f"- [[{t}]]" for t in targets)
    return f"{RELATED_START}\n## Related\n\n{items}\n{RELATED_END}\n"


def set_related(text: str, targets: list[str]) -> str:
    """Replace (or append) the managed block. With no targets, the block is removed. BOM and endings kept (D-35)."""
    text, form = _editable(text)
    fm, rest = split_frontmatter(text)
    body, _, _ = strip_block(rest)
    head = "" if fm is None else "---\n" + "\n".join(fm) + "\n---\n"
    if not targets:
        return _restore(head + body, form)
    return _restore(head + body + BLOCK_SEP + render_block(targets), form)
