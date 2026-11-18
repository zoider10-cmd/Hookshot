"""scripts/check_pr_description.py on sample descriptions, game-free. The template as it comes fails on every section;
three good descriptions pass: a fix (tests/pr_description/good.md, with How to reproduce), a perf change with a
variant column, and a docs change whose Measurements is one line; so does CONTRIBUTING.md's example measurements, with
its Baseline: line. Each rule refuses what it should: the status line (missing, a field missing or empty, a type that
isn't a title type, a risk not low, medium or high), Why, How to reproduce for a fix (by the title's type, else the
status line's; its Seen on, Steps, Expected and Actual; left as the template on another PR), What changed (a summary
first, then details), Measurements (one line, or a verdict, the setup lines and a table whose Before and After columns
name their commits; a Baseline: line when the before column isn't main), ### Flags and settings under it ("None", or a
summary and a row per flag with every cell), Testing (Tested, Not tested, Must be tested; each must-test item with
where, how, the result to expect and who runs it: the Test Farm or by hand), Risks with Compatibility, a bare "Fixes #", and the checklist (Everyone kept
whole and ticked; When it applies trimmed to what applies, every kept box ticked). Warnings: a switch the diff adds and
Flags doesn't list, a menu change with no flags, a rebase since the measurements, n/a, a box the diff suggests, the
status line's type against the title's, Needs against Must be tested, something measured said untested. A work-in-progress PR passes with a notice, and the workflow runs the script on Forgejo's events.

python -I -B tests/test_check_pr_description.py
"""
import contextlib
import importlib.util
import io
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_pr_description", ROOT / "scripts" / "check_pr_description.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
TEMPLATE = (ROOT / ".forgejo" / "pull_request_template.md").read_text(encoding="utf-8")
GOOD = (ROOT / "tests" / "pr_description" / "good.md").read_text(encoding="utf-8")
FIX = "fix(menu): the pause menu's text fits at 4K"

DIFF = """diff --git a/gpu/vk/vk_draw.cpp b/gpu/vk/vk_draw.cpp
--- a/gpu/vk/vk_draw.cpp
+++ b/gpu/vk/vk_draw.cpp
@@ -1,3 +1,4 @@
-    if (env_on("RX_VK_OLD")) moved();
+    if (env_on("RX_VK_OLD")) moved(1);
+    const char* e = getenv("RX_VK_NEW_THING");
diff --git a/docs/development.md b/docs/development.md
--- a/docs/development.md
+++ b/docs/development.md
@@ -1 +1,2 @@
+`RX_VK_DOCUMENTED` (set) is told of here only.
"""
MENU_DIFF = """diff --git a/gpu/vk/vk_menu.cpp b/gpu/vk/vk_menu.cpp
--- a/gpu/vk/vk_menu.cpp
+++ b/gpu/vk/vk_menu.cpp
@@ -1 +1,2 @@
+    row("Sharper text", &opt.sharper_text);
"""
HEADER = "| | Before: main @ 7afe6ae1 | After: this PR @ 992a2420 | Δ |"


def section(body, name, text, level="##"):
    """body with that heading's text replaced (up to the next heading of that level or higher)"""
    head = "%s %s\n" % (level, name)
    start = body.index(head) + len(head)
    m = re.compile(r"^#{1,%d} " % len(level), re.M).search(body, start)
    end = m.start() if m else len(body)
    return body[:start] + "\n" + text + "\n\n" + body[end:]


def drop(body, name, level="##"):
    """body without that heading and its text"""
    head = "%s %s\n" % (level, name)
    start = body.index(head)
    m = re.compile(r"^#{1,%d} " % len(level), re.M).search(body, start + len(head))
    return body[:start] + body[m.start() if m else len(body):]


def example_measurements():
    """CONTRIBUTING.md's filled-in Measurements section"""
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    block = text[text.index("### Measurements"):]
    return re.search(r"```\n(\*\*Verdict:\*\*.*?)```", block, re.S).group(1)


def measurements(text, flags="None"):
    return text + "\n### Flags and settings\n\n" + flags + "\n"


def filled():
    """the template filled in the plainest way that passes: a docs change, one line of Measurements, no flags"""
    body = drop(TEMPLATE, "How to reproduce").replace(TEMPLATE.splitlines()[0], "**Type:** docs · **Risk:** low · "
                                                       "**Tested on:** Linux · **Needs:** none")
    for name, text in (("Why", "Contributors can't tell how to run the build's tests on Windows."),
                       ("What changed", "The Windows steps are written down.\n\n- docs: `docs/development.md`."),
                       ("Measurements", measurements("Nothing to measure: docs only; run_all.py passes on main and "
                                                     "here.")),
                       ("Testing", "**Tested:** run_all.py on Linux.\n\n**Not tested:** the steps on Windows: no PC.\n\n"
                                   "**Must be tested:** None"),
                       ("Risks", "**What could break:** nothing runs it.\n\n**Turning it off:** revert the commit.\n\n"
                                 "**Compatibility:** Nothing changes.")):
        body = section(body, name, text)
    body = drop(body, "Issues")
    head, tail = body.split("### When it applies")
    return check.keep_applicable(head.replace("- [ ]", "- [x]") + "### When it applies" + tail, [])   # (none applies)


