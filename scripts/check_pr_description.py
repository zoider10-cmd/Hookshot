"""Check a pull request's description against the template (.forgejo/pull_request_template.md, CONTRIBUTING.md
"Commits and pull requests"). Each problem fails it; none of the template's <...> stand-ins may be left.

  - the status line, the first line: "**Type:** fix · **Risk:** low · **Tested on:** <OS, GPU> · **Needs:** <OS, GPU,
    or none>", the type one of the title types, the risk low, medium or high;
  - Why, filled in;
  - How to reproduce, for a fix (the title's type, or the status line's when there is no title): Seen on, Steps,
    Expected and Actual, each filled in. Another PR may leave it out; kept, it is filled in;
  - What changed: a short summary paragraph first, then the details (a bullet per area);
  - Measurements: either one line saying why there is nothing to measure, or a "Verdict:" line, the Hardware, Scene,
    Method and How to reproduce lines and a table whose columns name what was run with its commit ("Before: main @
    <hash>", "After: this PR @ <hash>", variants such as "After, RX_VK_X=0: this PR @ <hash>"; a Δ column is free),
    with a row of values. A before column other than main, or an after column other than this PR, needs a
    "Baseline:" line;
  - ### Flags and settings under Measurements: "None", or a summary line and a row per flag with every cell filled in
    (its before and after value, effect, where it helps, the recommendation);
  - Testing: Tested, Not tested and Must be tested, each filled in; Must be tested is "None", or an item per thing,
    each "<where>: <how>, expecting <the result>", saying who runs it: the Test Farm ("@Beanstalk ...") or by hand;
  - Risks, filled in, with its Compatibility part;
  - Issues may be left out; kept, no bare "Fixes #";
  - the checklist: every box of "Everyone" there and ticked. "When it applies" keeps only the boxes that apply (or is
    left out when none does), and every box kept is ticked.

Warnings, which do not fail it: an RX_*, HOS_* or HOOKSHOT_* name the diff adds that Flags and settings doesn't list,
a change to the menu's code while it says None, a PR rebased onto a newer main than the one measured, a box marked n/a
(delete it instead), a box the diff suggests that isn't there, the status line's type other than the title's, its
Needs disagreeing with Must be tested, and Not tested or Must be tested naming something the Measurements say was
measured.

A pull request still in work in progress (a title starting with WIP: or [WIP], Forgejo's draft mark, or the API's
draft) is not checked: it passes with a notice listing what is left. The check applies once it is marked ready for
review; forge.py pr ready runs the same check before it takes the WIP: off (--force goes on anyway).

    python -I scripts/check_pr_description.py --file body.md [--title T] [--diff pr.diff] [--wip]
    python -I scripts/check_pr_description.py --pr 12 [--repo MagicBeanDev/Hookshot] [--server https://git.magicbean.dev]

--pr reads the pull request, its title and its diff from the Forgejo API, with the token in FORGEJO_TOKEN or
GITHUB_TOKEN when one is set (a public repository needs none). Exit status 0 when it passes, 1 with the problems listed
when it does not. Standard library only; .forgejo/workflows/pr-description.yml runs it on every pull request.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / ".forgejo" / "pull_request_template.md"
# Forgejo's default WORK_IN_PROGRESS_PREFIXES ([repository.pull-request] in app.ini), matched at the start of the title
# whatever the case. The first is the one forge.py adds.
WIP_PREFIXES = ("WIP:", "[WIP]")
NEEDS_MEASUREMENTS = "needs measurements"   # (the label of a PR sent back to WIP for its measurements)
TYPES = ("feat", "fix", "perf", "refactor", "docs", "test", "ci", "build", "chore", "revert")   # (forge.py's TITLE_TYPES)
# A pull request is squash-merged, so its title is the commit on main: a Conventional Commit (the CI workflow's title
# job and MagicBeanDev/Tooling's forge.py pr create check it)
TITLE = re.compile(r"^(%s)(\([\w./-]+\))?!?: \S" % "|".join(TYPES))
# The files the game runs, by path prefix: forge.py (MagicBeanDev/Tooling, which loads this file as Hookshot's rules)
# opens a pull request that changes one only once it has run in the game (pr create --tested-in-game), unless --force
GAME_PATHS = ("gpu/", "host/", "nx2/", "assets/", "third_party/")
RISKS = ("low", "medium", "high")
STATUS = ("Type", "Risk", "Tested on", "Needs")
# The sections a description fills in; Issues may be left out, How to reproduce is for a fix
REQUIRED = ("Why", "What changed", "Measurements", "Testing", "Risks")
REPRODUCE = "How to reproduce"
REPRODUCE_PARTS = ("Seen on", "Settings and switches", "Steps", "Expected", "Actual")
REPRODUCE_NEEDED = ("Seen on", "Steps", "Expected", "Actual")
FLAGS = "Flags and settings"
FLAG_COLUMNS = ("Before this PR", "After this PR", "Effect", "Recommendation")
MEASURE_LINES = ("Hardware", "Scene", "Method", "How to reproduce")
TESTING_PARTS = ("Tested", "Not tested", "Must be tested")
MUST = "Must be tested"
RISK_PARTS = ("What could break", "Turning it off", "Compatibility")
EVERYONE, APPLIES = "Everyone", "When it applies"
WHO = re.compile(r"@Beanstalk\b|\btest farm\b|\bby hand\b", re.I)   # (who runs a Must be tested item)
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
STAND_IN = re.compile(r"<[^<>\n!]+>")   # (the template's <...> stand-ins, read from the template itself)
# A measurement column: "Before: main @ 7afe6ae1", "After, RX_VK_X=0: this PR @ 992a2420", "After: this PR @ 992a2420,
# RX_VK_X=1"
COLUMN = re.compile(r"^(?P<side>before|after)\b(?P<variant>[^:@]*):\s*(?P<build>[^@]+?)\s*@\s*(?P<hash>[^\s,;()]+)",
                    re.I)
DELTA = re.compile(r"^(Δ|delta|diff|change)\b", re.I)
NONE = re.compile(r"^\W*none\b", re.I)
# Switches the game, the build or a script reads: a quoted name added in the diff (docs/development.md, "Switches for
# testing and debugging"). Menu rows and ini keys are not spotted that surely: a change to the menu's code is a warning.
SWITCH = re.compile(r"[\"'`]((?:RX|HOS|HOOKSHOT)_[A-Z0-9_]+)[\"'`]")
MENU_CODE = ("gpu/vk/vk_menu.cpp",)
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def without_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def sections(body, level="##"):
    """{heading: text} for the headings of that level (the text up to the next heading of that level or higher)"""
    out, name = {}, None
    stop = re.compile(r"^#{1,%d} " % len(level))
    for line in body.splitlines():
        m = re.match(r"^%s (.+?)\s*#*\s*$" % level, line)
        if m:
            name = m.group(1).strip()
            out[name] = ""
        elif name is not None and stop.match(line):
            name = None
        elif name is not None:
            out[name] += line + "\n"
    return out


def before_subsections(text):
    """text up to its first ### heading"""
    return re.split(r"^### ", text, maxsplit=1, flags=re.M)[0]


