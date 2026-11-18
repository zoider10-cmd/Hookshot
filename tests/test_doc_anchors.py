"""Anchors from code to the docs that hold its rules (`// doc: docs/design.md#4-the-lessons-from-mkw-as-rules-here`): every
anchor in our own code (host/, gpu/, nx2/, scripts/, builder/; not eden, sirit or third_party) names a file under docs/
that exists and, after #, a heading in it (GitHub's anchor for it). The functions that enforce a documented rule keep
theirs: an agent reading one sees where its rule is written before it "simplifies" a capture or a wait away.

    python -I -B tests/test_doc_anchors.py
"""
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DIRS = ("host", "gpu", "nx2", "scripts", "builder")
SKIP = {"eden", "sirit", "third_party", "__pycache__", "node_modules", "bin", "obj"}
EXTS = {".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".cs", ".sh", ".comp", ".frag", ".vert", ".glsl"}
ANCHOR = re.compile(r"(?://|#)\s*doc: (\S+?)(?:#([^\s)]+))?(?=[\s)]|$)")

# (the functions behind design.md's rules, each with the anchor kept just above it: file, the line the function's comment
# or definition starts with, the anchor's target)
RULES = "docs/design.md#4-the-lessons-from-mkw-as-rules-here"
REQUIRED = [
    ("gpu/vk/vk_replay.cpp", "/// A submit on the replay thread: replayed as far", RULES),
    ("gpu/vk/vk_memory.cpp", "// (and the game's pools up to RX_VK_CAPTURE_POOL_MB", RULES),
    ("gpu/vk/vk_replay.cpp", "void register_texture_queued(", RULES),
    ("gpu/vk/vk_replay.cpp", "// (the GPU's time as the game measures it", RULES),
    ("gpu/vk/vk_draw.cpp", "/// A clear after draws of the open pass", RULES),
    ("gpu/vk/vk_draw.cpp", "/// A draw that samples a target this pass already wrote", RULES),
    ("nx2/build.py", "def rss_mb(proc):", "docs/compiler-memory-accounting.md"),
]


def slug(heading):
    """GitHub's anchor for a Markdown heading: lower case, the punctuation left out (not - or _), spaces as -"""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())   # (`code` and **bold** lose their marks; _ is kept)
    return text.replace(" ", "-")


def anchors_of(doc):
    """Every heading's anchor in a Markdown file (a repeated one gets -1, -2 ...); fenced code is not headings"""
    seen, out, fence = {}, set(), False
    for line in doc.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else "%s-%d" % (s, n))
    return out


def sources():
    for top in DIRS:
        for folder, dirs, files in os.walk(ROOT / top):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            for f in files:
                if os.path.splitext(f)[1] in EXTS:
                    yield Path(folder) / f


def check(anchors):
    """anchors: (where, target file, fragment or None); the ones that do not resolve, as messages"""
    bad, cache = [], {}
    for where, target, frag in anchors:
        doc = ROOT / target
        if not target.startswith("docs/") or not doc.is_file():
            bad.append("%s: %s is not a file under docs/" % (where, target))
            continue
        if frag is not None:
            if target not in cache:
                cache[target] = anchors_of(doc)
            if frag not in cache[target]:
                bad.append("%s: %s has no heading #%s" % (where, target, frag))
    return bad


def main():
    # the anchor rule itself
    assert slug("4. The lessons from MKW, as rules here") == "4-the-lessons-from-mkw-as-rules-here"
    assert slug("Graphics pipeline `state` (A/B)") == "graphics-pipeline-state-ab"
    assert slug("rx_vk_occ_queries and RX_VK_PACE") == "rx_vk_occ_queries-and-rx_vk_pace"
    assert ANCHOR.search("// doc: docs/a.md#b-c (rule 1)").groups() == ("docs/a.md", "b-c")
    assert ANCHOR.search("# doc: docs/a.md").groups() == ("docs/a.md", None)
    assert check([("x", "docs/design.md", "no-such-heading")]) and check([("x", "docs/none.md", None)])
    assert not check([("x", "docs/design.md", "4-the-lessons-from-mkw-as-rules-here")])

    found = []
    for f in sources():
        rel = f.relative_to(ROOT).as_posix()
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in ANCHOR.finditer(line):
                found.append(("%s:%d" % (rel, n), m.group(1), m.group(2)))
    bad = check(found)
    for path, marker, target in REQUIRED:
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        at = [i for i, l in enumerate(lines) if l.lstrip().startswith(marker)]
        if len(at) != 1:
            bad.append("%s: %r is not there once (found %d): the anchor's place moved, update REQUIRED" % (path, marker, len(at)))
        elif "doc: " + target not in lines[at[0] - 1]:
            bad.append("%s:%d: no doc: %s just above %r" % (path, at[0], target, marker))
    if bad:
        sys.exit("doc anchors:\n  " + "\n  ".join(bad))
    print("doc anchors: %d, each resolves; the %d rules' functions keep theirs" % (len(found), len(REQUIRED)))


if __name__ == "__main__":
    main()