def perf():
    """GOOD as a perf change: no How to reproduce, a variant column"""
    body = drop(GOOD, "How to reproduce").replace("**Type:** fix", "**Type:** perf")
    table = ("| | Before: main @ 7afe6ae1 | After: this PR @ 992a2420 | After, RX_VK_MENU_FONT_SCALE=1: this PR @ "
             "992a2420 |\n|---|---|---|---|\n| menu frame time | 0.42 ms | 0.38 ms | 0.41 ms |\n")
    start = body.index(HEADER)
    end = body.index("\n\n", start)
    return body[:start] + table + body[end + 2:]


class Samples(unittest.TestCase):
    def test_the_bare_template_fails_on_every_section(self):
        found = check.problems(TEMPLATE)
        text = "\n".join(found)
        self.assertIn("the status line still holds the template's placeholders", text)
        for name in check.REQUIRED:
            self.assertIn("## %s still holds the template's placeholders" % name, text)
        self.assertIn("## How to reproduce is for a fix: delete it, or fill it in", text)
        self.assertIn("### Flags and settings still holds the template's placeholders", text)
        self.assertIn("## Issues: 'Fixes #' names no issue", text)
        self.assertEqual(sum(f.startswith("not ticked: ") for f in found), 10)
        self.assertIn("How to reproduce still holds", " ".join(check.problems(TEMPLATE, title="fix: x")))

    def test_the_fix_sample_passes(self):
        self.assertEqual(check.review(GOOD, diff=DIFF.replace("RX_VK_NEW_THING", "RX_VK_MENU_FONT_SCALE"), title=FIX),
                         ([], []))
        self.assertEqual(check.problems(GOOD.replace("\n", "\r\n"), title=FIX), [])
        self.assertNotIn("AI assistance", GOOD, "When it applies keeps only the boxes that apply")

    def test_a_perf_change_with_a_variant_passes(self):
        self.assertEqual(check.review(perf(), title="perf(menu): x"), ([], []))
        # (a variant as the before column is not main: it says which baseline, and why)
        body = perf().replace("| | Before: main @ 7afe6ae1 |", "| | Before, RX_VK_X=0: this PR @ 992a2420 |")
        self.assertEqual(check.problems(body), [
            "## Measurements compares something other than main against this PR: add a 'Baseline:' line saying what "
            "the before column is and why main against this PR wasn't the comparison"])
        said = body.replace("Hardware:", "Baseline: this PR with the switch off: main can't set it.\nHardware:")
        self.assertEqual(check.problems(said), [])

    def test_a_docs_change_with_one_line_passes(self):
        self.assertEqual(check.review(filled(), title="docs: x"), ([], []))
        self.assertNotIn("## How to reproduce", filled())
        self.assertNotIn("## Issues", filled(), "the section may go when there is none")

    def test_contributings_example_passes(self):
        example = example_measurements()
        self.assertIn("| | Before: nightly @ 55b976c0 | After: main @ 87991bc8 (with #2602) | Δ |", example)
        self.assertEqual(check.problems(section(filled(), "Measurements", measurements(example))), [])
        self.assertIn("Baseline:", " ".join(check.problems(section(filled(), "Measurements", measurements(
            re.sub(r"^Baseline:.*\n", "", example, flags=re.M))))))


class Template(unittest.TestCase):
    def test_the_sections_follow_the_order(self):
        names = list(check.sections(TEMPLATE))
        self.assertEqual(names, ["Why", "How to reproduce", "What changed", "Measurements", "Testing", "Risks",
                                 "Issues", "Checklist"])
        for name in names[:-1]:   # (a line of guidance under each, as a comment)
            self.assertTrue(check.sections(TEMPLATE)[name].strip().startswith("<!--"), name)
        self.assertEqual(list(check.sections(check.sections(TEMPLATE)["Measurements"], "###")), ["Flags and settings"])
        self.assertEqual(list(check.checklist(TEMPLATE)), ["Everyone", "When it applies"])

    def test_the_status_line_comes_first(self):
        first = TEMPLATE.splitlines()[0]
        self.assertEqual(list(check.status(first)), list(check.STATUS))
        self.assertEqual(check.status("**Type:** fix · **Risk:** low · **Tested on:** Linux, RX 6700 XT · **Needs:** "
                                      "none"), {"Type": "fix", "Risk": "low", "Tested on": "Linux, RX 6700 XT",
                                                "Needs": "none"})
        self.assertEqual(check.status("Type: perf | Risk: high | Tested on: Windows | Needs: Linux AMD")["Needs"],
                         "Linux AMD")

    def test_the_ai_trailers_box_is_when_it_applies(self):
        # (some maintainer accounts add no attribution, so it cannot be required)
        lists = check.checklist(TEMPLATE)
        self.assertNotIn("Assisted-by", lists["Everyone"])
        self.assertIn("Assisted-by", lists["When it applies"])
        self.assertIn("shipped at their recommended value", lists["When it applies"])

    def test_the_flags_columns(self):
        flags = check.sections(check.sections(TEMPLATE)["Measurements"], "###")["Flags and settings"]
        header = check.tables(flags)[0][0]
        self.assertEqual(header, ["Flag", "What it is", "Before this PR", "After this PR", "Effect",
                                  "Helps / doesn't help / untested", "Recommendation"])
        self.assertIn("A switch ships at its recommended value", " ".join(TEMPLATE.split()))


