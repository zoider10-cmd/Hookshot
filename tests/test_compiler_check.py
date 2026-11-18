"""Issue 1010: the builder's compiler check names what stopped the compiler. A Windows folder no program may list above it
(C:\\Users\\<name>\\Cookies, where a moved Desktop took the launcher) is said as such; otherwise the compiler's own last words and
exit code, never "no message". No compiler is run."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party/a64-kit/tools"))
spec = importlib.util.spec_from_file_location("make_game_compiler_check", ROOT / "nx2/make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


def run(code, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class CompilerFailureTests(unittest.TestCase):
    def test_first_error(self):
        self.assertEqual(make_game.compiler_failure(run(1, stderr="warning: x\nld.lld: error: cannot open t.exe\nclang: error: link\n")),
                         "ld.lld: error: cannot open t.exe")

    def test_last_line_and_code_without_an_error(self):
        said = make_game.compiler_failure(run(1, stderr="C:\\x\\clang.exe: permission denied\n"))
        self.assertTrue(said.startswith("C:\\x\\clang.exe: permission denied, exit code "), said)

    def test_nothing_said(self):
        said = make_game.compiler_failure(run(-1073741515))   # (0xC0000135 as Windows hands it to Python)
        self.assertIn("no output, exit code", said)
        if os.name == "nt":
            self.assertIn("0xC0000135", said)


class UnlistableTests(unittest.TestCase):
    def test_not_on_linux(self):
        with mock.patch.object(make_game.os, "name", "posix"):
            self.assertIsNone(make_game.unlistable_above("/home/me/Cookies/Desktop/tools/bin/clang"))

    def test_the_highest_folder_that_denies_listing(self):
        root = os.path.abspath(os.sep)
        cookies = os.path.join(root, "Users", "me", "Cookies")
        clang = os.path.join(cookies, "Desktop", "Hookshot", "tools", "llvm-mingw", "bin", "clang.exe")
        real = os.scandir

        def scandir(folder):
            if os.path.basename(folder) in ("Cookies", "Desktop"):
                raise PermissionError(13, "Access is denied", folder)
            if not os.path.isdir(folder):
                raise FileNotFoundError(2, "not there", folder)
            return real(folder)

        with mock.patch.object(make_game.os, "name", "nt"), mock.patch.object(make_game.os, "scandir", scandir):
            self.assertEqual(make_game.unlistable_above(clang), cookies)
            self.assertIsNone(make_game.unlistable_above(os.path.join(root, "Hookshot", "bin", "clang.exe")))


if __name__ == "__main__":
    unittest.main()