def boxes(text):
    """[(ticked, the item's text)] for the task list items in text"""
    return [(m.group(1).lower() == "x", m.group(2).strip()) for m in re.finditer(r"^\s*[-*] \[([ xX])\] (.+)$", text, re.M)]


def key(item):
    """an item's first words, lower case and without marks: the same item when someone ticks it, reflows it or adds a note"""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", item.lower()).split()[:4])


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def without_code(text):
    return re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)


def tables(text):
    """[(header cells, [row cells])] for the Markdown tables in text, outside code blocks"""
    lines = [ln.strip() for ln in without_code(text).splitlines()]
    out = []
    for i, ln in enumerate(lines[:-1]):
        if ln.startswith("|") and re.match(r"^\|[\s:|-]+$", lines[i + 1]) and "-" in lines[i + 1]:
            rows = []
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                rows.append(cells(row))
            out.append((cells(ln), rows))
    return out


def checklist(body):
    """{### heading: text} under ## Checklist"""
    return sections(sections(body).get("Checklist", ""), "###")


def everyone(body):
    """the text of ### Everyone under ## Checklist, None when there is none"""
    return checklist(body).get(EVERYONE)


def norm(text):
    return " ".join(text.split()).lower()


def plain(text):
    """text without Markdown's bold and italic marks"""
    return re.sub(r"\*{1,2}|__", "", text)


def parts(text, names):
    """{part: its text} for "**Name:** ..." (or "Name: ...", or a "### Name" heading) parts of a section"""
    pattern = re.compile(r"^(?:#{3,4}\s+)?[*_]*(%s)[*_]*\s*(?::[*_]*\s*(.*)|$)" % "|".join(
        re.escape(n) for n in sorted(names, key=len, reverse=True)), re.I)
    out, name = {}, None
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if m:
            name = next(n for n in names if n.lower() == m.group(1).lower())
            out[name] = (m.group(2) or "") + "\n"
        elif name:
            out[name] += line + "\n"
    return out