class Status(unittest.TestCase):
    def test_refusals(self):
        line = GOOD.split("\n## Why")[0].splitlines()[-1]
        def problems(new):
            return check.problems(GOOD.replace(line, new), title=FIX)
        self.assertEqual(problems(""), [
            "no status line: the description's first line is '**Type:** <type> · **Risk:** <low / medium / high> · "
            "**Tested on:** <OS, GPU> · **Needs:** <OS, GPU, or none>'"])
        self.assertEqual(problems(line.replace("**Risk:** low", "**Risk:** some")),
                         ["the status line's risk 'some': write low, medium or high"])
        self.assertEqual(problems(line.replace("**Type:** fix", "**Type:** bugfix")),
                         ["the status line's type 'bugfix' is not a title type: one of " + ", ".join(check.TYPES)])
        self.assertEqual(problems(line.replace(" · **Needs:** Windows, NVIDIA; Steam Deck", "")),
                         ["the status line has no 'Needs:'"])
        self.assertEqual(problems(line.replace("**Tested on:** Linux, RX 6700 XT", "**Tested on:**")),
                         ["the status line's 'Tested on:' is empty"])

    def test_the_type_against_the_title(self):
        self.assertEqual(check.review(GOOD, title="perf(menu): x")[1],
                         ["the status line's type is 'fix' and the title's 'perf': make them the same"])


class Sections(unittest.TestCase):
    def test_why(self):
        self.assertEqual(check.problems(drop(GOOD, "Why"), title=FIX),
                         ["no ## Why section (.forgejo/pull_request_template.md)"])
        self.assertEqual(check.problems(section(GOOD, "Why", "<!-- At 4K. -->"), title=FIX), ["## Why is empty"])
        self.assertEqual(check.problems(section(GOOD, "Why", "<the reason, in plain words>"), title=FIX),
                         ["## Why still holds the template's placeholders: <the reason, in plain words>"])
        self.assertIn("no ## Why section", " ".join(check.problems(None)))

    def test_how_to_reproduce(self):
        no_repro = drop(GOOD, "How to reproduce")
        want = ["no ## How to reproduce: a fix says how to see the bug on main (Seen on, Steps, Expected, Actual)"]
        self.assertEqual(check.problems(no_repro, title=FIX), want)
        self.assertEqual(check.problems(no_repro), want, "without a title, the status line's type")
        self.assertEqual(check.problems(no_repro.replace("**Type:** fix", "**Type:** feat")), [])
        self.assertEqual(check.problems(no_repro, title="feat(menu): x"), [], "the title's type decides")
        self.assertEqual(check.problems(GOOD.replace("**Expected:** every row ends inside the screen\n", ""), title=FIX),
                         ["## How to reproduce has no 'Expected:' (Seen on, Steps, Expected, Actual)"])
        self.assertEqual(check.problems(GOOD.replace("**Actual:** the last option of each row is cut off at the right "
                                                     "edge", "**Actual:**"), title=FIX),
                         ["## How to reproduce's 'Actual:' is empty"])
        template = check.sections(TEMPLATE)["How to reproduce"]
        self.assertEqual(check.problems(section(GOOD, "How to reproduce", template), title="feat(menu): x"),
                         ["## How to reproduce is for a fix: delete it, or fill it in"])
        self.assertEqual(check.problems(GOOD, title="feat(menu): x"), [], "filled in, another PR may keep it")

    def test_what_changed(self):
        details = check.sections(GOOD)["What changed"].strip().split("\n\n", 1)[1]
        self.assertEqual(check.problems(section(GOOD, "What changed", details), title=FIX), [
            "## What changed starts with the details: put a short plain summary (two or three sentences) first"])
        self.assertEqual(check.problems(section(GOOD, "What changed", "The font grows with the screen."), title=FIX), [
            "## What changed has a summary and no details: add a bullet per area, naming the files and functions"])
        self.assertEqual(check.problems(section(GOOD, "What changed", "The font grows.\n- menu: `menu_font_scale()`."),
                                        title=FIX), [], "the bullets may follow without a blank line")

    def test_risks(self):
        self.assertEqual(check.problems(GOOD.replace("**Compatibility:**", "**Players:**"), title=FIX), [
            "## Risks has no 'Compatibility:': what a player notices after updating (saves, hookshot_options.ini, the "
            "shader and pipeline caches, the vk ABI, the builder's tools), or 'Nothing changes'"])
        self.assertEqual(check.problems(section(GOOD, "Risks", "**Compatibility:**"), title=FIX), [
            "## Risks' 'Compatibility:' is empty: write what changes for a player after updating, or 'Nothing changes'"])
        self.assertEqual(check.problems(section(GOOD, "Risks", "**Compatibility:** Nothing changes."), title=FIX), [
            "## Risks says nothing on what could break: name it and where, and how to turn it off or revert it"])
        self.assertEqual(check.problems(section(GOOD, "Risks", "Low: revert the commit.\n\nCompatibility: none."),
                                        title=FIX), [], "the parts in plain words")
        self.assertEqual(check.problems(drop(GOOD, "Risks"), title=FIX),
                         ["no ## Risks section (.forgejo/pull_request_template.md)"])

    def test_issues(self):
        self.assertEqual(check.problems(section(GOOD, "Issues", "Fixes #"), title=FIX),
                         ["## Issues: 'Fixes #' names no issue: write its number, or delete the section when there is "
                          "none"])
        self.assertEqual(check.problems(section(GOOD, "Issues", "See #12\nFixes #13"), title=FIX), [])
        self.assertEqual(check.problems(drop(GOOD, "Issues"), title=FIX), [])


