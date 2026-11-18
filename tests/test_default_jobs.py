"""make_game.py's automatic build workers leave one CPU thread free, as the launcher's Automatic does
(SystemInfo.AutomaticWorkers: every thread but one), and never go below one. The function is cut out of the source and run
with the CPU count stubbed, so no build runs."""
import ast
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_default_jobs(cpus):
    src = open(os.path.join(ROOT, "nx2", "make_game.py"), encoding="utf-8").read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "default_jobs")
    fake_os = types.SimpleNamespace(cpu_count=lambda: cpus)
    ns = {"os": fake_os}
    exec(compile(ast.Module([fn], []), "make_game.py", "exec"), ns)
    return ns["default_jobs"]


class DefaultJobs(unittest.TestCase):
    def run_with(self, cpus):
        out = io.StringIO()
        with redirect_stdout(out):
            jobs = load_default_jobs(cpus)()
        return jobs, out.getvalue()

    def test_leaves_one_thread(self):
        for cpus, want in ((24, 23), (16, 15), (8, 7), (4, 3), (2, 1)):
            jobs, said = self.run_with(cpus)
            self.assertEqual(jobs, want, cpus)
            self.assertIn("up to %d compilers at once" % want, said)

    def test_never_below_one(self):
        self.assertEqual(self.run_with(1)[0], 1)

    def test_unknown_count(self):
        self.assertEqual(self.run_with(None)[0], 1)   # (os.cpu_count() can be None: 2 assumed, one left free)


if __name__ == "__main__":
    unittest.main()
