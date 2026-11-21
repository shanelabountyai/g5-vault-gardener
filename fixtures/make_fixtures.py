"""Write the synthetic fixture vault, arrivals, taxonomy, labeled sample and recorded responses (D-1, D-24).

Everything here is made up: hobby-topic notes with no people, companies or personal content. The recorded
Classifier/Linker responses are hand-written from the ground truth below, with the deliberate mistakes in
CLASSIFIER_MISTAKES and LINKER_MISTAKES, so quality numbers describe these fixtures, not a model.

Run: `uv run python fixtures/make_fixtures.py` (deterministic; a test regenerates into a temp dir and diffs).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

TYPES = ["project", "reference", "idea", "log", "meeting"]
TYPE_FOLDER = {"project": "projects", "reference": "reference", "idea": "ideas", "log": "logs", "meeting": "meetings"}
STATUSES = ["status/active", "status/someday", "status/done"]

# topic tag -> (sentence bank, notes). A note is (slug, type, status or None, title).
TOPICS: dict[str, tuple[list[str], list[tuple[str, str, str | None, str]]]] = {
    "topic/cooking": (
        [
            "Feed the starter at a 1:5:5 ratio when the kitchen is cool.",
            "A covered pot keeps steam in for the first twenty minutes of the bake.",
            "Salt goes in after the autolyse, never before.",
            "Soak dried beans overnight and keep the soaking water for the stew.",
            "A sharp knife at a steady angle is safer than a dull one.",
            "Label every jar with the date it was opened.",
            "Taste for acid at the end; a squeeze of lemon fixes a flat pot.",
            "Weigh flour instead of using cups; the numbers stay repeatable.",
        ],
        [
            ("sourdough-starter-log", "log", None, "Sourdough starter log"),
            ("sourdough-hydration-table", "reference", None, "Sourdough hydration table"),
            ("weeknight-bean-stew", "reference", None, "Weeknight bean stew"),
            ("bread-oven-schedule", "project", "status/active", "Bread oven schedule"),
            ("fermented-hot-sauce", "idea", "status/someday", "Fermented hot sauce"),
            ("knife-sharpening-angles", "reference", None, "Knife sharpening angles"),
            ("pantry-restock-list", "project", "status/done", "Pantry restock list"),
        ],
    ),
    "topic/gardening": (
        [
            "Rotate the tomato bed with beans every second season.",
            "The compost pile should feel warm a hand's depth in.",
            "Start peppers indoors eight weeks before the last frost.",
            "Drip lines lose less water than a sprinkler on a windy day.",
            "A strip of native flowers along the fence brings in pollinators.",
            "Mulch after the soil has warmed, not before.",
            "Plant garlic cloves pointy end up, two knuckles deep.",
            "Write the variety on the plant label in pencil; marker fades.",
        ],
        [
            ("tomato-bed-rotation", "project", "status/active", "Tomato bed rotation"),
            ("compost-temperature-log", "log", None, "Compost temperature log"),
            ("seed-starting-calendar", "reference", None, "Seed starting calendar"),
            ("drip-irrigation-plan", "project", "status/someday", "Drip irrigation plan"),
            ("pollinator-strip-idea", "idea", "status/someday", "Pollinator strip"),
            ("frost-dates-reference", "reference", None, "Frost dates"),
            ("garlic-planting-log", "log", None, "Garlic planting log"),
        ],
    ),
    "topic/programming": (
        [
            "Keep the command-line parser thin and push logic into plain functions.",
            "A lockfile makes a fresh install match the last green build.",
            "Write-ahead logging lets readers keep reading while one writer commits.",
            "Anchor a regular expression when you mean the whole line.",
            "A fixture should build exactly the state a test needs and nothing more.",
            "Static pages are cheap to host and hard to break.",
            "Rename in one commit, change behaviour in the next.",
            "Run the type checker in CI so it never drifts out of date.",
        ],
        [
            ("cli-todo-tool", "project", "status/active", "Command-line to-do tool"),
            ("python-packaging-notes", "reference", None, "Python packaging notes"),
            ("sqlite-wal-notes", "reference", None, "SQLite WAL notes"),
            ("regex-cheatsheet", "reference", None, "Regex cheatsheet"),
            ("test-fixture-patterns", "reference", None, "Test fixture patterns"),
            ("static-site-idea", "idea", "status/someday", "Static site for the notes"),
            ("refactor-log-cli", "log", None, "Refactor log for the CLI"),
        ],
    ),
    "topic/astronomy": (
        [
            "Collimate the reflector after every car trip.",
            "Start the observing list with the brightest clusters while the sky darkens.",
            "The first-quarter moon shows the most crater detail along the terminator.",
            "A dark site is worth an hour of driving for faint galaxies.",
            "Long exposures need a tracking mount or the stars smear.",
            "A wide eyepiece finds the target; a short one shows the detail.",
            "Let the mirror cool for half an hour before judging the seeing.",
            "Red light keeps night vision; white light ruins it for twenty minutes.",
        ],
        [
            ("telescope-collimation", "reference", None, "Telescope collimation"),
            ("messier-observing-list", "project", "status/active", "Messier observing list"),
            ("moon-phase-log", "log", None, "Moon phase log"),
            ("dark-sky-sites", "reference", None, "Dark sky sites"),
            ("astrophotography-idea", "idea", "status/someday", "Astrophotography setup"),
            ("eyepiece-comparison", "reference", None, "Eyepiece comparison"),
        ],
    ),
    "topic/home-repair": (
        [
            "Turn off the breaker before opening a ceiling fixture.",
            "A drop of light oil on the hinge pin stops most squeaks.",
            "Silicone caulk suits wet areas; acrylic takes paint.",
            "Clear the gutters after the last leaves fall.",
            "Use a stud for heavy shelves; anchors are for light loads.",
            "Measure twice and mark the cut line on the waste side.",
            "Keep the receipt and the manual in the same folder as the part.",
            "A level placed on the frame tells you more than the wall does.",
        ],
        [
            ("bathroom-fan-replacement", "project", "status/done", "Bathroom fan replacement"),
            ("door-hinge-squeak", "log", None, "Door hinge squeak"),
            ("caulk-types-reference", "reference", None, "Caulk types"),
            ("gutter-cleaning-schedule", "project", "status/active", "Gutter cleaning schedule"),
            ("shelf-anchor-guide", "reference", None, "Shelf anchor guide"),
            ("workbench-build-idea", "idea", "status/someday", "Workbench build"),
        ],
    ),
    "topic/reading": (
        [
            "Write one sentence about the book the day you finish it.",
            "Highlights are only useful if you review them within a week.",
            "Keep a short list; a long list never gets read.",
            "Mark the passage that changed your mind, not the one that agreed with you.",
            "A question per chapter makes a book club discussion easier.",
            "Alternate long books with short ones to keep momentum.",
            "Note the page number with every quote.",
            "Return library books with a slip noting what to reread.",
        ],
        [
            ("reading-list-autumn", "project", "status/active", "Autumn reading list"),
            ("notes-the-patient-orchard", "reference", None, "Notes: The Patient Orchard (fictional title)"),
            ("notes-maps-of-small-rivers", "reference", None, "Notes: Maps of Small Rivers (fictional title)"),
            ("highlight-review-method", "reference", None, "Highlight review method"),
            ("book-club-question-bank", "idea", "status/someday", "Book club question bank"),
            ("reading-log-october", "log", None, "Reading log, October"),
        ],
    ),
    "topic/fitness": (
        [
            "Most runs should feel easy enough to hold a conversation.",
            "Stretch after the run, not before it.",
            "Add no more than a tenth to weekly distance.",
            "Rotate two pairs of shoes so the foam recovers.",
            "Hill repeats build strength without a gym.",
            "Squats, push-ups and rows cover the basics.",
            "Sleep is the cheapest recovery tool.",
            "Write down how the run felt, not just the pace.",
        ],
        [
            ("10k-training-plan", "project", "status/active", "10k training plan"),
            ("stretching-routine", "reference", None, "Stretching routine"),
            ("run-log-week-41", "log", None, "Run log, week 41"),
            ("shoe-rotation", "reference", None, "Shoe rotation"),
            ("hill-repeats-idea", "idea", "status/someday", "Hill repeats"),
            ("strength-basics", "reference", None, "Strength basics"),
        ],
    ),
    "topic/cycling": (
        [
            "Clean and lube the chain every few hundred kilometres.",
            "The quiet route adds ten minutes and removes two busy junctions.",
            "Tubeless tyres seal small punctures on their own.",
            "Check brake pads for wear before a long descent.",
            "Pack the heaviest gear low and central on the bike.",
            "Saddle height is right when the knee is slightly bent at the bottom.",
            "Carry a spare tube even with tubeless tyres.",
            "Lights on in the rain, even at midday.",
        ],
        [
            ("bike-chain-maintenance", "reference", None, "Bike chain maintenance"),
            ("commute-route-options", "reference", None, "Commute route options"),
            ("tubeless-conversion", "project", "status/done", "Tubeless conversion"),
            ("ride-log-october", "log", None, "Ride log, October"),
            ("bikepacking-trip-idea", "idea", "status/someday", "Bikepacking trip"),
            ("brake-pad-wear-check", "reference", None, "Brake pad wear check"),
        ],
    ),
    "topic/networking": (
        [
            "Draw the network map before changing anything.",
            "Mesh nodes work best with a clear line between them.",
            "Update router firmware on a quiet evening, never before a trip.",
            "Filtering at the resolver covers every device at once.",
            "Put the smart plugs on their own network segment.",
            "Back up the configuration before every change.",
            "A wired backhaul beats any wireless one.",
            "Write down the admin address somewhere that is not on the network.",
        ],
        [
            ("home-network-map", "reference", None, "Home network map"),
            ("wifi-mesh-upgrade", "project", "status/active", "Wi-Fi mesh upgrade"),
            ("router-firmware-log", "log", None, "Router firmware log"),
            ("dns-filtering-idea", "idea", "status/someday", "DNS filtering"),
            ("vlan-notes", "reference", None, "VLAN notes"),
            ("backup-nas-plan", "project", "status/someday", "Backup NAS plan"),
        ],
    ),
}

# Inbox items already in the vault (slug, topic, type, status, title).
INBOX: list[tuple[str, str, str, str | None, str]] = [
    ("quick-note-proofing-box", "topic/cooking", "idea", "status/someday", "Proofing box from a cooler?"),
    ("clipped-mulch-tips", "topic/gardening", "reference", None, "Clipped: mulch tips"),
    ("star-party-checklist", "topic/astronomy", "project", "status/active", "Star party checklist"),
    ("todo-fix-leaky-faucet", "topic/home-repair", "project", "status/active", "Fix the leaky faucet"),
    ("pacing-notes", "topic/fitness", "reference", None, "Pacing notes"),
    ("router-reboot-again", "topic/networking", "log", None, "Router rebooted again"),
]

# Inbox items that arrive during the simulated day: (tick, slug, topic, type, status, title).
ARRIVALS: list[tuple[int, str, str, str, str | None, str]] = [
    (5, "pizza-dough-test", "topic/cooking", "log", None, "Pizza dough test"),
    (18, "aphids-on-the-kale", "topic/gardening", "log", None, "Aphids on the kale"),
    (33, "typing-tip-protocols", "topic/programming", "reference", None, "Typing tip: protocols"),
    (47, "meteor-shower-dates", "topic/astronomy", "reference", None, "Meteor shower dates"),
    (62, "saddle-height-fix", "topic/cycling", "log", None, "Saddle height fix"),
    (80, "novel-recommendation", "topic/reading", "idea", "status/someday", "A novel to try (fictional title)"),
]
# The owner edits these bodies between ticks (an appended line), so the Watcher sees a changed note.
USER_EDITS: list[tuple[int, str, str]] = [
    (25, "logs/sourdough-starter-log.md", "\n2026-11-21: Starter doubled in five hours.\n"),
    (55, "projects/tomato-bed-rotation.md", "\nNext season: beans in the east bed.\n"),
    (70, "projects/cli-todo-tool.md", "\nAdd a --due flag.\n"),
]

CLASSIFIER_MISTAKES: dict[str, Any] = {
    "projects/bread-oven-schedule.md": {"drop": "status/active"},
    "projects/messier-observing-list.md": {"drop": "status/active"},
    "ideas/hill-repeats-idea.md": {"drop": "status/someday"},
    "reference/sqlite-wal-notes.md": {"add": "topic/networking"},
    "reference/commute-route-options.md": {"add": "topic/fitness"},
    "reference/sourdough-hydration-table.md": {"add": "topic/baking"},  # not in the taxonomy -> rejected
    "logs/moon-phase-log.md": {"type": "reference"},
    "inbox/router-reboot-again.md": {"malformed": "Sorry, I can't tag this note right now."},
}
LINKER_MISTAKES: dict[str, Any] = {
    "reference/regex-cheatsheet.md": {"replace_last": "caulk-types-reference"},
    "logs/ride-log-october.md": {"replace_last": "run-log-week-41"},
    "ideas/dns-filtering-idea.md": {"add": "pi-hole-setup"},  # does not exist -> rejected
}

LABELED_SAMPLE = [
    "logs/sourdough-starter-log.md", "reference/sourdough-hydration-table.md", "projects/bread-oven-schedule.md",
    "projects/tomato-bed-rotation.md", "reference/seed-starting-calendar.md",
    "reference/sqlite-wal-notes.md", "reference/regex-cheatsheet.md", "ideas/static-site-idea.md",
    "projects/messier-observing-list.md", "logs/moon-phase-log.md",
    "reference/caulk-types-reference.md", "projects/gutter-cleaning-schedule.md",
    "reference/highlight-review-method.md", "ideas/hill-repeats-idea.md", "reference/stretching-routine.md",
    "reference/commute-route-options.md", "logs/ride-log-october.md",
    "ideas/dns-filtering-idea.md", "inbox/clipped-mulch-tips.md", "inbox/todo-fix-leaky-faucet.md",
]


def frontmatter_style(i: int, ntype: str, topic: str, folder: str) -> list[str] | None:
    """Pre-existing frontmatter, varied by index. Never wrong: whatever the owner wrote is treated as correct."""
    created = f"created: 2026-{9 + i % 2:02d}-{1 + i % 28:02d}"
    if folder == "inbox":
        return None if i % 2 == 0 else [created]
    style = i % 4
    if style == 0:
        return None
    if style == 1:
        return [created, f"tags: [{topic}]"]
    if style == 2:
        return [created, "aliases: []", f"type: {ntype}"]
    return [created, "tags:", "  - pinned"]


def body_for(i: int, title: str, ntype: str, bank: list[str]) -> str:
    s = [bank[(i + k) % len(bank)] for k in (0, 3, 5, 6)]
    lines = [f"# {title}", "", s[0], ""]
    if ntype == "log":
        lines += [f"2026-10-{10 + i % 18:02d}: {s[1]}", f"2026-10-{11 + i % 17:02d}: {s[2]}", ""]
    elif ntype == "project":
        lines += ["Next steps:", "", f"- [ ] {s[1]}", f"- [ ] {s[2]}", ""]
    else:
        lines += [f"- {s[1]}", f"- {s[2]}", ""]
    lines += [s[3]]
    return "\n".join(lines) + "\n"


def build() -> dict[str, Any]:
    notes: dict[str, dict[str, Any]] = {}  # path -> spec
    i = 0
    for topic, (bank, specs) in TOPICS.items():
        for slug, ntype, status, title in specs:
            folder = TYPE_FOLDER[ntype]
            path = f"{folder}/{slug}.md"
            notes[path] = {"slug": slug, "topic": topic, "type": ntype, "status": status, "title": title, "folder": folder,
                           "fm": frontmatter_style(i, ntype, topic, folder), "body": body_for(i, title, ntype, bank), "arrival": None}
            i += 1
    for slug, topic, ntype, status, title in INBOX:
        bank = TOPICS[topic][0]
        notes[f"inbox/{slug}.md"] = {"slug": slug, "topic": topic, "type": ntype, "status": status, "title": title, "folder": "inbox",
                                     "fm": frontmatter_style(i, ntype, topic, "inbox"), "body": body_for(i, title, ntype, bank), "arrival": None}
        i += 1
    for tick, slug, topic, ntype, status, title in ARRIVALS:
        bank = TOPICS[topic][0]
        notes[f"inbox/{slug}.md"] = {"slug": slug, "topic": topic, "type": ntype, "status": status, "title": title, "folder": "inbox",
                                     "fm": None, "body": body_for(i, title, ntype, bank), "arrival": tick}
        i += 1
    # The owner's own Related section in one note body (must never be touched).
    notes["logs/sourdough-starter-log.md"]["body"] += "\n## Related\n\n- [[weeknight-bean-stew]]\n"
    return notes


def truth_tags(spec: dict[str, Any]) -> list[str]:
    return [spec["topic"]] + ([spec["status"]] if spec["status"] else [])


def owner_tags(spec: dict[str, Any]) -> list[str]:
    fm = spec["fm"] or []
    if "  - pinned" in fm:
        return ["pinned"]
    if any(line.startswith("tags: [") for line in fm):
        return [spec["topic"]]
    return []


def truth_related(path: str, notes: dict[str, dict[str, Any]]) -> list[str]:
    spec = notes[path]
    return [s["slug"] for p, s in notes.items() if p != path and s["topic"] == spec["topic"] and s["arrival"] is None]


def recorded_related(path: str, notes: dict[str, dict[str, Any]]) -> list[str]:
    """The next three notes of the same topic in vault order (cyclic), then the designed mistakes."""
    spec = notes[path]
    peers = [p for p, s in notes.items() if s["topic"] == spec["topic"] and s["arrival"] is None and s["folder"] != "inbox"]
    if path in peers:
        k = peers.index(path)
        picks = [notes[peers[(k + j) % len(peers)]]["slug"] for j in (1, 2, 3)]
    else:
        picks = [notes[p]["slug"] for p in peers[:3]]
    m = LINKER_MISTAKES.get(path, {})
    if "replace_last" in m:
        picks[-1] = m["replace_last"]
    if "add" in m:
        picks.append(m["add"])
    return picks


def render(spec: dict[str, Any]) -> str:
    fm = spec["fm"]
    head = "" if fm is None else "---\n" + "\n".join(fm) + "\n---\n"
    return head + spec["body"]


def write_all(out: Path) -> None:
    notes = build()
    vault, arrivals = out / "vault", out / "arrivals"
    for d in (vault, arrivals):
        if d.exists():
            shutil.rmtree(d)
    for path, spec in notes.items():
        target = (arrivals / f"{spec['slug']}.md") if spec["arrival"] is not None else (vault / path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(spec), encoding="utf-8")

    schedule = {
        "_about": "Events applied to the copy vault between simulated ticks (D-19): inbox arrivals and owner body edits.",
        "events": sorted(
            [{"tick": s["arrival"], "action": "add", "path": p, "source": f"arrivals/{s['slug']}.md"} for p, s in notes.items() if s["arrival"] is not None]
            + [{"tick": t, "action": "user_edit", "path": p, "append": text} for t, p, text in USER_EDITS],
            key=lambda e: (e["tick"], e["path"]),
        ),
    }
    (out / "arrivals.json").write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")

    taxonomy = {
        "_about": "Synthetic tag taxonomy for the fixture vault (D-6). Tags outside this list are never written.",
        "tags": sorted(TOPICS) + STATUSES,
        "types": TYPES,
        "type_folder": TYPE_FOLDER,
    }
    (out / "taxonomy.json").write_text(json.dumps(taxonomy, indent=2) + "\n", encoding="utf-8")

    labels = {
        "_about": ("Hand-labeled sample (D-1, D-8): the correct tags (owner tags + taxonomy tags), type and related notes for 20 notes. "
                   "Related = every other non-inbox note on the same topic."),
        "notes": {p: {"tags": sorted(set(owner_tags(notes[p]) + truth_tags(notes[p]))), "type": notes[p]["type"],
                      "related": truth_related(p, notes)} for p in LABELED_SAMPLE},
    }
    (out / "labels.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")

    responses: dict[str, Any] = {}
    for path, spec in notes.items():
        m = CLASSIFIER_MISTAKES.get(path, {})
        if "malformed" in m:
            responses[f"classifier:{path}"] = m["malformed"]
        else:
            tags = [t for t in truth_tags(spec) if t != m.get("drop")]
            if "add" in m:
                tags.append(m["add"])
            ntype = m.get("type", spec["type"])
            responses[f"classifier:{path}"] = {"tags": tags, "type": ntype, "folder": TYPE_FOLDER[ntype]}
            responses[f"linker:{path}"] = {"related": recorded_related(path, notes)}
    recorded = {
        "_about": ("HAND-WRITTEN responses in each agent's output shape (D-9), keyed <agent>:<path>. Not a recording of a live model. "
                   "Designed mistakes are listed in fixtures/make_fixtures.py (D-24)."),
        "responses": responses,
    }
    (out / "recorded.json").write_text(json.dumps(recorded, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_all(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE)
    print("fixtures written")