class Measurements(unittest.TestCase):
    def problems(self, old, new, body=GOOD):
        self.assertIn(old, body)
        return check.problems(body.replace(old, new), title=FIX)

    def test_the_columns_name_their_commits(self):
        self.assertEqual(self.problems(HEADER, "| | Before | After | Δ |"), [
            "## Measurements' column 'Before' names no commit: 'Before: main @ <hash>', 'After: this PR @ <hash>' (a "
            "variant: 'After, RX_VK_X=0: this PR @ <hash>')",
            "## Measurements' column 'After' names no commit: 'Before: main @ <hash>', 'After: this PR @ <hash>' (a "
            "variant: 'After, RX_VK_X=0: this PR @ <hash>')"])
        self.assertTrue(self.problems(HEADER, "| | main @ 7afe6ae1 | this PR @ 992a2420 | Δ |")[0].startswith(
            "## Measurements' column 'main @ 7afe6ae1' names no commit"), "the old names say no side")
        self.assertEqual(self.problems(HEADER, "| | Before: main @ latest | After: this PR @ 992a2420 | Δ |"),
                         ["## Measurements' column 'Before: main @ latest': 'latest' is not a commit (7 to 40 hex "
                          "characters)"])
        self.assertEqual(self.problems(HEADER, "| | Before: main @ 7afe6ae1 | After: this PR, as nightly @ 992a2420 | Δ |"),
                         ["## Measurements' column 'After: this PR, as nightly @ 992a2420': write this PR's build as "
                          "'this PR @ <hash>', the variant before the colon ('After, RX_VK_X=1: this PR @ <hash>') or "
                          "after the hash"])
        self.assertEqual(self.problems(HEADER, "| | After: this PR @ 992a2420 | After, X=1: this PR @ 992a2420 | Δ |"),
                         ["## Measurements' table needs a 'Before: main @ <hash>' and an 'After: this PR @ <hash>' "
                          "column"])
        self.assertEqual(self.problems(HEADER, "| | **Before:** main @ 7afe6ae1 | After: this PR @ 992a2420, "
                                               "RX_VK_X=1 | Δ |"), [], "bold, and a note after the hash")

    def test_a_baseline_other_than_main(self):
        nightly = "| | Before: nightly @ abcd1234 | After: this PR @ 992a2420 | Δ |"
        self.assertEqual(self.problems(HEADER, nightly), [
            "## Measurements compares something other than main against this PR: add a 'Baseline:' line saying what "
            "the before column is and why main against this PR wasn't the comparison"])
        said = GOOD.replace("Hardware:", "Baseline: nightly-123, main had not built.\nHardware:")
        self.assertEqual(self.problems(HEADER, nightly, said), [])

    def test_the_verdict_and_the_setup(self):
        verdict = GOOD[GOOD.index("**Verdict:**"):GOOD.index("Hardware:")]
        self.assertEqual(self.problems(verdict, ""), [
            "## Measurements has no 'Verdict:' line: start with whether it helped, by how much, and whether it passed"])
        self.assertEqual(self.problems(verdict, "**Verdict:**\n\n"), [
            "## Measurements' 'Verdict:' is empty: say whether it helped, by how much, and whether it passed"])
        line = GOOD[GOOD.index("Method:"):GOOD.index("How to reproduce: open")]
        self.assertEqual(self.problems(line, ""), ["## Measurements has no 'Method:' line (what was measured, from "
                                                   "where, how many runs, the median)"])
        self.assertEqual(self.problems("| 0.41 / 0.42 ms | 0.41 / 0.41 ms |", "| | |"), [], "one full row is enough")
        rows = GOOD[GOOD.index("| widest row"):GOOD.index("\n```\n[menu]")]
        self.assertEqual(self.problems(rows, "| widest row | | | |"),
                         ["## Measurements' table has no row with a value in each column"])

    def test_one_line_or_a_table(self):
        self.assertEqual(check.problems(section(GOOD, "Measurements", measurements("Docs only.\nNothing ran.")),
                                        title=FIX),
                         ["## Measurements has no table: the verdict, the setup and | | Before: main @ <hash> | After: "
                          "this PR @ <hash> |, or a single line saying why there is nothing to measure"])
        self.assertEqual(check.problems(section(GOOD, "Measurements", measurements("")), title=FIX),
                         ["## Measurements is empty"])
        self.assertEqual(check.problems(section(GOOD, "Measurements", measurements("**Verdict:** nothing to measure: "
                                                                                    "the log's wording only.")),
                                        title=FIX), [])

    def test_the_rebase_warning(self):
        self.assertEqual(check.review(GOOD, merge_base="7afe6ae1" + "0" * 32, title=FIX)[1], [])
        self.assertEqual(check.review(GOOD, merge_base="0123456789abcdef", title=FIX)[1], [
            "measured on main 7afe6ae1, but the PR is now on main 01234567: measure again, or say why the numbers "
            "still hold"])