def testing_parts(text):
    return parts(text, TESTING_PARTS)


def items(text):
    """A list's items: each top-level bullet with the lines under it, or each line when there are no bullets"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not any(re.match(r"^ ?[-*] ", ln) for ln in lines):
        return [ln.strip() for ln in lines]
    out = []
    for ln in lines:
        if re.match(r"^ ?[-*] ", ln) or not out:
            out.append(re.sub(r"^\s*[-*] ", "", ln).strip())
        else:
            out[-1] += " " + ln.strip()
    return out


tester_lines = items   # (the earlier name)


# --- the status line --------------------------------------------------------------------------------------------

def status(body):
    """{Type, Risk, Tested on, Needs: value} from the description's first line, None when it is no status line"""
    first = next((ln for ln in body.splitlines() if ln.strip()), "")
    if first.startswith("#"):
        return None
    fields = {}
    for piece in re.split(r"\s+[·|•]\s+|\s+-\s+(?=[*_]*(?:risk|tested on|needs)\b)", plain(first)):
        m = re.match(r"^\s*(type|risk|tested on|needs)\s*:\s*(.*?)\s*$", piece, re.I)
        if m:
            fields[next(n for n in STATUS if n.lower() == m.group(1).lower())] = m.group(2)
    return fields if len(fields) >= 2 else None


def title_type(title):
    m = re.match(r"^([a-z]+)(\([^)]*\))?!?:", strip_wip(title or ""))
    return m.group(1) if m else None


def status_problems(fields):
    if fields is None:
        return ["no status line: the description's first line is '**Type:** <type> · **Risk:** <low / medium / high> · "
                "**Tested on:** <OS, GPU> · **Needs:** <OS, GPU, or none>'"]
    out = ["the status line has no '%s:'" % n for n in STATUS if n not in fields]
    out += ["the status line's '%s:' is empty" % n for n in STATUS if n in fields and not fields[n].strip()]
    kind, risk = fields.get("Type", "").strip().lower(), fields.get("Risk", "").strip().lower()
    if kind and kind not in TYPES:
        out.append("the status line's type '%s' is not a title type: one of %s" % (kind, ", ".join(TYPES)))
    if risk and risk not in RISKS:
        out.append("the status line's risk '%s': write low, medium or high" % risk)
    return out


# --- What changed, How to reproduce, Risks, Issues --------------------------------------------------------------

def what_changed_problems(text):
    blocks = [b for b in re.split(r"\n\s*\n", without_code(text).strip()) if b.strip()]
    if not blocks:
        return []
    first = blocks[0].splitlines()
    if BULLET.match(first[0]) or first[0].lstrip().startswith(("|", "#")):
        return ["## What changed starts with the details: put a short plain summary (two or three sentences) first"]
    if len(blocks) < 2 and not any(BULLET.match(ln) for ln in first[1:]):
        return ["## What changed has a summary and no details: add a bullet per area, naming the files and functions"]
    return []


def reproduce_problems(text):
    found = parts(text, REPRODUCE_PARTS)
    out = []
    for name in REPRODUCE_NEEDED:
        if name not in found:
            out.append("## How to reproduce has no '%s:' (Seen on, Steps, Expected, Actual)" % name)
        elif not found[name].strip():
            out.append("## How to reproduce's '%s:' is empty" % name)
    return out


def risks_problems(text):
    found = parts(text, RISK_PARTS)
    if "Compatibility" not in found:
        return ["## Risks has no 'Compatibility:': what a player notices after updating (saves, hookshot_options.ini, "
                "the shader and pipeline caches, the vk ABI, the builder's tools), or 'Nothing changes'"]
    if not found["Compatibility"].strip():
        return ["## Risks' 'Compatibility:' is empty: write what changes for a player after updating, or 'Nothing "
                "changes'"]
    label = re.compile(r"^(?:#{3,4}\s+)?[*_]*compatibility\b", re.I)
    rest, inside = [], False
    for line in text.splitlines():   # (everything but the Compatibility part)
        if label.match(line.strip()):
            inside = True
        elif any(re.match(r"^(?:#{3,4}\s+)?[*_]*%s\b" % n, line.strip(), re.I) for n in RISK_PARTS[:2]):
            inside = False
        if not inside:
            rest.append(re.sub(r"^[*_]*(%s)[*_]*:?[*_]*" % "|".join(RISK_PARTS[:2]), "", line.strip(), flags=re.I))
    if not "".join(rest).strip():
        return ["## Risks says nothing on what could break: name it and where, and how to turn it off or revert it"]
    return []


