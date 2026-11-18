"""nx2/walk.py's walk finds what the kit's a64_lift.Lifter.walk finds. Game-free.

  - KIT_TREE is still third_party/a64-kit's tree-sha256 (PROVENANCE.md): an a64-kit refresh fails here until nx2/walk.py is
    compared with the kit's walk again and KIT_TREE moved on;
  - two lifters over the same made-up image discover it, one with each walk: the same functions, bodies, labels, jump tables
    and counters. The image is random words (every kind classify knows turns up: branches, calls, returns, branches through a
    register, traps, system instructions) with some plain runs and loops written in, an entry every 64 bytes, read once
    through EdenImage's word view and code ranges (nx2/image.py, the walk's fast path) and once through plain methods;
  - the plain ops of one word share one entry, and the walk's discovery sees a word at the pcs it is at.

It has teeth (by hand, then restored, 2026-11-16): the walk not stopping at another entry, a conditional branch's target
left unvisited, and the shared entry kept for a word classify calls a branch, each fail it.

    python -I -B tests/test_walk.py
"""
import os
import random
import re
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import kit  # noqa: E402,F401  (a64-kit on the path)
import a64_lift  # noqa: E402
import image  # noqa: E402
import insn  # noqa: E402
import nx_image  # noqa: E402
import walk  # noqa: E402

BASE = 0x80000000
KIT_WALK = a64_lift.Lifter.walk   # (the kit's: nothing installed nx2/walk.py in this process)


def made_up(size=0x20000, seed=3):
    """An EdenImage without an exefs: random words with plain runs and backward branches written in; three code ranges"""
    rng = random.Random(seed)
    words = []
    for i in range(size // 4):
        r = rng.random()
        if r < 0.55:
            words.append(0x91000400 | (rng.getrandbits(12) << 10) | rng.getrandbits(5))   # add (a plain op, few words)
        elif r < 0.6:
            words.append(0x54000001 | ((-(rng.randrange(1, 40)) & 0x7FFFF) << 5))        # b.ne back (a loop)
        elif r < 0.62:
            words.append(0xd65f03c0)                                                      # ret
        elif r < 0.63:
            words.append(rng.choice((0xd61f00a0, 0xd63f00a0, 0xd4200000, 0xd4000001, 0xd5033fdf)))   # br, blr x5; brk; svc; isb
        else:
            words.append(rng.getrandbits(32))
    img = object.__new__(image.EdenImage)
    nx_image.MAIN_BASE = BASE
    img.mem = bytearray(struct.pack("<%dI" % len(words), *words))
    img.end = BASE + size
    img.code = [(BASE + 0x40, BASE + 0x8000, "main"), (BASE + 0x9000, BASE + 0x9100, "subsdk0"),
                (BASE + 0xa000, BASE + size - 0x100, "sdk")]
    img.lookups()
    img.entries = {lo + o for lo, hi, _ in img.code for o in range(0, hi - lo, 64)}
    img.hooks, img.names = {}, {}
    return img


class Plain:
    """The same image through plain methods only (no _words, no _spans): the walk's other path"""

    def __init__(self, img):
        self.img = img
        self.entries, self.hooks, self.names, self.code = img.entries, img.hooks, img.names, img.code

    def in_code(self, a):
        return nx_image.NxImage.in_code(self.img, a)

    def word(self, a):
        return nx_image.NxImage.word(self.img, a)

    def read(self, a, n):
        return nx_image.NxImage.read(self.img, a, n)


def discovered(img, walk_fn):
    a64_lift.Lifter.walk = walk_fn
    try:
        L = a64_lift.Lifter(img)
        L.discover()
    finally:
        a64_lift.Lifter.walk = KIT_WALK
    return L


class WalkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        insn.install()   # (as nx2/lift.py: both walks classify through it)

    def test_kit_tree(self):
        text = open(os.path.join(ROOT, "third_party", "a64-kit", "PROVENANCE.md"), encoding="utf-8").read()
        tree = re.search(r"tree-sha256: ([0-9a-f]{64})", text).group(1)
        self.assertEqual(walk.KIT_TREE, tree, "a64-kit changed: compare nx2/walk.py's walk with the kit's, then move KIT_TREE")

    def compare(self, img):
        kit_l, ours = discovered(img, KIT_WALK), discovered(img, walk.walk)
        self.assertGreater(len(kit_l.funcs), 500)
        kinds = {k[0] for body, _ in kit_l.funcs.values() for k, _ in body.values()}
        self.assertTrue({"op", "b", "bl", "bcond", "cbz", "tbz", "ret", "br", "blr", "trap"} <= kinds, kinds)
        self.assertEqual(sorted(kit_l.funcs), sorted(ours.funcs))
        for e in kit_l.funcs:
            self.assertEqual(kit_l.funcs[e], ours.funcs[e], "f_%08x" % e)
        self.assertEqual(kit_l.jt, ours.jt)
        self.assertEqual(kit_l.jt_missing, ours.jt_missing)
        self.assertEqual(kit_l.stats, ours.stats)
        self.assertEqual(kit_l.entries, ours.entries)
        return ours

    def test_same_as_the_kit(self):
        img = made_up()
        ours = self.compare(img)
        shared = {}
        for body, _ in ours.funcs.values():
            for pc, kw in body.items():
                if kw[0][0] == "op":
                    self.assertIs(shared.setdefault(kw[1], kw), kw, "two entries for the word %#010x" % kw[1])
                self.assertEqual(kw[1], img.word(pc), "the word at %#x" % pc)
        self.compare(Plain(img))


if __name__ == "__main__":
    unittest.main()
