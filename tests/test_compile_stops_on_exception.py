"""A compile that raises (its compiler gone, an object or its stamp not writable) or a Ctrl-C stops the compile at once.

nx2/build.py main runs compile_one on a thread pool. When one raises, the exception leaves the pool's `with` block, whose
exit waits for every job still queued: each of them then starts its compiler, the whole compile (up to an hour on a small PC)
with no line printed, before the build stops on the first file's error. Executes the AST-extracted compile_one and main's
actual compile statements with authored compiler stand-ins: no compiler, game or memory stress is involved.
"""
import argparse
import ast
import concurrent.futures
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'nx2/build.py'


def actual_coordinator(source):
    tree = ast.parse(source.read_text(encoding='utf-8'))
    compile_one, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'compile_one']
    main, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main']
    start, = [i for i, node in enumerate(main.body) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Tuple) and [getattr(n, 'id', None) for n in t.elts] == ['t0', 'failed']
                      for t in node.targets)]
    end, = [i for i, node in enumerate(main.body) if i > start and isinstance(node, ast.If)
            and isinstance(node.test, ast.Name) and node.test.id == 'still']
    wrapper = ast.parse('def run_compile_jobs():\n    return 0\n').body[0]
    wrapper.body = main.body[start:end + 1] + wrapper.body
    module = ast.fix_missing_locations(ast.Module(body=[compile_one, wrapper], type_ignores=[]))
    scope = dict(os=os, time=time, concurrent=concurrent, GATE=None, no_throttle=lambda handle: None)
    exec(compile(module, str(source), 'exec'), scope)
    return scope


class CompileStopsOnExceptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hookshot-compile-stops-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.cache = self.folder / 'cache'
        self.cache.mkdir()
        self.jobs = []
        for name in ('A', 'B', 'C', 'D', 'E'):
            source = self.folder / ('code_%s.c' % name)
            source.write_text('/* authored input, never compiled */\n', encoding='ascii')
            self.jobs.append(('authored-compiler', str(source), str(self.folder / ('code_%s.o' % name)), ['-O1'], b'h'))
        self.scope = actual_coordinator(SOURCE)

    def run_jobs(self, raising, workers):
        launched, lock = [], threading.Lock()

        class Child:
            def __init__(child, args, **kwargs):
                obj = Path(args[-1]).stem
                if obj == raising[0]:
                    raise raising[1]
                with lock:
                    launched.append(obj)
                child.args, child.obj, child.returncode = args, args[-1], 0

            def __enter__(child):
                return child

            def __exit__(child, *args):
                return False

            def communicate(child):
                time.sleep(0.05)
                Path(child.obj).write_bytes(b'authored object')
                return '', ''

        self.scope.update(jobs=self.jobs, a=SimpleNamespace(jobs=workers),
                          subprocess=SimpleNamespace(Popen=Child, PIPE=subprocess.PIPE,
                                                     CompletedProcess=subprocess.CompletedProcess),
                          OBJ_CACHE=str(self.cache), PLANNED={(j[1], j[2]): '%040d' % i for i, j in enumerate(self.jobs)},
                          cache_put=lambda obj, key: None, counted=False, expected={}, pending=[], eta_jobs=workers,
                          eta_left=lambda pending, jobs: 0, src_size=os.path.getsize)
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(type(raising[1])):
                self.scope['run_compile_jobs']()
        return launched

    def test_a_compiler_that_cannot_start_stops_the_compile(self):
        # (one compiler at a time: the first job raises, the four after it are queued. The worker may take the next one before
        # the pool hears of the failure: one, not all four)
        launched = self.run_jobs(('code_A', FileNotFoundError(2, 'authored: the compiler is gone')), workers=1)
        print('launched after the failure: %s' % launched, flush=True)
        self.assertLessEqual(len(launched), 1, 'the queued compiles ran after the first raised')

    def test_queued_jobs_do_not_start_after_one_raises_beside_others(self):
        # (two at a time: B runs beside A, which raises; of C, D and E at most the one A's worker takes next starts)
        launched = self.run_jobs(('code_A', PermissionError(13, 'authored: the object is held')), workers=2)
        print('launched: %s' % launched, flush=True)
        self.assertLessEqual(len(launched), 2, 'the queued compiles ran after one raised')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    args, remaining = parser.parse_known_args()
    SOURCE = args.source.resolve()
    unittest.main(argv=[__file__, *remaining])
