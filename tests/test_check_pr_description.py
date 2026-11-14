"""scripts/check_pr_description.py on sample descriptions, game-free: the template as it comes fails on every section,
the sample good description (tests/pr_description/good.md) passes, and so does CONTRIBUTING.md's example
measurements; For everyone is kept whole (an unticked or deleted box, or no checklist at all, fails) while If
applicable keeps only the boxes that apply (trimmed or left out passes, a box kept but unticked fails, "n/a" and a box
the diff suggests but that isn't there are warnings); Testing has its
three parts (Tested, Not tested, Needs other testers), filled in, each tester line with its test request or "request to
open" (a warning, and pr ready's refusal), and naming something the Measurements say was measured as untested is a
warning; Measurements' columns must name main and this PR with their commits, never a bare Before and After; the
Flags and settings note is never a gate: missing, empty, a row missing a cell, a switch the diff adds that it doesn't
list and a menu change with no flags are warnings, like a rebase since the measurements; a work-in-progress PR (WIP:
or [WIP], as Forgejo reads them) passes with a notice; and the workflow runs the script on Forgejo's events.

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


def section(body, name, text):
    """body with ## name's text replaced"""
    start = body.index("## %s\n" % name) + len("## %s\n" % name)
    end = body.index("\n## ", start)
    return body[:start] + "\n" + text + "\n" + body[end:]


def example_measurements():
    """CONTRIBUTING.md's filled-in Measurements section"""
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    block = text[text.index("### Measurements"):]
    return re.search(r"```\n(Baseline: .*?)```", block, re.S).group(1)


def filled():
    """the template filled in the plainest way that passes: no flags, CONTRIBUTING.md's example measurements"""
    body = TEMPLATE
    for name, text in (("Why", "The menu's text is cut off at 4K."), ("What changed", "- menu: the font scales."),
                       ("Flags and settings", "None"),
                       ("Measurements", example_measurements() + "\n```\n[hos host] 600 presents, 78.4 fps\n```"),
                       ("Testing", "**Tested:** run_all.py on Linux.\n\n**Not tested:** Windows: no PC.\n\n"
                                   "**Needs other testers:** None"),
                       ("Risk and rollback", "Text could overflow on small screens; revert the commit.")):
        body = section(body, name, text)
    head, tail = body.split("### If applicable")
    return check.keep_applicable(head.replace("- [ ]", "- [x]") + "### If applicable" + tail, [])   # (none applies)