def issues_problems(text):
    return ["## Issues: '%s' names no issue: write its number, or delete the section when there is none" % ln.strip()
            for ln in text.splitlines() if re.match(r"^\W*(fixes|closes|see)\s+#(?!\d)", ln, re.I)]


# --- Measurements -----------------------------------------------------------------------------------------------

def column(cell):
    """{side, variant, build, hash} of a measurement column, or None when it names no commit"""
    m = COLUMN.match(plain(cell).strip())
    if not m:
        return None
    return {"side": m.group("side").lower(), "variant": m.group("variant").strip(" ,"),
            "build": m.group("build").strip(), "hash": m.group("hash")}


def line_value(text, name):
    """the text after "Name:" on its own line (bold or not), None when there is no such line"""
    m = re.search(r"^[^\w\n]*%s[ \t]*[*_]*:[*_]*[ \t]*(.*)$" % re.escape(name), text, re.M | re.I)
    return m.group(1).strip() if m else None


def measurement_columns(text):
    """[(header index, column)] for the first table's value columns that name a commit"""
    found = tables(text)
    if not found:
        return []
    return [(i, c) for i, c in ((i, column(h)) for i, h in enumerate(found[0][0]) if i) if c]


def measurement_problems(text):
    """One line saying why there is nothing to measure, or the verdict, the setup and a table of named commits"""
    found = tables(text)
    lines = [ln for ln in without_code(text).splitlines() if ln.strip()]
    if not found:
        if len(lines) == 1:
            return []
        return ["## Measurements has no table: the verdict, the setup and | | Before: main @ <hash> | After: this PR @ "
                "<hash> |, or a single line saying why there is nothing to measure"]
    out = []
    verdict = line_value(text, "Verdict")
    if verdict is None:
        out.append("## Measurements has no 'Verdict:' line: start with whether it helped, by how much, and whether it "
                   "passed")
    elif not verdict:
        out.append("## Measurements' 'Verdict:' is empty: say whether it helped, by how much, and whether it passed")
    for name in MEASURE_LINES:
        if not line_value(text, name):
            out.append("## Measurements has no '%s:' line%s" % (name, {
                "Hardware": " (OS, GPU, driver, CPU, RAM)", "Scene": " (the area; the settings)",
                "Method": " (what was measured, from where, how many runs, the median)",
                "How to reproduce": " (the spot, the settings, the commands)"}[name]))
    header, rows = found[0]
    values = [i for i, c in enumerate(header) if i and c and not DELTA.match(plain(c))]
    cols = []
    for i in values:
        name, c = header[i], column(header[i])
        if c is None:
            out.append("## Measurements' column '%s' names no commit: 'Before: main @ <hash>', 'After: this PR @ <hash>' "
                       "(a variant: 'After, RX_VK_X=0: this PR @ <hash>')" % name)
        elif not COMMIT.match(c["hash"]):
            out.append("## Measurements' column '%s': '%s' is not a commit (7 to 40 hex characters)" % (name, c["hash"]))
        elif c["build"].lower().startswith("this pr") and c["build"].lower() != "this pr":
            out.append("## Measurements' column '%s': write this PR's build as 'this PR @ <hash>', the variant before "
                       "the colon ('After, RX_VK_X=1: this PR @ <hash>') or after the hash" % name)
        else:
            cols.append(c)
    sides = {c["side"] for c in cols}
    if not out and sides != {"before", "after"}:
        out.append("## Measurements' table needs a 'Before: main @ <hash>' and an 'After: this PR @ <hash>' column")
    if cols and any((c["side"] == "before" and c["build"].lower() != "main")
                    or (c["side"] == "after" and c["build"].lower() != "this pr") for c in cols):
        if not line_value(text, "Baseline"):
            out.append("## Measurements compares something other than main against this PR: add a 'Baseline:' line "
                       "saying what the before column is and why main against this PR wasn't the comparison")
    if not any(r and r[0] and all(i < len(r) and r[i] for i in values) for r in rows):
        out.append("## Measurements' table has no row with a value in each column")
    return out