class Flags(unittest.TestCase):
    def flags(self, text):
        return section(GOOD, "Flags and settings", text, "###")

    def test_none_or_rows(self):
        self.assertEqual(check.review(self.flags("None."), title=FIX), ([], []))
        self.assertEqual(check.problems(self.flags("Some, see the code."), title=FIX),
                         ["### Flags and settings has neither 'None' nor a table with a row per flag"])
        self.assertEqual(check.problems(self.flags(""), title=FIX),
                         ["### Flags and settings is empty: write None, or a summary line and a row per flag"])
        no_flags = drop(GOOD, "Flags and settings", "###")
        self.assertEqual(check.problems(no_flags, title=FIX), [
            "no ### Flags and settings under ## Measurements: 'None', or a row per switch, menu row, ini key or build "
            "flag"])
        self.assertEqual(check.problems(no_flags, diff=DIFF, title=FIX), [
            "no ### Flags and settings under ## Measurements: 'None', or a row per switch, menu row, ini key or build "
            "flag (the diff adds RX_VK_NEW_THING)"])
        template = check.sections(check.sections(TEMPLATE)["Measurements"], "###")["Flags and settings"]
        self.assertEqual(check.problems(self.flags(check.without_comments(template).strip()), title=FIX), [
            "### Flags and settings still holds the template's placeholders: <None, or a one-line summary>, <flag> "
            "(write 'None' alone, or fill in the table)"])

    def test_the_rows(self):
        table = check.sections(check.sections(GOOD)["Measurements"], "###")["Flags and settings"]
        rows = table[table.index("|"):].strip()
        self.assertEqual(check.problems(self.flags(rows), title=FIX), [
            "### Flags and settings starts with the table: put a one-line summary first (what this PR adds or changes)"])
        self.assertEqual(check.problems(GOOD.replace("| Leave unset: a testing switch |", "| |"), title=FIX), [
            "### Flags and settings: '`RX_VK_MENU_FONT_SCALE` (new)' has no 'Recommendation' (write '-' when there is "
            "nothing)"])
        self.assertEqual(check.problems(GOOD.replace("| Effect |", "| What it does |"), title=FIX),
                         ["### Flags and settings' table has no 'Effect' column"])

    def test_warnings(self):
        self.assertEqual(check.diff_changes(DIFF)[0], ["RX_VK_NEW_THING"], "one only moved, or in the docs, is not new")
        self.assertEqual(check.review(GOOD, diff=DIFF, title=FIX),
                         ([], ["the diff adds RX_VK_NEW_THING, which ### Flags and settings does not list"]))
        self.assertEqual(check.review(self.flags("None"), diff=DIFF, title=FIX)[1],
                         ["the diff adds RX_VK_NEW_THING, which ### Flags and settings does not list"])
        self.assertEqual(check.review(self.flags("None"), diff=MENU_DIFF, title=FIX), ([], [
            "the diff changes gpu/vk/vk_menu.cpp and ### Flags and settings says None: list any menu row or ini key it "
            "adds or changes"]))
        self.assertEqual(check.review(GOOD, diff=MENU_DIFF, title=FIX)[1], [], "a Flags table is there")
        # (the earlier layout, a section of its own: read, with a warning)
        flags = "## Flags and settings\n\nNone\n\n"
        old = drop(GOOD, "Flags and settings", "###").replace("## Testing\n", flags + "## Testing\n")
        self.assertEqual(check.review(old, title=FIX),
                         ([], ["Flags and settings is a ### subsection of ## Measurements"]))


