"""The lift's discovery shortcuts give the kit's answers: nx2/image.py EdenImage.word and in_code (a 32-bit view of the image and
a flat tuple of code ranges, in place of NxImage's struct unpack and loop) and nx2/insn.py's classify (a word known to be a plain
op at one pc is one at every pc). Game-free: a made-up image and words.

  - word and in_code against NxImage's own methods at every address of a small image with three code ranges, at the edges
    of each range and of the image, unaligned and outside it (NxImage's errors too);
  - classify, each word asked twice at two pcs (so the second answer can come from the kit's words remembered as plain ops),
    against classify_ext and the kit's classify asked directly: branches (whose targets read the pc), the pointer
    authentication forms nx2/insn.py adds, system instructions and plain ops.

It has teeth (by hand, then restored, 2026-11-16): word reading off by one word, in_code taking a range's end, and the
classify cache keeping a branch, each fail it.

    python -I -B tests/test_lift_lookups.py
"""
import os
import random
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

BASE = 0x80000000


def made_up(size=0x3000, seed=7):
    """An EdenImage without an exefs: random bytes, code in three ranges, set up as EdenImage.__init__ does"""
    img = object.__new__(image.EdenImage)
    rng = random.Random(seed)
    nx_image.MAIN_BASE = BASE
    img.mem = bytearray(rng.getrandbits(8) for _ in range(size))
    img.end = BASE + size
    img.code = [(BASE + 0x100, BASE + 0x800, "main"), (BASE + 0x1000, BASE + 0x1004, "subsdk0"),
                (BASE + 0x2000, BASE + 0x2ffc, "sdk")]
    img.lookups()
    return img


def kit_answer(fn, *args):
    try:
        return fn(*args)
    except (struct.error, IndexError, ValueError) as e:
        return type(e)


class LookupTests(unittest.TestCase):
    def test_word_and_in_code_are_the_kits(self):
        img = made_up()
        self.assertIsNotNone(img._words, "the 32-bit view was not made (a big-endian host, or an image not a multiple of 4)")
        edges = {BASE - 4, BASE - 1, BASE, BASE + 1, BASE + 2, BASE + 3, img.end - 8, img.end - 4, img.end - 3, img.end,
                 img.end + 4, 0, 4}
        for lo, hi, _ in img.code:
            edges |= {lo - 4, lo - 1, lo, lo + 1, lo + 4, hi - 4, hi - 1, hi, hi + 4}
        for a in sorted(set(range(BASE, img.end + 8)) | edges):
            self.assertEqual(img.in_code(a), nx_image.NxImage.in_code(img, a), "in_code(%#x)" % a)
            if BASE <= a <= img.end - 4:
                self.assertEqual(img.word(a), nx_image.NxImage.word(img, a), "word(%#x)" % a)
            else:   # (outside the image: whatever NxImage does, error or not)
                self.assertEqual(kit_answer(img.word, a), kit_answer(nx_image.NxImage.word, img, a), "word(%#x)" % a)


class ClassifyTests(unittest.TestCase):
    def test_classify_is_the_kits(self):
        self.assertFalse(insn._installed)
        kit_classify = a64_lift.classify   # (the kit's, before nx2/insn.py's)
        insn.install()
        self.assertIsNot(a64_lift.classify, kit_classify)
        rng = random.Random(11)
        words = [0x14000010, 0x94000010, 0x17fffff0, 0x54000081, 0xb4000040, 0x35000040, 0x36080040, 0x37f80040,
                 0xd61f0220, 0xd63f00a0, 0xd65f03c0, 0xd65f0bff, 0xd65f0fff, 0xd61f0a1f, 0xd63f081f, 0xd4000001,
                 0xd4200000, 0xd4400000, 0xd5033fdf, 0xd50b7520, 0x91000400, 0xf9400022, 0x1e212800, 0xd503201f]
        words += [rng.getrandbits(32) for _ in range(20000)]
        for w in words:
            for pc in (0x80001000, 0x80123450):
                want = insn.classify_ext(w, pc) or kit_classify(w, pc)
                self.assertEqual(a64_lift.classify(w, pc), want, "classify(%#010x, %#x)" % (w, pc))


if __name__ == "__main__":
    unittest.main()
