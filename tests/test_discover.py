"""nx2/discover.py's discovery in parts gives the kit's discover. Game-free: tests/test_walk.py's made-up image of random
words (with jump tables planted), the parts walked here in turn (the run stand-in) or by new processes.

  - discover.discover over 12 parts: the same functions (bodies and labels), jump tables, misses, counters, PLT stubs and
    setjmp owners as a64_lift.Lifter.discover on a lifter of its own, in the same order;
  - the same through the real path: 2 spawned processes, each rebuilding the image from an image.bin written here (this
    file's module level installs what nx2/lift.py's does, so the workers, which import it again, walk as this process);
  - a worker whose walk is not the lift's, or whose image.bin is not the lift's size, stops (_init), and the processes'
    discovery then walks here, with the kit's result;
  - parts_of cuts only where the unwind range changes, keeps every entry once and in order;
  - conflicts: a range whose predecessors one part read is a conflict when another part found a table or read them
    there, not when only one part touched it;
  - a run that raises (a worker that stopped), or parts that meet in a searched range: the kit's discover, the same
    result, and the lift says so.

It has teeth (by hand, then restored, 2026-11-16): merge dropping the parts' counters, parts_of cutting inside an unwind
range, and conflicts ignoring a range read by one part where another found a table, each fail it.

    python -I -B tests/test_discover.py
"""
import collections
import contextlib
import importlib.util
import io
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import kit  # noqa: E402,F401  (a64-kit on the path)
import a64_lift  # noqa: E402
import discover  # noqa: E402
import insn  # noqa: E402
import walk  # noqa: E402

spec = importlib.util.spec_from_file_location("test_walk", os.path.join(ROOT, "tests", "test_walk.py"))
test_walk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test_walk)   # (before the installs: it keeps the kit's walk)

insn.install()   # (at module level, as nx2/lift.py: the spawned workers import this file again and must walk the same)
walk.install()


def in_turn(fn, parts, lifter):
    return [fn(lifter, p) for p in parts]


def state(L):
    return (list(L.funcs.items()), list(L.jt.items()), dict(L.jt_missing), dict(L.stats), dict(L.plt),
            dict(getattr(L, "setjmp_owner", {})))


class DiscoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = test_walk.made_up(size=0x40000, seed=9)
        # (`adr x5, .+8; br x5` written in here and there: a BR to a code constant, which the kit's jump_table resolves)
        lo, hi, _ = cls.img.code[2]
        for pc in range(lo + 0x100, hi - 8, 0x400):
            struct.pack_into("<II", cls.img.mem, pc - test_walk.BASE, 0x10000045, 0xd61f00a0)
        cls.img.eh_starts = sorted(cls.img.entries)[::7]   # (unwind ranges of several entries each)

    def kit(self):
        L = a64_lift.Lifter(self.img)
        L.discover()
        return L

    def test_parts_are_the_kits(self):
        want = self.kit()
        self.assertGreater(len(want.jt), 0)
        L = a64_lift.Lifter(self.img)
        helper = a64_lift.Lifter(self.img)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            n = discover.discover(L, None, 4, run=lambda fn, parts: in_turn(fn, parts, helper))
        self.assertEqual(n, 4)
        self.assertIn("parts walked", out.getvalue())
        self.assertEqual(state(L), state(want))

    def setUp(self):
        gate = mock.patch.object(discover, "MIN_ENTRIES", 1000)   # (the made-up image has ~4,000 entries, OoT 294,000)
        gate.start()
        self.addCleanup(gate.stop)

    def image_bin(self, d):
        path = os.path.join(d, "image.bin")
        with open(path, "wb") as f:
            f.write(self.img.mem)
        return path

    def test_new_processes_are_the_kits(self):
        want = self.kit()
        L = a64_lift.Lifter(self.img)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"HOOKSHOT_LIFT_NO_FORK": "1"}),                 contextlib.redirect_stdout(out):
            self.image_bin(d)
            n = discover.discover(L, d, 2)
        self.assertEqual(n, 2, out.getvalue())
        self.assertIn("6 parts walked in 2 processes", out.getvalue())
        self.assertEqual(state(L), state(want))

    def test_new_processes_that_walk_otherwise_walk_here(self):
        want = self.kit()
        L = a64_lift.Lifter(self.img)
        other = [("a64_lift", "classify")] + discover.identities()[1:]   # (the lift classifies as the kit, the workers not)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"HOOKSHOT_LIFT_NO_FORK": "1"}),                 mock.patch.object(discover, "identities", lambda: other), contextlib.redirect_stdout(out):
            self.image_bin(d)
            n = discover.discover(L, d, 2)
        self.assertEqual(n, 1, out.getvalue())
        self.assertIn("walked here", out.getvalue())
        self.assertEqual(state(L), state(want))

    def test_init_checks_the_walk_and_the_image(self):
        img = self.img
        try:
            with tempfile.TemporaryDirectory() as d:
                path = self.image_bin(d)
                args = (path, test_walk.BASE, img.end, img.code, img.entries, {}, img.eh_starts)
                other = [("a64_lift", "classify")] + discover.identities()[1:]
                with self.assertRaisesRegex(RuntimeError, "walks with"):
                    discover._init(*args, other)
                with self.assertRaisesRegex(RuntimeError, "bytes"):
                    discover._init(path, test_walk.BASE, img.end + 4, img.code, img.entries, {}, img.eh_starts,
                                   discover.identities())
                discover._init(*args, discover.identities())
                view = discover._view.img
                self.assertEqual(view.mem, img.mem)
                self.assertEqual((view.end, view.code, view.entries, view.eh_starts), (img.end, img.code, img.entries,
                                                                                      img.eh_starts))
                self.assertEqual([view.word(a) for a in range(img.code[0][0], img.code[0][0] + 0x400, 4)],
                                 [img.word(a) for a in range(img.code[0][0], img.code[0][0] + 0x400, 4)])
        finally:
            discover._view = None

    def test_parts_of(self):
        L = a64_lift.Lifter(self.img)
        order = sorted(L.entries)
        parts = discover.parts_of(L, order, 12)
        self.assertGreater(len(parts), 6)
        self.assertEqual([e for p in parts for e in p], order)
        starts = L.eh_starts
        for a, b in zip(parts, parts[1:]):
            self.assertNotEqual(L.function_extent(a[-1]), L.function_extent(b[0]), "a cut inside an unwind range")
        self.assertTrue(starts)

    def test_conflicts(self):
        def r(found, searched):
            return ({}, {}, {}, collections.Counter(), set(found), set(searched))
        self.assertEqual(discover.conflicts([r({1}, {1}), r({2}, {2})]), [])
        self.assertEqual(discover.conflicts([r({1}, set()), r({1}, set())]), [])   # (tables alone: no search)
        self.assertEqual(discover.conflicts([r(set(), {5}), r({5}, set())]), [5])
        self.assertEqual(discover.conflicts([r({5}, set()), r(set(), {5})]), [5])
        self.assertEqual(discover.conflicts([r(set(), {5}), r(set(), {5})]), [5])

    def test_a_run_that_fails_walks_here(self):
        want = self.kit()
        L = a64_lift.Lifter(self.img)

        def broken(fn, parts):
            raise RuntimeError("a worker stopped")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            n = discover.discover(L, None, 4, run=broken)
        self.assertEqual(n, 1)
        self.assertIn("walked here", out.getvalue())
        self.assertEqual(state(L), state(want))

    def test_parts_that_meet_walk_here(self):
        want = self.kit()
        L = a64_lift.Lifter(self.img)
        helper = a64_lift.Lifter(self.img)

        def meeting(fn, parts):   # (part 0 searched a range where part 1 found a table)
            results = in_turn(fn, parts, helper)
            results[0][5].add(0x1234)
            results[1][4].add(0x1234)
            return results
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            n = discover.discover(L, None, 4, run=meeting)
        self.assertEqual(n, 1)
        self.assertIn("by two parts (first at 0x1234): walked here", out.getvalue())
        self.assertEqual(state(L), state(want))


if __name__ == "__main__":
    unittest.main()