def flags_problems(text, switches):
    """(problems, warnings) for ### Flags and settings"""
    body = text.strip()
    found = [(h, rows) for h, rows in tables(body) if h and plain(h[0]).lower() == "flag"]
    out, warn = [], []
    if not found:
        if not NONE.match(body):
            out.append("### Flags and settings has neither 'None' nor a table with a row per flag")
        warn += ["the diff adds %s, which ### Flags and settings does not list" % s for s in switches]
        return out, warn
    first = next((ln for ln in body.splitlines() if ln.strip()), "")
    if first.startswith("|"):
        out.append("### Flags and settings starts with the table: put a one-line summary first (what this PR adds or "
                   "changes)")
    header, rows = found[0]
    names = [plain(h).lower() for h in header]
    out += ["### Flags and settings' table has no '%s' column" % c for c in FLAG_COLUMNS if c.lower() not in names]
    rows = [r for r in rows if r and r[0]]
    if not rows:
        out.append("### Flags and settings' table has no row: a row per flag, or 'None' alone")
    for r in rows:
        for i, name in enumerate(header):
            if i and (i >= len(r) or not r[i]):
                out.append("### Flags and settings: '%s' has no '%s' (write '-' when there is nothing)" % (r[0], name))
    warn += ["the diff adds %s, which ### Flags and settings does not list" % s for s in switches if s not in body]
    return out, warn


# --- Testing ----------------------------------------------------------------------------------------------------

def testing_problems(text):
    found, out = testing_parts(text), []
    for name in TESTING_PARTS:
        if name not in found:
            out.append("## Testing has no '%s:' part (Tested, Not tested, Must be tested)" % name)
        elif not found[name].strip():
            out.append("## Testing's '%s:' is empty%s" % (name, ": write None when Tested covers everything"
                                                           if name == MUST else ""))
    must = found.get(MUST, "").strip()
    if must and not NONE.match(must):
        for item in items(must):
            bare = STAND_IN.sub("", item)
            where, _, how = bare.partition(":")
            if not where.strip() or not how.strip() or len(where) > 120 or re.search(r"\bexpect", where, re.I):
                out.append("## Testing's 'Must be tested:' item '%s' says not where: '<OS, GPU, driver, or a Test Farm "
                           "tag>: <the steps>, expecting <the result>'" % item)
            if not re.search(r"\bexpect", bare, re.I):
                out.append("## Testing's 'Must be tested:' item '%s' says no result to expect: '..., expecting <the "
                           "result>'" % item)
            if not WHO.search(bare):
                out.append("## Testing's 'Must be tested:' item '%s' says not who runs it: the Test Farm ('@Beanstalk "
                           "<what to test>' on the PR) or 'by hand' (and what to look at)" % item)
    return out


def farm_items(body):
    """The Must be tested items (Test Farm or not), as (item, for the Test Farm)"""
    found = testing_parts(sections(without_comments((body or "").replace("\r\n", "\n"))).get("Testing", ""))
    must = found.get(MUST, "").strip()
    if not must or NONE.match(must):
        return []
    return [(item, bool(re.search(r"@Beanstalk\b|\btest farm\b", item, re.I))) for item in items(must)
            if not STAND_IN.search(item)]


def measured(text):
    """What the Measurements say was measured on: the Hardware line's items and the table's rows"""
    things = []
    hardware = line_value(text, "Hardware")
    if hardware:
        things += [t.strip() for t in re.split(r"[,;]", STAND_IN.sub("", hardware))]
    for header, rows in tables(text)[:1]:
        things += [r[0] for r in rows if r and r[0] and not STAND_IN.search(r[0])]
    return [t for t in things if len(t) >= 3]


# --- the checklist, and the boxes a diff suggests ---------------------------------------------------------------

