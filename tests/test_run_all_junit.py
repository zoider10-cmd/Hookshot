"""tests/run_all.py --list, --junit, --exact, the default substring names and --shard (CircleCI's splitter uses them)."""
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ONE = "tests/test_utf8_paths.py"


def run_all(*args):
    return subprocess.run([sys.executable, "-I", "-B", "tests/run_all.py", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)


def listed(*args):
    r = run_all("--strict", "--list", *args)
    return r, r.stdout.splitlines()


class RunAllJUnit(unittest.TestCase):
    def test_list_exits_zero_and_runs_nothing(self):
        r, lines = listed()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreater(len([ln for ln in lines if ln.startswith("tests/")]), 10)
        self.assertIn("tests/byte_compile_tracked.py", lines)
        self.assertNotIn("passed", r.stdout)

    def test_junit_file_written(self):
        with tempfile.TemporaryDirectory() as td:
            junit = os.path.join(td, "sub", "junit.xml")
            r = run_all("--exact", ONE, "--junit", junit)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            root = ET.parse(junit).getroot()
            cases = root.findall(".//testcase")
            self.assertEqual([c.get("name") for c in cases], [ONE])
            self.assertEqual(cases[0].get("file"), ONE)

    def test_exact_selects_whole_path_only(self):
        r, lines = listed("--exact", ONE)
        self.assertEqual((r.returncode, lines), (0, [ONE]), r.stderr)
        r, lines = listed("--exact", "test_utf8_paths")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(lines, [])

    def test_exact_fails_closed_and_runs_nothing(self):
        r = run_all("--exact", "tests/no_such_check.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("checks,", r.stdout)
        self.assertIn("nothing run", r.stderr)

    def test_substring_names_still_work(self):
        r, lines = listed("test_utf8_paths")
        self.assertEqual((r.returncode, lines), (0, [ONE]), r.stderr)

    def test_shards_cover_every_check_once(self):
        _, everything = listed()
        _, first = listed("--shard", "1/2")
        _, second = listed("--shard", "2/2")
        self.assertEqual(sorted(first + second), sorted(everything))
        self.assertEqual(len(set(first + second)), len(everything))


if __name__ == "__main__":
    unittest.main()
