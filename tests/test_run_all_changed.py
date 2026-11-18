"""tests/run_all.py --changed (the dev-loop proposal's D1): the checks that read a changed file, by its path or its name in the
test's text, the changed tests themselves, and every check when the runner or a shared test file changed; the files from git,
since the base's merge base, committed or not, and the untracked ones.

python -I -B tests/test_run_all_changed.py
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_all_changed", ROOT / "tests" / "run_all.py")
run_all = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_all)
TESTS = sorted(d + "/" + f for d in ("tests", "nx2") for f in os.listdir(ROOT / d) if f.startswith("test_") and f.endswith(".py"))


class ChangedTests(unittest.TestCase):
    def test_the_checks_that_name_a_changed_file(self):
        picked, everything = run_all.reads_changed(TESTS, ["nx2/chunks.py"])
        self.assertFalse(everything)
        self.assertIn("tests/test_chunk_split.py", picked)
        self.assertIn("tests/test_parallel_emit.py", picked)
        self.assertNotIn("tests/test_team_chat.py", picked)
        self.assertLess(len(picked), len(TESTS) // 4)

    def test_by_name_too_and_not_inside_a_longer_name(self):
        picked, _ = run_all.reads_changed(TESTS, ["scripts/team_chat.py"])
        self.assertIn("tests/test_team_chat.py", picked)
        self.assertFalse(any("team_chat_x" in p for p in picked))

    def test_a_changed_test_runs_itself(self):
        self.assertEqual(run_all.reads_changed(TESTS, ["tests/test_run_all_changed.py"])[0], ["tests/test_run_all_changed.py"])

    def test_the_runner_or_a_shared_test_file_runs_everything(self):
        for changed in (["tests/run_all.py"], ["tests/some_shared_helper.py"]):
            picked, everything = run_all.reads_changed(TESTS, changed)
            self.assertTrue(everything)
            self.assertEqual(picked, TESTS)

    def test_a_file_nothing_names_runs_no_test(self):
        unnamed = "docs/" + "-".join(("nothing", "reads", "this")) + ".md"   # (made here: this file's text does not name it)
        self.assertEqual(run_all.reads_changed(TESTS, [unnamed])[0], [])

    def test_a_module_a_test_imports_by_name(self):
        self.assertIn("tests/test_parallel_emit.py", run_all.reads_changed(TESTS, ["nx2/chunks.py"])[0])

    def test_the_files_come_from_git_committed_or_not_and_untracked(self):
        answers = {("merge-base", "HEAD", "origin/main"): "abc123\n", ("diff", "--name-only", "abc123"): "nx2/a.py\nnx2/b.py\n",
                   ("ls-files", "--others", "--exclude-standard"): "tests/test_new.py\n"}

        def git(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, answers[tuple(cmd[3:])], "")
        with mock.patch.object(run_all.subprocess, "run", git):
            self.assertEqual(run_all.changed_files("origin/main"), ["nx2/a.py", "nx2/b.py", "tests/test_new.py"])

    def test_the_base_is_main_on_the_remote_that_points_at_hookshot(self):
        # (forge.py adds forge for it unless a remote points there already; a GitHub-era clone's origin is GitHub)
        cases = (("forge\thttps://git.magicbean.dev/MagicBeanDev/Hookshot.git (fetch)\n"
                  "origin\thttps://github.com/NotRexed/Hookshot.git (fetch)\n", "forge/main"),
                 ("hookshot\thttps://git.magicbean.dev/MagicBeanDev/Hookshot.git (fetch)\n"
                  "forge-fork\thttps://git.magicbean.dev/someone/Hookshot.git (fetch)\n", "hookshot/main"),
                 ("origin\thttps://git.magicbean.dev/someone/Hookshot.git (fetch)\n", "origin/main"))
        for out, want in cases:
            def git(cmd, **kw):
                self.assertEqual(cmd[3:], ["remote", "-v"])
                return subprocess.CompletedProcess(cmd, 0, out, "")
            with mock.patch.object(run_all.subprocess, "run", git):
                self.assertEqual(run_all.default_base(), want, out)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