# The When it applies boxes a diff suggests: (the box's first words, as key() reads them, why, a test on the files and
# switches the diff changes). A hint is a warning, never a failure; pr create keeps these boxes when it fills in the
# template.
HOST_CODE = re.compile(r"^(?!tests/|third_party/).*\.(c|cc|cpp|h|hpp)$")
SHADER = re.compile(r"\.(comp|glsl|vert|frag|mesh|task|geom|tesc|tese)$")
DOCS = re.compile(r"^(docs/.*|README\.md|CONTRIBUTING\.md|AGENTS\.md)$")
HINTS = (
    ("switches documented docs", "it adds %s", lambda files, switches, read: ", ".join(switches)),
    ("mkwvk api version bumped", "it changes gpu/vk/vk_api.h", lambda files, switches, read: "gpu/vk/vk_api.h" in files),
    ("the spir v headers", "it changes the shader %s",
     lambda files, switches, read: ", ".join(sorted(f for f in files if SHADER.search(f)))),
    ("a check under tests", "tests read %s", lambda files, switches, read: ", ".join(sorted(read))),
    ("host code builds on", "it changes host code (%s)",
     lambda files, switches, read: ", ".join(sorted(f for f in files if HOST_CODE.match(f))[:3])),
    ("docs updated", "it changes %s", lambda files, switches, read: ", ".join(sorted(f for f in files if DOCS.match(f))[:3])),
)
NA = re.compile(r"\bn/a\b", re.I)


def read_by_tests(files, root=None):
    """The changed source files a check under tests/ reads by name (the tests cut functions out of the source)"""
    folder = Path(root) if root else TEMPLATE.parents[1] / "tests"
    try:
        texts = [p.read_text(encoding="utf-8", errors="replace") for p in folder.glob("test_*.py")]
    except OSError:
        return set()
    out = set()
    for f in files:
        if f.startswith(("tests/", "docs/")) or f.endswith(".md"):
            continue
        name = f.rsplit("/", 1)[-1]
        if any(f in t or '"%s"' % name in t or "'%s'" % name in t for t in texts):
            out.add(f)
    return out


def suggested_boxes(diff, template=None):
    """[(the When it applies item, why)] for the boxes the diff suggests"""
    switches, files = diff_changes(diff)
    if not files:
        return []
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    listed = [item for _, item in boxes(checklist(without_comments(template)).get(APPLIES, ""))]
    read = read_by_tests(files)
    out = []
    for start, why, test in HINTS:
        found = test(files, switches, read)
        item = next((i for i in listed if key(i).startswith(start)), None)
        if found and item:
            out.append((item, why % found if "%s" in why else why))
    return out


def keep_applicable(body, keep):
    """body with its When it applies list down to the items in keep (none: the heading and a comment)"""
    m = re.search(r"^### %s\n(.*?)(?=^#{1,3} |\Z)" % APPLIES, body, re.S | re.M)
    if not m:
        return body
    wanted = {key(i) for i in keep}
    lines = [ln for ln in m.group(1).splitlines() if not re.match(r"^\s*[-*] \[[ xX]\] ", ln)
             or key(re.sub(r"^\s*[-*] \[[ xX]\] ", "", ln)) in wanted]
    text = "\n".join(lines).strip("\n")
    if not wanted:
        text = ("<!-- Nothing in the diff suggested one when this PR was opened. Add the boxes that apply from the template\n"
                "     (.forgejo/pull_request_template.md), ticked once done. -->")
    return body[:m.start(1)] + "\n" + text + "\n\n" + body[m.end(1):].lstrip("\n")


def without_reproduce(body):
    """body without its How to reproduce section (pr create drops it for anything but a fix)"""
    return re.sub(r"^## %s\n.*?(?=^## )" % REPRODUCE, "", body, flags=re.S | re.M)


def diff_changes(diff):
    """(the switch names the diff adds, the files it changes) for a unified diff; a name only moved is not added"""
    added, removed, files, path = set(), set(), set(), None
    for line in (diff or "").splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            files.add(path)
        elif line.startswith("--- "):
            continue
        elif path and not path.startswith(("docs/", "tests/")) and not path.endswith(".md"):
            if line.startswith("+"):
                added.update(SWITCH.findall(line))
            elif line.startswith("-"):
                removed.update(SWITCH.findall(line))
    return sorted(added - removed), files


def checklist_problems(body, template, diff):
    out, warn = [], []
    lists = checklist(body)
    mine = lists.get(EVERYONE)
    if "Checklist" not in sections(body):
        out.append("no ## Checklist: keep the Everyone list whole, and the When it applies boxes that apply")
    elif mine is None:
        out.append("no ### Everyone checklist under ## Checklist")
    kept = boxes(lists.get(APPLIES, ""))
    for ticked, item in kept:
        if NA.search(item):
            warn.append("When it applies: '%s' says n/a: delete a box that doesn't apply" % item)
        elif not ticked:
            out.append("When it applies, not ticked: %s (a box kept here applies, so it must be done: tick it, or "
                       "delete it if it doesn't apply)" % item)
    have = {key(item) for _, item in kept}
    warn += ["When it applies: the diff suggests '%s' (%s): add it, ticked once done, if it applies" % (item, why)
             for item, why in suggested_boxes(diff, template) if key(item) not in have]
    if mine is not None:
        have = {key(item) for _, item in boxes(mine)}
        out += ["not ticked: " + item for ticked, item in boxes(mine) if not ticked]
        out += ["missing from Everyone: " + item for _, item in boxes(everyone(without_comments(template)) or "")
                if key(item) not in have]
    return out, warn


