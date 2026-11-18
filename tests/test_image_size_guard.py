"""A game image past 2 GB fails the build instead of linking silently broken (nx2/build.py image_span, image_too_big).

The game's code reaches its data RIP-relative (a signed 32-bit offset). lld does not range-check those fixups on x86-64
COFF: lifted code compiled at -O0 linked a 2,262 MB hookshot.exe with no error, and the game read the wrong memory
(.data started past 2^31; `movq -0x7d457b8e(%rip)` landed 4 GB below .refptr.a64_dirty). Checked here, with
image_span/image_too_big cut out of build.py:
  - a PE's SizeOfImage and an ELF's PT_LOAD span are read right (made-up headers, both sides of the limit);
  - an image at or past 2 GB gives the "link FAILED" message and is deleted; one under it is kept;
  - a file that is neither gives None (no check, no deletion);
  - every link of the lifted code in build.py's main() (Linux, Windows, --dll) is followed by the check;
  - with clang and lld on this PC: a small program linked for Windows and Linux reads as a small image.

python -I -B tests/test_image_size_guard.py
"""
import ast
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "nx2" / "build.py"
NAMES = ("image_span", "image_too_big")


def guard():
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"), filename=str(BUILD_SCRIPT))
    body = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in NAMES) or
            (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "IMAGE_LIMIT" for t in n.targets))]
    found = {n.name for n in body if isinstance(n, ast.FunctionDef)}
    if found != set(NAMES) or len(body) != len(NAMES) + 1:
        raise AssertionError("%s should define IMAGE_LIMIT, %s" % (BUILD_SCRIPT, ", ".join(NAMES)))
    ns = {"os": os}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(BUILD_SCRIPT), "exec"), ns)
    return ns


def pe(size_of_image):
    """The headers of a PE32+ image whose OptionalHeader.SizeOfImage is size_of_image"""
    b = bytearray(0x200)
    b[:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, 0x80)
    b[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", b, 0x84, 0x8664, 1)          # (Machine, NumberOfSections)
    struct.pack_into("<H", b, 0x98, 0x20B)               # (OptionalHeader.Magic: PE32+)
    struct.pack_into("<I", b, 0x98 + 56, size_of_image)  # (SizeOfImage)
    return bytes(b)


def elf(loads):
    """An ELF64 little-endian file with a PT_LOAD per (vaddr, memsz), and one PT_NOTE far away (not counted)"""
    phs = [(1, v, m) for v, m in loads] + [(4, 0x7FFF00000000, 0x10)]
    b = bytearray(0x40 + 0x38 * len(phs))
    b[:4] = b"\x7fELF"
    b[4], b[5], b[6] = 2, 1, 1
    struct.pack_into("<Q", b, 0x20, 0x40)                # (e_phoff)
    struct.pack_into("<HH", b, 0x36, 0x38, len(phs))     # (e_phentsize, e_phnum)
    for i, (kind, vaddr, memsz) in enumerate(phs):
        o = 0x40 + 0x38 * i
        struct.pack_into("<I", b, o, kind)
        struct.pack_into("<Q", b, o + 0x10, vaddr)
        struct.pack_into("<Q", b, o + 0x28, memsz)
    return bytes(b)


class Case(unittest.TestCase):
    def setUp(self):
        self.ns = guard()
        tmp = tempfile.TemporaryDirectory(prefix="hookshot-image-guard-")
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def file(self, name, data):
        p = os.path.join(self.dir, name)
        Path(p).write_bytes(data)
        return p


class ReadsTheSpan(Case):
    def test_pe(self):
        self.assertEqual(self.ns["image_span"](self.file("a.exe", pe(0x8D6A0000))), 0x8D6A0000)

    def test_elf_from_lowest_to_highest_end(self):
        p = self.file("a", elf([(0x200000, 0x1000), (0x400000, 0x7FFF0000), (0x300000, 0x10)]))
        self.assertEqual(self.ns["image_span"](p), 0x400000 + 0x7FFF0000 - 0x200000)

    def test_neither(self):
        self.assertIsNone(self.ns["image_span"](self.file("a.txt", b"not an image" * 10)))
        self.assertIsNone(self.ns["image_span"](self.file("e", elf([]))))


class FailsPastTheLimit(Case):
    def test_the_cover_streams_image_fails_and_is_deleted(self):
        exe = self.file("hookshot.exe", pe(2262 * 2**20 + 0x80000))
        msg = self.ns["image_too_big"](exe)
        self.assertIsNotNone(msg)
        self.assertTrue(msg.startswith("link FAILED"), msg)
        self.assertIn("2262 MB", msg)
        self.assertFalse(os.path.exists(exe), "a broken image is left where it could be started")

    def test_at_the_limit_fails(self):
        self.assertIsNotNone(self.ns["image_too_big"](self.file("a.exe", pe(2**31))))
        self.assertIsNotNone(self.ns["image_too_big"](self.file("a", elf([(0x400000, 2**31)]))))

    def test_under_it_is_kept(self):
        for name, data in (("a.exe", pe(2**31 - 0x1000)), ("today.exe", pe(420 * 2**20)), ("a", elf([(0x400000, 2**31 - 1)]))):
            with self.subTest(name):
                p = self.file(name, data)
                self.assertIsNone(self.ns["image_too_big"](p))
                self.assertTrue(os.path.exists(p))

    def test_not_an_image_is_left_alone(self):
        p = self.file("a.exe", b"MZ")
        self.assertIsNone(self.ns["image_too_big"](p))
        self.assertTrue(os.path.exists(p))


class EveryGameLinkIsChecked(unittest.TestCase):
    def test_each_link_of_the_lifted_code_is_followed_by_the_check(self):
        """main() links the lifted code three ways (Linux hookshot, Windows hookshot.exe, --dll hookshot_game.dll): each
        image it writes with -o is checked before it is said to be linked"""
        import re
        src = BUILD_SCRIPT.read_text(encoding="utf-8")
        main = src[src.index("\ndef main("):]
        linked = re.findall(r'"-o", (exe|dll)\b', main)
        self.assertGreaterEqual(len(linked), 3, "build.py's main() links the game fewer ways than this test knows")
        for name in set(linked):
            self.assertEqual(main.count("image_too_big(%s)" % name), linked.count(name),
                             "a link of %s in build.py's main() is not followed by image_too_big(%s)" % (name, name))


class RealLinks(Case):
    def test_small_programs_read_small(self):
        clang = shutil.which("clang")
        if not clang:
            self.skipTest("no clang")
        src = self.file("t.c", b"int start(void) { return 0; }\n")
        for target, out, entry in (("x86_64-w64-mingw32", "t.exe", ["-Wl,/entry:start"]),
                                   ("x86_64-unknown-linux-gnu", "t", ["-Wl,--entry=start"])):
            with self.subTest(target):
                exe = os.path.join(self.dir, out)
                r = subprocess.run([clang, "--target=" + target, "-fuse-ld=lld", "-nostdlib", "-o", exe, src] + entry,
                                   capture_output=True, text=True)
                if r.returncode:
                    self.skipTest("cannot link for %s here: %s" % (target, (r.stdout + r.stderr)[-300:]))
                span = self.ns["image_span"](exe)
                self.assertIsNotNone(span)
                self.assertLess(span, 2**24)
                self.assertIsNone(self.ns["image_too_big"](exe))


if __name__ == "__main__":
    unittest.main()