class Check(unittest.TestCase):
    def test_the_bare_template_fails_on_every_section(self):
        found = check.problems(TEMPLATE)
        text = "\n".join(found)
        for name in check.REQUIRED:
            self.assertIn("## %s still holds the template's placeholders" % name, text)
        self.assertEqual(sum(f.startswith("not ticked: ") for f in found), 10)

    def test_the_good_sample_passes(self):
        self.assertEqual(check.review(GOOD, diff=DIFF.replace("RX_VK_NEW_THING", "RX_VK_MENU_FONT_SCALE")), ([], []))
        self.assertEqual(check.problems(GOOD.replace("\n", "\r\n")), [])
        self.assertNotIn("AI assistance", GOOD, "If applicable keeps only the boxes that apply")

    def test_the_plain_fill_and_contributings_example_pass(self):
        self.assertEqual(check.problems(filled()), [])
        self.assertIn("| | nightly @ 55b976c0 (last nightly before #2602) | main @ 87991bc8 (with #2602) | Δ |",
                      example_measurements(), "another baseline, named, and said to be the baseline")

    def test_the_sections_follow_the_order(self):
        names = list(check.sections(TEMPLATE))
        self.assertEqual(names, ["Why", "What changed", "Flags and settings", "Measurements", "Testing", "Screenshots",
                                 "Risk and rollback", "Reviewer notes", "Issues", "Checklist"])
        for name in names[:-1]:   # (a line of guidance under each, as a comment)
            self.assertTrue(check.sections(TEMPLATE)[name].strip().startswith("<!--"), name)

    def test_the_ai_trailers_box_is_if_applicable(self):
        # (some maintainer accounts add no attribution, so it cannot be required)
        lists = check.sections(check.sections(TEMPLATE)["Checklist"], "###")
        self.assertNotIn("Assisted-by", lists["For everyone"])
        self.assertIn("Assisted-by", lists["If applicable"])
        self.assertIn("Flags noted, and the switch reference updated", lists["If applicable"])

    def test_an_unticked_or_deleted_box_fails(self):
        body = GOOD.replace("- [x] Rebased on current `main`.", "- [ ] Rebased on current `main`.")
        self.assertEqual(check.problems(body), ["not ticked: Rebased on current `main`."])
        body = GOOD.replace("- [x] One topic.\n", "")
        self.assertEqual(check.problems(body), ["missing from For everyone: One topic."])
        self.assertEqual(check.problems(GOOD.replace("### For everyone", "### Mine")),
                         ["no ### For everyone checklist under ## Checklist"])

    def test_missing_or_empty_sections(self):
        no_why = GOOD[:GOOD.index("## Why")] + GOOD[GOOD.index("## What changed"):]
        self.assertEqual(check.problems(no_why), ["no ## Why section (.forgejo/pull_request_template.md)"])
        self.assertEqual(check.problems(section(GOOD, "Risk and rollback", "")), ["## Risk and rollback is empty"])
        commented = section(GOOD, "Why", "<!-- The menu's text is cut off at 4K. -->")
        self.assertEqual(check.problems(commented), ["## Why is empty"])
        self.assertEqual(check.problems(GOOD.replace("the title screen's menu", "<what this PR could affect that "
                                                     "nobody has run yet, and why>")),
                         ["## Testing still holds the template's placeholders: <what this PR could affect that nobody "
                          "has run yet, and why>"])
        self.assertEqual(check.problems(section(GOOD, "Reviewer notes", "")), [], "Reviewer notes are optional")
        self.assertIn("no ## Why section", " ".join(check.problems(None)))

    def test_measurements_name_main_and_this_pr(self):
        def problems(old, new):
            self.assertIn(old, GOOD)
            return check.problems(GOOD.replace(old, new))
        header = "| | main @ 7afe6ae1 | this PR @ 992a2420 | Δ |"
        self.assertEqual(problems(header, "| | Before | After | Δ |"), [
            "## Measurements' columns are a bare Before and After: name them 'main @ <hash>' and 'this PR @ <hash>', "
            "or what else was compared, with its hash"])
        self.assertEqual(problems(header, "| | main @ 7afe6ae1 | branch | Δ |"), [
            "## Measurements' column 'branch' names no commit: 'main @ <hash>', 'this PR @ <hash>', or what else was "
            "compared, with its hash"])
        self.assertEqual(problems(header, "| | main @ latest | this PR @ 992a2420 | Δ |"),
                         ["## Measurements' column 'main @ latest': 'latest' is not a commit (7 to 40 hex characters)"])
        self.assertIn("does not say which column is the baseline",   # (a named build: which is the baseline?)
                      " ".join(problems(header, "| | main @ 7afe6ae1 | mine @ 992a2420 | Δ |")))
        self.assertEqual(problems("main: 7afe6ae1 (2026-11-10)", "main: (2026-11-10)"),
                         ["## Measurements has no 'main: <hash> (<date>)' line"])
        self.assertEqual(problems("this PR: fix/menu-font-4k @ 992a2420", "this PR: fix/menu-font-4k"),
                         ["## Measurements has no 'this PR: <branch> @ <hash>' line"])
        self.assertEqual(problems("| 0.41 / 0.42 ms | 0.41 / 0.41 ms |", "| | |"), [], "one full row is enough")
        self.assertEqual(problems("this PR: fix/menu-font-4k @ 992a2420", "this PR: fix/menu-font-4k @ 1234567"),
                         ["## Measurements' 'this PR:' line names 1234567, and its column 992a2420"])
        self.assertEqual(problems(header, "| | this PR @ 992a2420 | Δ |"), [
            "## Measurements' table has nothing to compare with: add 'main @ <hash>' (or the baseline it was compared "
            "with, named, with its hash)"])
        # (no "this PR, <anything>" wildcard: another build is named by itself)
        self.assertEqual(problems(header, "| | main @ 7afe6ae1 | this PR, as nightly @ 992a2420 | Δ |"), [
            "## Measurements' column 'this PR, as nightly @ 992a2420': this PR's column is 'this PR @ <hash>', with "
            "anything more after the hash ('this PR @ <hash>, RX_VK_X=1'); another build is named by itself"])

    def test_another_baseline_is_named_and_said_to_be_the_baseline(self):
        header = "| | main @ 7afe6ae1 | this PR @ 992a2420 | Δ |"
        flag = "| | this PR @ 992a2420, RX_VK_X=0 | this PR @ 992a2420, RX_VK_X=1 | Δ |"
        nightly = "| | nightly-123-abcd1234 | this PR @ 992a2420 | Δ |"
        unsaid = ("## Measurements does not say which column is the baseline: add a 'Baseline: <its column>' line, "
                  "with one line on why main against this PR wasn't the comparison")
        for other in (flag, nightly):
            self.assertEqual(check.problems(GOOD.replace(header, other)), [unsaid], other)
        said = GOOD.replace("main: 7afe6ae1", "Baseline: this PR @ 992a2420, RX_VK_X=0\nmain: 7afe6ae1")
        self.assertEqual(check.problems(said.replace(header, flag)), [])
        said = GOOD.replace("main: 7afe6ae1", "Baseline: nightly-123-abcd1234\nmain: 7afe6ae1")
        self.assertEqual(check.problems(said.replace(header, nightly)), [])
        wrong = GOOD.replace("main: 7afe6ae1", "Baseline: the old one\nmain: 7afe6ae1")
        self.assertEqual(check.problems(wrong.replace(header, nightly)), [
            "## Measurements' 'Baseline:' line names no one column of the table: write the column's header there"])
        # (the change can be a named build that carries it: main, here, against the nightly before it)
        self.assertEqual(check.problems(section(filled(), "Measurements", example_measurements())), [])
        self.assertEqual(check.problems(section(filled(), "Measurements", example_measurements().replace(
            "Baseline: nightly @ 55b976c0 (last nightly before #2602)\n", ""))), [unsaid])

    def test_flags_is_a_note_never_a_gate(self):
        def review(body, diff=None):
            found, warnings = check.review(body, diff=diff)
            self.assertEqual(found, [], "the Flags note never fails the check")
            return warnings
        self.assertEqual(review(section(GOOD, "Flags and settings", "None.")), [])
        self.assertEqual(review(section(GOOD, "Flags and settings", "Some, see the code.")),
                         ["## Flags and settings has neither a filled-in row nor 'None'"])
        self.assertEqual(review(section(GOOD, "Flags and settings", "")),
                         ["## Flags and settings is empty: write None, or a row per flag"])
        no_flags = GOOD[:GOOD.index("## Flags and settings")] + GOOD[GOOD.index("## Measurements"):]
        self.assertEqual(review(no_flags), ["no ## Flags and settings: a note on what the PR adds and what you "
                                            "recommend, or None"])
        self.assertEqual(review(no_flags, diff=DIFF), ["no ## Flags and settings (the diff adds RX_VK_NEW_THING): a "
                                                       "note on what the PR adds and what you recommend, or None"])
        template_flags = check.sections(TEMPLATE)["Flags and settings"]
        self.assertEqual(review(section(GOOD, "Flags and settings", check.without_comments(template_flags).strip())),
                         ["## Flags and settings still holds the template's placeholders: <flag>"])
        empty_cell = GOOD.replace("| Unset | Off by default: a testing switch |", "| Unset | |")
        self.assertEqual(review(empty_cell), [
            "## Flags and settings: '`RX_VK_MENU_FONT_SCALE` (new)' has no 'Recommendation' (write '-' when there is "
            "nothing)"])
        # (a switch the diff adds and the note doesn't list; one only moved, or only in the docs, is not new)
        self.assertEqual(check.diff_changes(DIFF)[0], ["RX_VK_NEW_THING"])
        self.assertEqual(review(GOOD, diff=DIFF), ["the diff adds RX_VK_NEW_THING, which ## Flags and settings does "
                                                   "not list"])
        self.assertEqual(review(section(GOOD, "Flags and settings", "None"), diff=DIFF),
                         ["the diff adds RX_VK_NEW_THING, which ## Flags and settings does not list"])

    def test_the_flags_columns(self):
        header = check.tables(check.sections(TEMPLATE)["Flags and settings"])[0][0]
        self.assertEqual(header, ["Flag", "What it does", "Default now", "Recommendation", "Helps on", "Doesn't help on",
                                  "Untested on"])
        self.assertIn("on by default / off by default / on after more testing", " ".join(TEMPLATE.split()))

    def test_warnings(self):
        none = section(GOOD, "Flags and settings", "None")
        found, warnings = check.review(none, diff=MENU_DIFF)
        self.assertEqual(found, [])
        self.assertEqual(warnings, ["the diff changes gpu/vk/vk_menu.cpp and ## Flags and settings says None: list any "
                                    "menu row or ini key it adds or changes"])
        self.assertEqual(check.review(GOOD, diff=MENU_DIFF)[1], [], "a Flags table is there")
        self.assertEqual(check.review(GOOD, merge_base="7afe6ae1" + "0" * 32)[1], [])
        self.assertEqual(check.review(GOOD, merge_base="0123456789abcdef")[1], [
            "measured on main 7afe6ae1, but the PR is now on main 01234567: measure again, or say why the numbers "
            "still hold"])

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
        tmp.write_text(GOOD, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check.main(["--file", str(tmp)]), 0)
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