# --- the whole description --------------------------------------------------------------------------------------

def review(body, diff=None, merge_base=None, template=None, title=None):
    """(problems, warnings) for body: it passes when there are no problems. diff (the PR's unified diff) adds the
    Flags and box hints; merge_base (the commit the PR is now on) the rebase warning; title (the PR's) decides
    whether it is a fix, which needs How to reproduce (without one, the status line's type does)."""
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    stand_ins = set(STAND_IN.findall(without_comments(template)))
    body = without_comments((body or "").replace("\r\n", "\n"))
    top = sections(body)
    out, warn = [], []
    switches, files = diff_changes(diff)

    def placeholders(name, text):
        left = sorted(s for s in stand_ins if s in text)
        return ["%s still holds the template's placeholders: %s%s" % (name, ", ".join(left[:3]), " and %d more" % (
            len(left) - 3) if len(left) > 3 else "")] if left else []

    fields = status(body)
    first = next((ln for ln in body.splitlines() if ln.strip()), "")
    found = placeholders("the status line", first) if fields is not None else []
    out += found or status_problems(fields)
    kind = title_type(title) or (fields or {}).get("Type", "").strip().lower()
    if title_type(title) and fields and fields.get("Type", "").strip().lower() not in ("", title_type(title)) \
            and not STAND_IN.search(fields["Type"]):
        warn.append("the status line's type is '%s' and the title's '%s': make them the same" % (
            fields["Type"].strip(), title_type(title)))

    for name in REQUIRED[:1] + (REPRODUCE,) + REQUIRED[1:]:
        text = top.get(name)
        if name == REPRODUCE:
            if text is None:
                if kind == "fix":
                    out.append("no ## How to reproduce: a fix says how to see the bug on main (Seen on, Steps, "
                               "Expected, Actual)")
                continue
            if kind != "fix" and (any(s in text for s in stand_ins) or not text.strip()):
                out.append("## How to reproduce is for a fix: delete it, or fill it in")
                continue
        if text is None:
            out.append("no ## %s section (.forgejo/pull_request_template.md)" % name)
            continue
        part = before_subsections(text) if name == "Measurements" else text
        left = placeholders("## " + name, part)
        if left:
            out += left
        elif not part.strip():
            out.append("## %s is empty" % name)
        elif name == "What changed":
            out += what_changed_problems(text)
        elif name == REPRODUCE:
            out += reproduce_problems(text)
        elif name == "Measurements":
            out += measurement_problems(part)
        elif name == "Testing":
            out += testing_problems(text)
        elif name == "Risks":
            out += risks_problems(text)

    flags = sections(top.get("Measurements", ""), "###").get(FLAGS) if "Measurements" in top else None
    if flags is None and FLAGS in top:
        flags = top[FLAGS]   # (as a section of its own: read it, and say where it goes)
        warn.append("Flags and settings is a ### subsection of ## Measurements")
    if flags is None:
        out.append("no ### Flags and settings under ## Measurements: 'None', or a row per switch, menu row, ini key or "
                   "build flag%s" % (" (the diff adds %s)" % ", ".join(switches) if switches else ""))
    elif placeholders("", flags):
        out.append("### Flags and settings%s (write 'None' alone, or fill in the table)" % placeholders("", flags)[0])
    elif not flags.strip():
        out.append("### Flags and settings is empty: write None, or a summary line and a row per flag")
    else:
        found, warned = flags_problems(flags, switches)
        out += found
        warn += warned
    if files & set(MENU_CODE) and (flags is None or NONE.match(flags.strip())):
        warn.append("the diff changes %s and ### Flags and settings says None: list any menu row or ini key it adds "
                    "or changes" % ", ".join(sorted(files & set(MENU_CODE))))

    if "Issues" in top:
        out += issues_problems(top["Issues"])

    found, warned = checklist_problems(body, template, diff)
    out += found
    warn += warned

    measurements = before_subsections(top.get("Measurements", ""))
    bases = [c["hash"] for _, c in measurement_columns(measurements) if c["side"] == "before" and c["build"].lower() == "main"]
    if bases and merge_base and not any(merge_base.lower().startswith(h.lower()) for h in bases):
        warn.append("measured on main %s, but the PR is now on main %s: measure again, or say why the numbers still "
                    "hold" % (bases[0], merge_base[:8]))
    found = testing_parts(top.get("Testing", ""))
    untested = " ".join(found.get(p, "") for p in ("Not tested", MUST)).lower()
    for thing in measured(measurements):
        if thing.lower() in untested:
            warn.append("## Testing says '%s' is not tested or must be tested, but the Measurements say it was "
                        "measured" % thing)
    must = found.get(MUST, "").strip()
    needs = (fields or {}).get("Needs", "").strip()
    if needs and must and not STAND_IN.search(needs + must):
        if NONE.match(needs) and not NONE.match(must):
            warn.append("the status line says Needs: none, and ## Testing's 'Must be tested:' lists something")
        elif not NONE.match(needs) and NONE.match(must):
            warn.append("the status line says Needs: %s, and ## Testing's 'Must be tested:' says None" % needs)
    return out, warn


