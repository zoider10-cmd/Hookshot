"""nx2/dead_flags.py's dead_flags gives the kit's answers. Game-free, no translator: made-up functions with hand-written
instruction texts.

3,000 random functions of 1-40 instructions: plain ops whose text writes flags, reads them, both or neither, an op the
translator does not handle (its flags), conditional branches (which read flags), branches, calls inside and outside the
function's entries, returns, a branch through a register with and without a jump table, and SVCs. Each is asked of the kit's
Lifter.dead_flags and of nx2's, which must agree; both kinds turn up (functions with a flag write, where the kit's method runs,
and functions with none, answered at once), and some of the first kind have dead stores.

It has teeth (by hand, then restored, 2026-11-16): writes_flags looking at the first op only, or at the flags an op reads
instead of those it writes, each fail it. (Counting an unhandled op's text as a write only sends a function to the kit's
method, whose answer is the same: not a fault.)

    python -I -B tests/test_dead_flags.py
"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import kit  # noqa: E402,F401  (a64-kit on the path)
import a64_lift  # noqa: E402
import a64emit  # noqa: E402
import dead_flags  # noqa: E402

KIT = a64_lift.Lifter.dead_flags   # (the kit's: nothing installed nx2/dead_flags.py in this process)
OP = ("op",)
TEXTS = [
    ("c->x[1] = c->x[2] + 4;", 0),
    ("{ uint64_t r = c->x[3] - 1; c->n = r >> 63; c->z = r == 0; c->c = 1; c->v = 0; c->x[3] = r; }", 0),
    ("c->z = c->x[4] == 0;", 0),
    ("c->x[5] = c->z ? c->x[6] : c->x[7];", 0),
    ("{ c->c = c->x[1] < 3; c->x[0] = c->n; }", 0),
    ("c->n = 0; c->z = 1; c->c = 0; c->v = 0;", a64emit.UNHANDLED),   # (unhandled: its text is not what runs)
    ("c->x[8] = 0;", a64emit.UNHANDLED),
]


def function(rng, base, entries):
    """(body, pcs, texts) of a made-up function at base"""
    body, texts = {}, {}
    n = rng.randrange(1, 41)
    # (half the functions write no flag: texts that only read them, or an unhandled op whose text would)
    palette = range(len(TEXTS)) if rng.random() < 0.5 else (0, 3, 5, 6)
    for i in range(n):
        pc = base + 4 * i
        r = rng.random()
        if r < 0.6:
            w = rng.choice(palette)
            texts[w] = TEXTS[w]
            body[pc] = (OP, w)
        elif r < 0.7:
            body[pc] = (("bcond", base + 4 * rng.randrange(n), rng.randrange(16)), 0x54000000)
        elif r < 0.75:
            body[pc] = (("b", base + 4 * rng.randrange(n + 2)), 0x14000000)
        elif r < 0.8:
            body[pc] = (("cbz", base + 4 * rng.randrange(n), 1, 1, 0), 0xb4000000)
        elif r < 0.86:
            body[pc] = (("bl", rng.choice(entries + [0x9000])), 0x94000000)
        elif r < 0.89:
            body[pc] = (("blr", 5), 0xd63f00a0)
        elif r < 0.93:
            body[pc] = (("ret", 30), 0xd65f03c0)
        elif r < 0.97:
            body[pc] = (("br", 5), 0xd61f00a0)
        else:
            body[pc] = (("svc", 1), 0xd4000021)
    return body, sorted(body), texts


class DeadFlagsTests(unittest.TestCase):
    def test_same_as_the_kit(self):
        rng = random.Random(5)
        L = object.__new__(a64_lift.Lifter)
        entries = [0x100000 + 0x1000 * i for i in range(3000)]
        L.entries, L.plt, L.jt = set(entries), {}, {}
        dead_flags.install()
        ours = a64_lift.Lifter.dead_flags
        self.assertIsNot(ours, KIT)
        kinds, dead = {"writes": 0, "none": 0}, 0
        for e in entries:
            body, pcs, texts = function(rng, e, entries)
            for pc, (k, _) in body.items():
                if k[0] == "br" and rng.random() < 0.5:
                    L.jt[pc] = [e + 4 * rng.randrange(len(pcs))]
            L.cur = e
            want = KIT(L, body, pcs, texts)
            got = ours(L, body, pcs, texts)
            self.assertEqual(got, want, "f_%08x" % e)
            kinds["writes" if dead_flags.writes_flags(body, texts) else "none"] += 1
            dead += bool(want)
        self.assertGreater(kinds["writes"], 300, kinds)
        self.assertGreater(kinds["none"], 300, kinds)
        self.assertGreater(dead, 100)


if __name__ == "__main__":
    unittest.main()