class Testing(unittest.TestCase):
    def must(self, text):
        return GOOD[:GOOD.index("**Must be tested:**")] + "**Must be tested:**\n" + text + "\n\n" + \
            GOOD[GOOD.index("## Risks"):]

    def test_the_parts(self):
        self.assertEqual(check.testing_parts(check.sections(GOOD)["Testing"]).keys(), set(check.TESTING_PARTS))
        self.assertIn("Tested but not measured", check.testing_parts(check.sections(GOOD)["Testing"])["Tested"],
                      "a note inside Tested, not a part of its own")
        no_part = GOOD.replace("**Not tested:** the title screen's menu", "The title screen's menu")
        self.assertEqual(check.problems(no_part, title=FIX),
                         ["## Testing has no 'Not tested:' part (Tested, Not tested, Must be tested)"])
        empty = re.sub(r"\*\*Tested:\*\*.*?(?=\*\*Not tested)", "**Tested:**\n\n", GOOD, flags=re.S)
        self.assertEqual(check.problems(empty, title=FIX), ["## Testing's 'Tested:' is empty"])
        self.assertEqual(check.problems(self.must(""), title=FIX),
                         ["## Testing's 'Must be tested:' is empty: write None when Tested covers everything"])
        headings = section(GOOD, "Testing", "### Tested\nRan it.\n### Not tested\nWindows.\n### Must be tested\nNone")
        self.assertEqual(check.problems(headings.replace("**Needs:** Windows, NVIDIA; Steam Deck", "**Needs:** none"),
                                        title=FIX), [], "the parts as headings")

    def test_must_be_tested(self):
        none = self.must("None: Linux only.").replace("**Needs:** Windows, NVIDIA; Steam Deck", "**Needs:** none")
        self.assertEqual(check.review(none, title=FIX), ([], []))
        self.assertEqual(check.problems(self.must("- Arc A770, Windows: walls drawn, expecting no gaps (Test Farm: "
                                                  "@Beanstalk windows, intel, the walls)"), title=FIX), [])
        self.assertEqual(check.problems(self.must("- radv: the walls, expecting no gaps (by hand: the walls' edges)"),
                                        title=FIX), [], "a Test Farm tag for where")
        self.assertEqual(check.problems(self.must("- Arc A770, Windows: the walls (by hand)"), title=FIX), [
            "## Testing's 'Must be tested:' item 'Arc A770, Windows: the walls (by hand)' says no result to expect: "
            "'..., expecting <the result>'"])
        self.assertEqual(check.problems(self.must("- Arc A770: walls drawn, expecting no gaps"), title=FIX), [
            "## Testing's 'Must be tested:' item 'Arc A770: walls drawn, expecting no gaps' says not who runs it: the "
            "Test Farm ('@Beanstalk <what to test>' on the PR) or 'by hand' (and what to look at)"])
        self.assertEqual(check.problems(self.must("- walls drawn, expecting no gaps (Test Farm: @Beanstalk walls)"),
                                        title=FIX), [
            "## Testing's 'Must be tested:' item 'walls drawn, expecting no gaps (Test Farm: @Beanstalk walls)' says not "
            "where: '<OS, GPU, driver, or a Test Farm tag>: <the steps>, expecting <the result>'"])
        steps = self.must("- Windows, any GPU (I'm on Linux):\n  1. open the menu\n  2. press Start,\n  expecting the "
                          "menu (by hand: the menu's last row)")
        self.assertEqual(check.problems(steps, title=FIX), [], "steps under an item are the item's")
        self.assertEqual(check.farm_items(GOOD), [
            ("Windows, NVIDIA, any recent driver: open the pause menu at 3840x2160, expecting every row inside the "
             "screen and the frame time unchanged (by hand: read each row's end, and the FPS counter's Dev level)", False),
            ("Steam Deck, SteamOS (steamdeck): open the pause menu at 1280x800, expecting the text no smaller than on "
             "main (Test Farm: @Beanstalk steamdeck, the pause menu's text size against main)", True)])
        self.assertEqual(check.farm_items(TEMPLATE), [], "the template's own stand-in is no item")

    def test_needs_against_must_be_tested(self):
        self.assertEqual(check.review(self.must("None"), title=FIX)[1], [
            "the status line says Needs: Windows, NVIDIA; Steam Deck, and ## Testing's 'Must be tested:' says None"])
        self.assertEqual(check.review(GOOD.replace("**Needs:** Windows, NVIDIA; Steam Deck", "**Needs:** none"),
                                      title=FIX)[1],
                         ["the status line says Needs: none, and ## Testing's 'Must be tested:' lists something"])

    def test_untested_but_measured_is_a_warning(self):
        body = GOOD.replace("the title screen's menu, which", "the RX 6700 XT at 1440p, and the title screen's menu, "
                                                            "which")
        found, warnings = check.review(body, title=FIX)
        self.assertEqual(found, [])
        self.assertEqual(warnings, ["## Testing says 'RX 6700 XT' is not tested or must be tested, but the "
                                    "Measurements say it was measured"])
        self.assertEqual(check.measured(check.sections(GOOD)["Measurements"])[:2], ["CachyOS", "RX 6700 XT"])