class Testing(unittest.TestCase):
    def needs(self, text):
        return GOOD[:GOOD.index("**Needs other testers:**")] + "**Needs other testers:**\n" + text + "\n" + \
            GOOD[GOOD.index("## Screenshots"):]

    def test_the_parts(self):
        self.assertEqual(check.testing_parts(check.sections(GOOD)["Testing"]).keys(), set(check.TESTING_PARTS))
        self.assertIn("Tested but not measured", check.testing_parts(check.sections(GOOD)["Testing"])["Tested"],
                      "a note inside Tested, not a part of its own")
        no_part = GOOD.replace("**Not tested:** the title screen's menu", "The title screen's menu")
        self.assertEqual(check.problems(no_part),
                         ["## Testing has no 'Not tested:' part (Tested, Not tested, Needs other testers)"])
        empty = re.sub(r"\*\*Tested:\*\*.*?(?=\*\*Not tested)", "**Tested:**\n\n", GOOD, flags=re.S)
        self.assertEqual(check.problems(empty), ["## Testing's 'Tested:' is empty"])
        self.assertEqual(check.problems(self.needs("")),
                         ["## Testing's 'Needs other testers:' is empty: write None if nobody else needs to test it"])
        headings = section(GOOD, "Testing", "### Tested\nRan it.\n### Not tested\nWindows.\n### Needs other testers\nNone")
        self.assertEqual(check.problems(headings), [], "the parts as headings")

    def test_needs_other_testers(self):
        self.assertEqual(check.review(self.needs("None, the change is Linux-only.")), ([], []))
        self.assertEqual(check.problems(self.needs("- Arc A770: walls drawn, expecting no gaps (https://matrix.to/#/x)")), [])
        self.assertEqual(check.problems(self.needs("- Arc A770: walls drawn, expecting no gaps")), [
            "## Testing's 'Needs other testers:' has no test request for 'Arc A770: walls drawn, expecting no gaps': "
            "link it (scripts/test_requests.py request --pr <n> ...), or write 'request to open'"])
        wip = self.needs("- Arc A770: walls drawn,\n  expecting no gaps (request to open)\n- Deck: same (T-9MZ4)")
        found, warnings = check.review(wip)
        self.assertEqual(found, [], "request to open passes the check...")
        self.assertEqual(check.requests_to_open(wip), ["Arc A770: walls drawn, expecting no gaps (request to open)"])
        self.assertEqual(warnings, ["## Testing's 'Needs other testers:' has a test request still to open: 'Arc A770: "
                                    "walls drawn, expecting no gaps (request to open)' (the PR goes ready once it is "
                                    "open: docs/test-requests.md)"], "...with a warning (pr ready refuses it)")
        self.assertEqual(check.requests_to_open(TEMPLATE), [], "the template's own stand-in is not a request")

    def test_untested_but_measured_is_a_warning(self):
        body = GOOD.replace("the title screen's menu, which", "the RX 6700 XT at 1440p, and the title screen's menu, "
                                                            "which")
        found, warnings = check.review(body)
        self.assertEqual(found, [])
        self.assertEqual(warnings, ["## Testing says 'RX 6700 XT' is not tested or needs other testers, but the "
                                    "Measurements say it was measured"])
        self.assertEqual(check.measured(check.sections(GOOD)["Measurements"])[:2], ["RX 6700 XT", "Mesa 25.2 RADV"])


