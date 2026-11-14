"""Check a pull request's description against the template (.forgejo/pull_request_template.md, CONTRIBUTING.md
"Commits and pull requests"):

  - Why, What changed, Measurements, Testing and Risk and rollback there, filled in, none of the template's <...>
    stand-ins left;
  - Testing: its three parts, Tested, Not tested and Needs other testers, each filled in; Needs other testers is
    "None", or a line per thing with its test request (a T-XXXX id or a link) or "request to open";
  - Measurements: a table whose columns each name what they measured with its hash, never a bare Before and After:
    one the change ("this PR @ <hash>", or a named build that carries it), one the baseline ("main @ <hash>", or a
    named build). main against this PR needs nothing more; anything else says which column is the baseline in a
    "Baseline: <its column>" line. A main or this PR column comes with its "main: <hash> (<date>)" or "this PR:
    <branch> @ <hash>" line, on the same commit; and a row of values;
  - the checklist: every box of "For everyone" there and ticked. "If applicable" keeps only the boxes that apply
    (or is left out when none does), and every box kept is ticked: a box there means it applies, so it is done.

Warnings, which do not fail it: Flags and settings, a note on what the PR adds and the author's recommendation, never
a gate (missing, empty or with the template's stand-ins; a row missing a cell; an RX_*, HOS_* or HOOKSHOT_* name the
diff adds that isn't listed; a change to the menu's code while it says None), a PR rebased onto a newer main than the
one measured, an If applicable box marked n/a (delete it instead), a box the diff suggests that isn't there, Not tested or Needs other testers naming something the Measurements say was
measured, and a test request still to open (forge.py pr ready refuses that one: the PR goes ready once they are open).

A pull request still in work in progress (a title starting with WIP: or [WIP], Forgejo's draft mark, or the API's
draft) is not checked: it passes with a notice listing what is left. The check applies once it is marked ready for
review; forge.py pr ready runs the same check before it takes the WIP: off.

    python -I scripts/check_pr_description.py --file body.md [--diff pr.diff] [--wip]
    python -I scripts/check_pr_description.py --pr 12 [--repo MagicBeanDev/Hookshot] [--server https://git.magicbean.dev]

--pr reads the pull request and its diff from the Forgejo API, with the token in FORGEJO_TOKEN or GITHUB_TOKEN when one
is set (a public repository needs none). Exit status 0 when it passes, 1 with the problems listed when it does not.
Standard library only; .forgejo/workflows/pr-description.yml runs it on every pull request.
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
# The sections a description fills in; Screenshots, Reviewer notes and Issues may stay empty.
REQUIRED = ("Why", "What changed", "Measurements", "Testing", "Risk and rollback")
FLAGS = "Flags and settings"
TESTING_PARTS = ("Tested", "Not tested", "Needs other testers")
# A part of Testing: "**Tested:** ...", "Tested: ..." or a "### Tested" heading ("Tested but not measured: ..." is a
# note inside Tested, not a part)
PART = re.compile(r"^(?:#{3,4}\s+)?[*_]*(%s)[*_]*\s*(?::[*_]*\s*(.*)|$)" % "|".join(
    sorted(TESTING_PARTS, key=len, reverse=True)), re.I)
TEST_REQUEST = re.compile(r"\bT-[0-9A-Z]{4}\b|https?://\S+")
TO_OPEN = re.compile(r"request to open", re.I)
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
STAND_IN = re.compile(r"<[^<>\n!]+>")   # (the template's <...> stand-ins, read from the template itself)
# A measurement column: "main @ 7afe6ae1", "this PR @ 992a2420, RX_VK_X=1", or a build named by its tag,
# "nightly-123-abcd1234"
AT_COMMIT = re.compile(r"^(?P<name>[^@]+?)\s*@\s*(?P<hash>[^\s,;()]+)")
TAGGED = re.compile(r"^(?P<name>[A-Za-z][\w.]*)-(?:\d+-)?(?P<hash>[0-9a-f]{7,40})\b")
DELTA = re.compile(r"^(Δ|delta|diff|change)\b", re.I)
# Switches the game, the build or a script reads: a quoted name added in the diff (docs/development.md, "Switches for
# testing and debugging"). Menu rows and ini keys are not spotted that surely: a change to the menu's code is a warning.
SWITCH = re.compile(r"[\"'`]((?:RX|HOS|HOOKSHOT)_[A-Z0-9_]+)[\"'`]")
MENU_CODE = ("gpu/vk/vk_menu.cpp",)


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


def boxes(text):
    """[(ticked, the item's text)] for the task list items in text"""
    return [(m.group(1).lower() == "x", m.group(2).strip()) for m in re.finditer(r"^\s*[-*] \[([ xX])\] (.+)$", text, re.M)]


def key(item):
    """an item's first words, lower case and without marks: the same item when someone ticks it, reflows it or adds a note"""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", item.lower()).split()[:4])


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(text):
    """[(header cells, [row cells])] for the Markdown tables in text, outside code blocks"""
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    lines = [ln.strip() for ln in text.splitlines()]
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


def for_everyone(body):
    """the text of ### For everyone under ## Checklist, None when there is none"""
    return sections(sections(body).get("Checklist", ""), "###").get("For everyone")


def column(cell):
    """(name, hash) of a measurement column, or None when it names no commit"""
    m = AT_COMMIT.match(cell) or TAGGED.match(cell)
    return (m.group("name").strip(), m.group("hash")) if m else None


def norm(text):
    return " ".join(text.split()).lower()


def measurement_problems(text):
    """One column is the change (this PR @ <hash>, or a named build that carries it), one a labelled baseline (main @
    <hash>, or a named build with its hash); main against this PR needs nothing more, anything else a Baseline: line"""
    found = tables(text)
    if not found:
        return ["## Measurements has no table: | | main @ <hash> | this PR @ <hash> |"]
    header, rows = found[0]
    values = [i for i, c in enumerate(header) if i and c and not DELTA.match(c)]
    if any(header[i].strip("* ").lower() in ("before", "after") for i in values):
        return ["## Measurements' columns are a bare Before and After: name them 'main @ <hash>' and 'this PR @ <hash>', "
                "or what else was compared, with its hash"]
    out, cols = [], []
    for i in values:
        c = column(header[i])
        if c is None:
            out.append("## Measurements' column '%s' names no commit: 'main @ <hash>', 'this PR @ <hash>', or what "
                       "else was compared, with its hash" % header[i])
        elif not COMMIT.match(c[1]):
            out.append("## Measurements' column '%s': '%s' is not a commit (7 to 40 hex characters)" % (header[i], c[1]))
        elif c[0].lower().startswith("this pr") and c[0].lower() != "this pr":
            out.append("## Measurements' column '%s': this PR's column is 'this PR @ <hash>', with anything more after "
                       "the hash ('this PR @ <hash>, RX_VK_X=1'); another build is named by itself" % header[i])
        else:
            cols.append((c[0].lower(), c[1], norm(header[i])))
    if not out and len(cols) < 2:
        out.append("## Measurements' table has nothing to compare with: add 'main @ <hash>' (or the baseline it was "
                   "compared with, named, with its hash)")
    elif not out:
        said = re.search(r"^\W*baseline:\s*(.+)$", text, re.M | re.I)
        names = [n for n, _, _ in cols]
        if said:
            line = norm(said.group(1))
            hits = [c for c in cols if c[2] in line]
            if not hits:   # (the column by its name and hash only, when that is enough to tell it)
                hits = [c for c in cols if "%s @ %s" % (c[0], c[1]) in line
                        and sum(d[:2] == c[:2] for d in cols) == 1]
            if len(hits) != 1:
                out.append("## Measurements' 'Baseline:' line names no one column of the table: write the column's "
                           "header there")
            elif len(hits) == len(cols):
                out.append("## Measurements' table has only the baseline")
        elif not ("main" in names and "this pr" in names):
            out.append("## Measurements does not say which column is the baseline: add a 'Baseline: <its column>' "
                       "line, with one line on why main against this PR wasn't the comparison")
    for name, pattern, line in (("main", r"^\W*main:\s*([0-9a-f]{7,40})\b", "main: <hash> (<date>)"),
                                ("this pr", r"^\W*this PR:.*?@\s*([0-9a-f]{7,40})\b", "this PR: <branch> @ <hash>")):
        hashes = [h for n, h, _ in cols if n == name]
        if not hashes:
            continue
        m = re.search(pattern, text, re.M | re.I)
        if not m:
            out.append("## Measurements has no '%s' line" % line)
        elif not any(h.startswith(m.group(1)) or m.group(1).startswith(h) for h in hashes):
            out.append("## Measurements' '%s' line names %s, and its column %s" % (line.split(":")[0] + ":",
                                                                                   m.group(1), hashes[0]))
    if not any(r and r[0] and all(i < len(r) and r[i] for i in values) for r in rows):
        out.append("## Measurements' table has no row with a value in each column")
    return out


def flags_notes(text, switches):
    """What the Flags and settings note leaves out: warnings only, it is never a gate"""
    out = []
    plain = text.strip()
    rows = []
    for header, body_rows in tables(plain):
        if header and header[0].lower() == "flag":
            rows += [(header, r) for r in body_rows if r and r[0]]
    if not rows and not re.match(r"^none\b", plain, re.I):
        out.append("## Flags and settings has neither a filled-in row nor 'None'")
    for header, r in rows:
        for i, name in enumerate(header):
            if i >= len(r) or not r[i]:
                out.append("## Flags and settings: '%s' has no '%s' (write '-' when there is nothing)" % (r[0], name))
    listed = text if rows else ""
    out += ["the diff adds %s, which ## Flags and settings does not list" % s for s in switches if s not in listed]
    return out


# The If applicable boxes a diff suggests: (the box's first words, as key() reads them, why, a test on the files and
# switches the diff changes). A hint is a warning, never a failure; pr create keeps these boxes when it fills in the
# template.
HOST_CODE = re.compile(r"^(?!tests/|third_party/).*\.(c|cc|cpp|h|hpp)$")
SHADER = re.compile(r"\.(comp|glsl|vert|frag|mesh|task|geom|tesc|tese)$")
DOCS = re.compile(r"^(docs/.*|README\.md|CONTRIBUTING\.md|AGENTS\.md)$")
HINTS = (
    ("flags noted and the", "it adds %s", lambda files, switches, read: ", ".join(switches)),
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
    """[(the If applicable item, why)] for the boxes the diff suggests"""
    switches, files = diff_changes(diff)
    if not files:
        return []
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    items = [item for _, item in boxes(sections(sections(without_comments(template)).get("Checklist", ""), "###")
                                       .get("If applicable", ""))]
    read = read_by_tests(files)
    out = []
    for start, why, test in HINTS:
        found = test(files, switches, read)
        item = next((i for i in items if key(i).startswith(start)), None)
        if found and item:
            out.append((item, why % found if "%s" in why else why))
    return out


def keep_applicable(body, keep):
    """body with its If applicable list down to the items in keep (none: the heading and a comment)"""
    m = re.search(r"^### If applicable\n(.*?)(?=^#{1,3} |\Z)", body, re.S | re.M)
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


def testing_parts(text):
    """{part: its text} for the parts of ## Testing"""
    out, name = {}, None
    for line in text.splitlines():
        m = PART.match(line.strip())
        if m:
            name = next(p for p in TESTING_PARTS if p.lower() == m.group(1).lower())
            out[name] = (m.group(2) or "") + "\n"
        elif name:
            out[name] += line + "\n"
    return out


def tester_lines(text):
    """Needs other testers' items: each bullet with its continuation lines, or each line when there are no bullets"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not any(re.match(r"^\s*[-*] ", ln) for ln in lines):
        return [ln.strip() for ln in lines]
    items = []
    for ln in lines:
        if re.match(r"^\s*[-*] ", ln) or not items:
            items.append(re.sub(r"^\s*[-*] ", "", ln).strip())
        else:
            items[-1] += " " + ln.strip()
    return items


def testing_problems(text):
    parts, out = testing_parts(text), []
    for name in TESTING_PARTS:
        if name not in parts:
            out.append("## Testing has no '%s:' part (Tested, Not tested, Needs other testers)" % name)
        elif not parts[name].strip():
            out.append("## Testing's '%s:' is empty%s" % (name, ": write None if nobody else needs to test it"
                                                           if name == "Needs other testers" else ""))
    needs = parts.get("Needs other testers", "").strip()
    if needs and not re.match(r"^none\b", needs, re.I):
        out += ["## Testing's 'Needs other testers:' has no test request for '%s': link it (scripts/test_requests.py "
                "request --pr <n> ...), or write 'request to open'" % item
                for item in tester_lines(needs) if not TEST_REQUEST.search(item) and not TO_OPEN.search(STAND_IN.sub("", item))]
    return out


def requests_to_open(body):
    """The Needs other testers lines whose test request is still to open"""
    parts = testing_parts(sections(without_comments((body or "").replace("\r\n", "\n"))).get("Testing", ""))
    needs = parts.get("Needs other testers", "")
    return [item for item in tester_lines(needs) if TO_OPEN.search(STAND_IN.sub("", item))]   # (not the template's own)


def measured(text):
    """What the Measurements say was measured on: the Hardware line's items and the table's rows"""
    things = []
    m = re.search(r"^\W*Hardware:\s*(.+)$", text, re.M | re.I)
    if m:
        things += [t.strip() for t in re.split(r"[,;]", m.group(1))]
    for header, rows in tables(text)[:1]:
        things += [r[0] for r in rows if r and r[0]]
    return [t for t in things if len(t) >= 3]


def review(body, diff=None, merge_base=None, template=None):
    """(problems, warnings) for body: it passes when there are no problems. diff (the PR's unified diff) adds the
    Flags checks; merge_base (the commit the PR is now on) the rebase warning."""
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    stand_ins = set(STAND_IN.findall(without_comments(template)))
    body = without_comments((body or "").replace("\r\n", "\n"))
    top = sections(body)
    out, warn = [], []
    switches, files = diff_changes(diff)
    for name in REQUIRED:
        text = top.get(name)
        if text is None:
            out.append("no ## %s section (.forgejo/pull_request_template.md)" % name)
            continue
        left = sorted(s for s in stand_ins if s in text)
        if left:
            out.append("## %s still holds the template's placeholders: %s%s" % (
                name, ", ".join(left[:3]), " and %d more" % (len(left) - 3) if len(left) > 3 else ""))
        elif not text.strip():
            out.append("## %s is empty" % name)
        elif name == "Measurements":
            out += measurement_problems(text)
        elif name == "Testing":
            out += testing_problems(text)
    flags = top.get(FLAGS)
    left = sorted(s for s in stand_ins if s in (flags or ""))
    if flags is None:
        warn.append("no ## Flags and settings%s: a note on what the PR adds and what you recommend, or None" % (
            " (the diff adds %s)" % ", ".join(switches) if switches else ""))
    elif left:
        warn.append("## Flags and settings still holds the template's placeholders: %s" % ", ".join(left[:3]))
    elif not flags.strip():
        warn.append("## Flags and settings is empty: write None, or a row per flag")
    else:
        warn += flags_notes(flags, switches)
    lists = sections(top.get("Checklist", ""), "###")
    everyone = lists.get("For everyone")
    if "Checklist" not in top:
        out.append("no ## Checklist: keep the For everyone list whole, and the If applicable boxes that apply")
    elif everyone is None:
        out.append("no ### For everyone checklist under ## Checklist")
    kept = boxes(lists.get("If applicable", ""))
    for ticked, item in kept:
        if NA.search(item):
            warn.append("If applicable: '%s' says n/a: delete a box that doesn't apply" % item)
        elif not ticked:
            out.append("If applicable, not ticked: %s (a box kept here applies, so it must be done: tick it, or "
                       "delete it if it doesn't apply)" % item)
    have = {key(item) for _, item in kept}
    warn += ["If applicable: the diff suggests '%s' (%s): add it, ticked once done, if it applies" % (item, why)
             for item, why in suggested_boxes(diff, template) if key(item) not in have]
    if everyone is not None:
        have = {key(item) for _, item in boxes(everyone)}
        out += ["not ticked: " + item for ticked, item in boxes(everyone) if not ticked]
        out += ["missing from For everyone: " + item for _, item in boxes(for_everyone(without_comments(template)) or "")
                if key(item) not in have]
    flags = (flags or "").strip()
    if files & set(MENU_CODE) and (not flags or re.match(r"^none\b", flags, re.I)):
        warn.append("the diff changes %s and ## Flags and settings says None: list any menu row or ini key it adds "
                    "or changes" % ", ".join(sorted(files & set(MENU_CODE))))
    m = re.search(r"^\W*main:\s*([0-9a-f]{7,40})\b", top.get("Measurements", ""), re.M | re.I)
    if m and merge_base and not merge_base.lower().startswith(m.group(1).lower()):
        warn.append("measured on main %s, but the PR is now on main %s: measure again, or say why the numbers still "
                    "hold" % (m.group(1), merge_base[:8]))
    parts = testing_parts(top.get("Testing", ""))
    untested = " ".join(parts.get(p, "") for p in ("Not tested", "Needs other testers")).lower()
    for thing in measured(top.get("Measurements", "")):
        if thing.lower() in untested:
            warn.append("## Testing says '%s' is not tested or needs other testers, but the Measurements say it was "
                        "measured" % thing)
    warn += ["## Testing's 'Needs other testers:' has a test request still to open: '%s' (the PR goes ready once it "
             "is open: docs/test-requests.md)" % item for item in requests_to_open(body)]
    return out, warn


def problems(body, template=None, diff=None):
    """What keeps body from passing: an empty list when it passes"""
    return review(body, diff=diff, template=template)[0]


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
    src.add_argument("--pr", type=int, help="the pull request's number: its description and diff, from the API")
    p.add_argument("--diff", help="with --file: the PR's unified diff, for the Flags checks")
    p.add_argument("--wip", "--draft", dest="wip", action="store_true",
                   help="with --file: treat it as work in progress (not checked: a notice only)")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or "MagicBeanDev/Hookshot")
    p.add_argument("--server", default=os.environ.get("GITHUB_SERVER_URL") or "https://git.magicbean.dev")
    a = p.parse_args(argv)
    merge_base, diff = None, None
    if a.file:
        body, wip = Path(a.file).read_text(encoding="utf-8"), a.wip
        diff = Path(a.diff).read_text(encoding="utf-8", errors="replace") if a.diff else None
    else:
        pr = fetch(a.server, a.repo, a.pr)
        body, wip, merge_base = pr.get("body") or "", is_draft(pr.get("title"), pr.get("draft")), pr.get("merge_base")
        try:
            diff = fetch(a.server, a.repo, a.pr, ".diff")
        except OSError as e:
            print("::warning::could not read the diff (%s): the Flags table is not checked against it" % e)
    found, warnings = review(body, diff=diff, merge_base=merge_base)
    if wip:
        print("::notice::Work in progress (WIP: in the title): the description is checked once it is marked ready "
              "for review%s" % (" (%d to fix by then)" % len(found) if found else ""))
        for f in found + warnings:
            print("  " + f)
        return 0
    for w in warnings:
        print("::warning::" + w)
    if not found:
        print("The description is complete: every section filled in, the measurements named, every For everyone box "
              "ticked.")
        return 0
    print("The description is not complete (the template is .forgejo/pull_request_template.md; a PR without "
          "measurements goes back to WIP with the label '%s'):" % NEEDS_MEASUREMENTS)
    for f in found:
        print("::error::" + f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
