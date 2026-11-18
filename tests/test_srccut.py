"""tests/srccut.py, the one source cutter the checks share (the dev-loop proposal's D2): a block's braces are counted outside
string and character literals (raw ones too), comments and preprocessor lines; a missing or repeated marker stops the check
with one message naming it, and the file it was read from and the check when the check names no source; between() and
unique=False; and the comparison with the old brace counter that a migration runs.

python -I -B tests/test_srccut.py
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
import srccut  # noqa: E402

SOURCE = r'''
static int other(void) { return 1; }

void menu_row(const char *label) {
    const char *open = "{ not a brace";   // nor this one: }
    char c = '}';
    /* a comment with { and } in it
       } */
    std::string raw = R"x(a raw }} string)x";
#define WRAP(x) { x }
    long big = 1'000'000;
    if (label) {
        draw("}\"");
    }
}

int after(void) { return 2; }
'''


class Cut(unittest.TestCase):
    def setUp(self):   # (no checkout to search for the file a failing cut read: CheckoutSource does that once)
        patch = mock.patch.object(srccut, "_tracked_sources", return_value=[])
        patch.start()
        self.addCleanup(patch.stop)

    def test_block_skips_braces_in_literals_comments_and_preprocessor_lines(self):
        cut = srccut.block(SOURCE, "void menu_row(", "menu.cpp")
        self.assertTrue(cut.startswith("void menu_row(const char *label) {"))
        self.assertTrue(cut.endswith('        draw("}\\"");\n    }\n}'), cut[-60:])
        self.assertNotIn("after", cut)

    def test_the_old_counter_cut_that_wrongly_and_plain_code_the_same(self):
        try:   # (it counted the braces in the string, the comments and the literals)
            old = srccut._naive(SOURCE, "void menu_row(")
        except (ValueError, IndexError):
            old = None
        self.assertNotEqual(old, srccut.block(SOURCE, "void menu_row("))
        plain = "void f(void) {\n    if (x) {\n        y();\n    }\n}\n"
        self.assertEqual(srccut.block(plain, "void f("), srccut._naive(plain, "void f("))

    def test_a_missing_marker_names_the_source_and_the_marker(self):
        with self.assertRaises(srccut.CutError) as e:
            srccut.block(SOURCE, "void renamed(", "gpu/vk/vk_menu.cpp")
        self.assertIn("'void renamed(' is not in gpu/vk/vk_menu.cpp", str(e.exception))

    def test_a_check_that_names_no_source_is_named_itself(self):
        with self.assertRaises(srccut.CutError) as e:
            srccut.block(SOURCE, "void renamed(")
        self.assertIn("'void renamed(' is not in the source tests/test_srccut.py cut", str(e.exception))
        with self.assertRaises(srccut.CutError) as e:
            srccut.between(SOURCE, "(void) {", ";")
        self.assertIn("is in the source tests/test_srccut.py cut more than once", str(e.exception))

    def test_a_check_that_names_no_source_gets_the_file_it_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gpu").mkdir()
            (root / "gpu" / "menu.cpp").write_bytes(SOURCE.replace("\n", "\r\n").encode("utf-8"))
            (root / "gpu" / "copy.cpp").write_bytes(b"int after(void) { return 2; }\n")
            text = (root / "gpu" / "menu.cpp").read_text(encoding="utf-8")   # (CRLF read as \n, as the checks read)
            tracked = ["gpu/copy.cpp", "gpu/menu.cpp"]
            with mock.patch.object(srccut, "ROOT", root), mock.patch.object(srccut, "_tracked_sources", return_value=tracked):
                with self.assertRaises(srccut.CutError) as e:
                    srccut.block(text, "void renamed(")
                self.assertIn("'void renamed(' is not in gpu/menu.cpp (cut by test_srccut.py)", str(e.exception))
                with self.assertRaises(srccut.CutError) as e:   # (a cut of a cut: the one file that holds it)
                    srccut.block(srccut.block(text, "void menu_row("), "renamed")
                self.assertIn("is not in gpu/menu.cpp (cut by", str(e.exception))
                with self.assertRaises(srccut.CutError) as e:   # (two files hold it: name only the check)
                    srccut.block("int after(void) { return 2; }", "renamed")
                self.assertIn("is not in the source test_srccut.py cut", str(e.exception))

    def test_a_repeated_marker_stops_unless_asked_for_the_first(self):
        with self.assertRaises(srccut.CutError) as e:
            srccut.block(SOURCE, "(void) {", "menu.cpp")
        self.assertIn("more than once (lines 2 and 17)", str(e.exception))
        self.assertEqual(srccut.block(SOURCE, "(void) {", unique=False), "(void) { return 1; }")

    def test_between(self):
        self.assertEqual(srccut.between(SOURCE, "char c", ";"), "char c = '}'")
        with self.assertRaises(srccut.CutError):
            srccut.between(SOURCE, "char c", "no such end")

    def test_an_unclosed_block_says_so(self):
        with self.assertRaises(srccut.CutError) as e:
            srccut.block("void f(void) {\n    if (x) {\n", "void f(")
        self.assertIn("does not close", str(e.exception))

    def test_the_migration_check_compares_with_the_old_counter(self):
        plain = "void f(void) { { } }\n"
        with mock.patch.dict(os.environ, {"SRCCUT_CHECK_NAIVE": "1"}):
            self.assertEqual(srccut.block(plain, "void f("), "void f(void) { { } }")
            with self.assertRaises(srccut.CutError) as e:
                srccut.block('void g(void) { s = "}"; }\n', "void g(")
        self.assertIn("cuts differently from the old brace counter", str(e.exception))


class CheckoutSource(unittest.TestCase):
    def test_a_failing_cut_names_the_tracked_source_it_read(self):
        tracked = [name for name in srccut._tracked_sources() if name.endswith(".c")]
        if not tracked:
            self.skipTest("no git to list the tracked sources")
        name = tracked[0]
        text = (srccut.ROOT / name).read_text(encoding="utf-8")
        with self.assertRaises(srccut.CutError) as e:
            srccut.block(text, "srccut: no such marker")
        self.assertIn("is not in %s (cut by tests/test_srccut.py)" % name, str(e.exception))


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