class Checklist(unittest.TestCase):
    def test_an_unticked_or_deleted_box_fails(self):
        body = GOOD.replace("- [x] Rebased on current `main`.", "- [ ] Rebased on current `main`.")
        self.assertEqual(check.problems(body, title=FIX), ["not ticked: Rebased on current `main`."])
        self.assertEqual(check.problems(GOOD.replace("- [x] One topic.\n", ""), title=FIX),
                         ["missing from Everyone: One topic."])
        self.assertEqual(check.problems(GOOD.replace("### Everyone", "### Mine"), title=FIX),
                         ["no ### Everyone checklist under ## Checklist"])
        self.assertEqual(check.problems(GOOD[:GOOD.index("## Checklist")], title=FIX),
                         ["no ## Checklist: keep the Everyone list whole, and the When it applies boxes that apply"])

    def test_when_it_applies_keeps_only_what_applies(self):
        self.assertEqual(check.problems(GOOD[:GOOD.index("### When it applies")], title=FIX), [],
                         "left out when nothing applies")
        trimmed = GOOD.replace("- [x] Docs updated.\n", "")
        self.assertEqual(check.review(trimmed, title=FIX), ([], []), "a trimmed list passes")
        self.assertEqual(check.problems(GOOD.replace("- [x] Docs updated.", "- [ ] Docs updated."), title=FIX), [
            "When it applies, not ticked: Docs updated. (a box kept here applies, so it must be done: tick it, or "
            "delete it if it doesn't apply)"])
        self.assertEqual(check.review(GOOD.replace("- [x] Docs updated.", "- [ ] Docs updated. n/a"), title=FIX),
                         ([], ["When it applies: 'Docs updated. n/a' says n/a: delete a box that doesn't apply"]))

    def test_the_diff_hints_at_boxes(self):
        def hinted(diff):
            return [item.split(" ")[0] + " ... (" + why + ")" for item, why in check.suggested_boxes(diff)]
        def diff(*paths, added=""):
            return "".join("--- a/%s\n+++ b/%s\n@@ -1 +1,2 @@\n+%s\n" % (p, p, added) for p in paths)
        self.assertEqual(hinted(diff("gpu/vk/vk_api.h")), [
            "`MKWVK_API_VERSION` ... (it changes gpu/vk/vk_api.h)",
            "A ... (tests read gpu/vk/vk_api.h)",
            "Host ... (it changes host code (gpu/vk/vk_api.h))"])
        self.assertIn("The ... (it changes the shader gpu/vk/shaders/fsr.comp)", hinted(diff("gpu/vk/shaders/fsr.comp")))
        self.assertIn("Switches ... (it adds RX_VK_NEW)", hinted(diff("scripts/x.py", added='os.environ.get("RX_VK_NEW")')))
        self.assertIn("A ... (tests read gpu/vk/vk_menu.cpp)", hinted(diff("gpu/vk/vk_menu.cpp")),
                      "tests/ cut functions out of vk_menu.cpp")
        self.assertEqual(hinted(diff("docs/forge.md")), ["Docs ... (it changes docs/forge.md)"])
        self.assertEqual(hinted(None), [])
        # (a hint is a warning, never a failure; a box that is there already gives none)
        bare = GOOD[:GOOD.index("### When it applies")]
        found, warnings = check.review(bare, diff=diff("gpu/vk/vk_api.h"), title=FIX)
        self.assertEqual(found, [])
        self.assertEqual(warnings, [
            "When it applies: the diff suggests '`MKWVK_API_VERSION` bumped (`gpu/vk/vk_api.h`'s `MkwVkHost` or "
            "`MkwVkRenderer` changed).' (it changes gpu/vk/vk_api.h): add it, ticked once done, if it applies",
            "When it applies: the diff suggests 'A check under `tests/` that reads changed source updated in this PR, "
            "not weakened.' (tests read gpu/vk/vk_api.h): add it, ticked once done, if it applies",
            "When it applies: the diff suggests 'Host code builds on both Windows (llvm-mingw) and Linux, with UTF-8 "
            "paths.' (it changes host code (gpu/vk/vk_api.h)): add it, ticked once done, if it applies"])
        self.assertEqual(check.review(GOOD, diff=diff("gpu/vk/vk_menu.cpp"), title=FIX), ([], []))

    def test_keep_applicable(self):
        keep = [item for item, _ in check.suggested_boxes("+++ b/docs/forge.md\n+x\n")]
        lists = check.checklist(check.keep_applicable(TEMPLATE, keep))
        self.assertEqual(check.boxes(lists["When it applies"]), [(False, "Docs updated.")])
        self.assertEqual(lists["Everyone"], check.checklist(TEMPLATE)["Everyone"])
        none = check.checklist(check.keep_applicable(TEMPLATE, []))["When it applies"]
        self.assertEqual(check.boxes(none), [])
        self.assertIn("Add the boxes that apply from the template", none)

    def test_without_reproduce(self):
        body = check.without_reproduce(TEMPLATE)
        self.assertNotIn("## How to reproduce", body)
        self.assertEqual(list(check.sections(body))[:2], ["Why", "What changed"])