def problems(body, template=None, diff=None, title=None):
    """What keeps body from passing: an empty list when it passes"""
    return review(body, diff=diff, template=template, title=title)[0]


def wip_prefix(title):
    """The WIP prefix title starts with, as written there, or None"""
    t = (title or "").lstrip()
    for p in WIP_PREFIXES:
        if t[:len(p)].upper() == p:
            return t[:len(p)]
    return None


def strip_wip(title):
    """title without its WIP prefixes (the prefix, then the spaces after it, as Forgejo takes it off)"""
    title = (title or "").strip()
    while wip_prefix(title):
        title = title[len(wip_prefix(title)):].strip()
    return title


def is_draft(title, api_draft=False):
    """Work in progress: a WIP prefix on the title, or the API says it is a draft"""
    return bool(api_draft) or wip_prefix(title) is not None


def fetch(server, repo, number, suffix=""):
    req = urllib.request.Request("%s/api/v1/repos/%s/pulls/%d%s" % (server.rstrip("/"), repo, number, suffix),
                                 headers={"Accept": "application/json", "User-Agent": "hookshot-pr-check/1"})
    token = os.environ.get("FORGEJO_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "token " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data.decode("utf-8", "replace") if suffix else json.loads(data)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="the description, from a file")
    src.add_argument("--pr", type=int, help="the pull request's number: its description, title and diff, from the API")
    p.add_argument("--title", help="with --file: the PR's title (a fix needs How to reproduce)")
    p.add_argument("--diff", help="with --file: the PR's unified diff, for the Flags checks")
    p.add_argument("--wip", "--draft", dest="wip", action="store_true",
                   help="with --file: treat it as work in progress (not checked: a notice only)")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or "MagicBeanDev/Hookshot")
    p.add_argument("--server", default=os.environ.get("GITHUB_SERVER_URL") or "https://git.magicbean.dev")
    a = p.parse_args(argv)
    merge_base, diff, title = None, None, a.title
    if a.file:
        body, wip = Path(a.file).read_text(encoding="utf-8"), is_draft(title, a.wip)
        diff = Path(a.diff).read_text(encoding="utf-8", errors="replace") if a.diff else None
    else:
        pr = fetch(a.server, a.repo, a.pr)
        body, wip, merge_base = pr.get("body") or "", is_draft(pr.get("title"), pr.get("draft")), pr.get("merge_base")
        title = pr.get("title")
        try:
            diff = fetch(a.server, a.repo, a.pr, ".diff")
        except OSError as e:
            print("::warning::could not read the diff (%s): the Flags table is not checked against it" % e)
    found, warnings = review(body, diff=diff, merge_base=merge_base, title=title)
    if wip:
        print("::notice::Work in progress (WIP: in the title): the description is checked once it is marked ready "
              "for review%s" % (" (%d to fix by then)" % len(found) if found else ""))
        for f in found + warnings:
            print("  " + f)
        return 0
    for w in warnings:
        print("::warning::" + w)
    if not found:
        print("The description is complete: the status line, every section filled in, the measurements named by "
              "commit, every Everyone box ticked.")
        return 0
    print("The description is not complete (the template is .forgejo/pull_request_template.md; a PR without "
          "measurements goes back to WIP with the label '%s'):" % NEEDS_MEASUREMENTS)
    for f in found:
        print("::error::" + f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