class Checklist(unittest.TestCase):
    def test_if_applicable_keeps_only_what_applies(self):
        self.assertEqual(check.problems(GOOD[:GOOD.index("### If applicable")]), [], "left out when nothing applies")
        trimmed = GOOD.replace("- [x] Screenshots for a change that shows on screen.\n", "")
        self.assertEqual(check.review(trimmed), ([], []), "a trimmed list passes")
        unticked = GOOD.replace("- [x] Docs updated.", "- [ ] Docs updated.")
        self.assertEqual(check.problems(unticked), [
            "If applicable, not ticked: Docs updated. (a box kept here applies, so it must be done: tick it, or delete "
            "it if it doesn't apply)"])
        na = GOOD.replace("- [x] Docs updated.", "- [ ] Docs updated. n/a")
        self.assertEqual(check.review(na), ([], ["If applicable: 'Docs updated. n/a' says n/a: delete a box that "
                                                 "doesn't apply"]))

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
        self.assertIn("Flags ... (it adds RX_VK_NEW)", hinted(diff("scripts/x.py", added='os.environ.get("RX_VK_NEW")')))
        self.assertIn("A ... (tests read gpu/vk/vk_menu.cpp)", hinted(diff("gpu/vk/vk_menu.cpp")),
                      "tests/ cut functions out of vk_menu.cpp")
        self.assertEqual(hinted(diff("docs/forge.md")), ["Docs ... (it changes docs/forge.md)"])
        self.assertEqual(hinted(None), [])
        # (a hint is a warning, never a failure; a box that is there already gives none)
        bare = GOOD[:GOOD.index("### If applicable")]
        found, warnings = check.review(bare, diff=diff("gpu/vk/vk_api.h"))
        self.assertEqual(found, [])
        self.assertEqual(warnings, [
            "If applicable: the diff suggests '`MKWVK_API_VERSION` bumped (`gpu/vk/vk_api.h`'s `MkwVkHost` or "
            "`MkwVkRenderer` changed).' (it changes gpu/vk/vk_api.h): add it, ticked once done, if it applies",
            "If applicable: the diff suggests 'A check under `tests/` that reads changed source updated in this PR, not "
            "weakened.' (tests read gpu/vk/vk_api.h): add it, ticked once done, if it applies",
            "If applicable: the diff suggests 'Host code builds on both Windows (llvm-mingw) and Linux, with UTF-8 "
            "paths.' (it changes host code (gpu/vk/vk_api.h)): add it, ticked once done, if it applies"])
        self.assertEqual(check.review(GOOD, diff=diff("gpu/vk/vk_menu.cpp")), ([], []))

    def test_keep_applicable(self):
        keep = [item for item, _ in check.suggested_boxes("+++ b/docs/forge.md\n+x\n")]
        body = check.keep_applicable(TEMPLATE, keep)
        lists = check.sections(check.sections(body)["Checklist"], "###")
        self.assertEqual(check.boxes(lists["If applicable"]), [(False, "Docs updated.")])
        self.assertEqual(lists["For everyone"], check.sections(check.sections(TEMPLATE)["Checklist"], "###")["For everyone"])
        none = check.sections(check.sections(check.keep_applicable(TEMPLATE, []))["Checklist"], "###")["If applicable"]
        self.assertEqual(check.boxes(none), [])
        self.assertIn("Add the boxes that apply from the template", none)

    def test_the_whole_checklist_is_kept(self):
        self.assertEqual(check.problems(GOOD[:GOOD.index("## Checklist")]),
                         ["no ## Checklist: keep the For everyone list whole, and the If applicable boxes that apply"])
        box = "- [x] Testing filled in: what was tested, what wasn't, and what needs other testers (with test requests).\n"
        self.assertIn(box, GOOD)
        self.assertEqual(check.problems(GOOD.replace(box, "")), [
            "missing from For everyone: Testing filled in: what was tested, what wasn't, and what needs other testers "
            "(with test requests)."])


if __name__ == "__main__":
    unittest.main()