class Running(unittest.TestCase):
    def test_wip_titles(self):
        # (Forgejo's default WORK_IN_PROGRESS_PREFIXES, matched whatever the case)
        for title in ("WIP: fix(menu): text cut off", "[WIP] fix", "wip: fix", "  WIP:fix"):
            self.assertTrue(check.is_draft(title), title)
        self.assertTrue(check.is_draft("fix", api_draft=True))
        for title in ("fix(menu): WIP: no", "WIPE: no", "", None):
            self.assertFalse(check.is_draft(title), title)
        self.assertEqual(check.strip_wip("WIP: fix(menu): text"), "fix(menu): text")
        self.assertEqual(check.strip_wip("[WIP] WIP:  fix: x "), "fix: x")
        self.assertEqual(check.strip_wip("fix: WIP: x"), "fix: WIP: x")
        self.assertEqual(check.title_type("WIP: perf(vk)!: x"), "perf")

    def test_file_mode_uses_wip_title(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder) / "body.md"
            tmp.write_text(drop(GOOD, "Why"), encoding="utf-8")
            for title in ("WIP: " + FIX, "[WIP] " + FIX, "wip: " + FIX, "  WIP:" + FIX):
                with self.subTest(title=title):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        result = check.main(["--file", str(tmp), "--title", title])
                    self.assertEqual(result, 0)
                    self.assertIn("::notice::Work in progress", out.getvalue())
                    self.assertIn("no ## Why section", out.getvalue())
                    self.assertNotIn("::error::", out.getvalue())

    def test_file_mode_requires_complete_non_wip_body(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder) / "body.md"
            tmp.write_text(drop(GOOD, "Why"), encoding="utf-8")
            for title in (FIX, "fix: WIP: no", "WIPE: no", None, ""):
                with self.subTest(title=title):
                    argv = ["--file", str(tmp)]
                    if title is not None:
                        argv += ["--title", title]
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        result = check.main(argv)
                    self.assertEqual(result, 1)
                    self.assertIn("::error::no ## Why section", out.getvalue())
                    self.assertNotIn("::notice::Work in progress", out.getvalue())

    def test_wip_title_does_not_skip_review(self):
        body = drop(GOOD, "Why")
        want = ["no ## Why section (.forgejo/pull_request_template.md)"]
        for title in ("WIP: " + FIX, "[WIP] " + FIX, "wip: " + FIX, "  WIP:" + FIX):
            with self.subTest(title=title):
                self.assertEqual(check.review(body, title=title), (want, []))
                self.assertEqual(check.problems(body, title=title), want)

    def test_main_and_wip(self):
        folder = Path(tempfile.mkdtemp())
        tmp, diff = folder / "body.md", folder / "pr.diff"
        tmp.write_text(TEMPLATE, encoding="utf-8")
        diff.write_text(DIFF, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check.main(["--file", str(tmp), "--wip"]), 0)
            self.assertIn("::notice::Work in progress", out.getvalue())
            self.assertEqual(check.main(["--file", str(tmp), "--draft"]), 0)   # (the earlier name)
            self.assertEqual(check.main(["--file", str(tmp)]), 1)
            self.assertIn("needs measurements", out.getvalue())
        tmp.write_text(drop(GOOD, "How to reproduce"), encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check.main(["--file", str(tmp), "--title", "fix: x"]), 1)
            self.assertIn("::error::no ## How to reproduce", out.getvalue())
            self.assertEqual(check.main(["--file", str(tmp), "--title", "feat: x"]), 0)
        tmp.write_text(GOOD, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(check.main(["--file", str(tmp), "--diff", str(diff)]), 0)
        self.assertIn("::warning::the diff adds RX_VK_NEW_THING", out.getvalue())

    def test_the_workflow(self):
        wf = (ROOT / ".forgejo" / "workflows" / "pr-description.yml").read_text(encoding="utf-8")
        on = wf.split("\non:")[1].split("\npermissions:")[0]
        self.assertIn("pull_request_target:", on)
        self.assertIn("types: [opened, edited, synchronize, reopened]", on)   # (edited: the title's WIP: taken off)
        self.assertNotIn("ready_for_review", on)   # (Forgejo 17 has no such event)
        self.assertIn("runs-on: quick", wf)   # (a quick job: the runner kept free for them, docs/forgejo-runners.md)
        self.assertRegex(wf, r"uses: https://github.com/actions/checkout@[0-9a-f]{40} ")
        self.assertIn("python3 -I scripts/check_pr_description.py --pr", wf)
        self.assertNotIn("${{ github.event.pull_request.title", wf)   # (nothing the PR's author writes reaches the shell)



class TitleAndGamePaths(unittest.TestCase):
    """TITLE, the Conventional Commit the CI workflow's title job and Tooling's forge.py check; GAME_PATHS, the files
    the game runs, for which forge.py pr create wants a run in the game"""

    def test_title(self):
        for good in ("fix(vk): walls", "feat(builder)!: x", "docs: y", "ci(forge.py): z"):
            self.assertTrue(check.TITLE.match(good), good)
        for bad in ("Fix walls", "fix walls", "fix:walls", "wip: x", "WIP: fix: x"):
            self.assertFalse(check.TITLE.match(bad), bad)
        self.assertTrue(check.TITLE.match(check.strip_wip("WIP: fix: x")))

    def test_game_paths(self):
        self.assertTrue(all(p.endswith("/") for p in check.GAME_PATHS))
        for path in ("gpu/vk/vk_draw.cpp", "host/hos.c", "nx2/lift.py"):
            self.assertTrue(path.startswith(check.GAME_PATHS), path)
        for path in ("docs/development.md", "scripts/release.py", "tests/run_all.py", "website/src/x.ts"):
            self.assertFalse(path.startswith(check.GAME_PATHS), path)
        ci = (ROOT / ".forgejo" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('spec_from_file_location("check", "scripts/check_pr_description.py")', ci)   # (the title job)
        self.assertNotIn('"scripts/forge.py"', ci)   # (forge.py is Tooling's: the sparse checkout has only a forwarder)


if __name__ == "__main__":
    unittest.main()
