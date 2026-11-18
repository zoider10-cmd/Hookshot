"""nx2/build.py's back end files keyed by the headers they read (renderer_deps; the dev-loop proposal's A6): each is compiled
with -MD, and the next build names its object by the headers its depfile lists under gpu/vk, gpu/render, gpu/compat and suyu's
texture decoders, not by every header there. A header the file does not read changes nothing; one it reads, or one gone,
changes its key; a file with no depfile yet keeps the folders' blob; an object compiled now is cached under the key its new
depfile gives (rekey_depfiles), so the next build does not compile it again.

Nothing here runs a compiler or needs the game.

python -I -B tests/test_renderer_depfiles.py
"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
spec = importlib.util.spec_from_file_location("build_depfiles", ROOT / "nx2" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

BLOB = b"the folders' blob"

# (a compiler for the scenario below: the "object" is the source and every header it includes, one level, and the depfile
# names those headers, as clang -MD would)
FAKE_CC = r'''
import os, re, sys
args = sys.argv[1:]
src, obj = args[args.index("-c") + 1], args[args.index("-o") + 1]
text = open(src, "rb").read()
heads = [os.path.join(os.path.dirname(src), m.decode()) for m in re.findall(rb'#include "([^"]+)"', text)]
open(obj, "wb").write(text + b"".join(open(h, "rb").read() for h in heads))
esc = lambda p: p.replace("\\", "/").replace(" ", "\\ ")
open(obj[:-2] + ".d", "w").write("%s: %s\n" % (esc(obj), " ".join(esc(p) for p in [src] + heads)))
'''


class DepfileTests(unittest.TestCase):
    def test_clangs_depfile_is_read_as_clang_writes_it(self):
        # (what clang 23 wrote on Windows for a source and headers in folders with spaces: '/' and '\ ')
        text = ("C:\\Work\\dep\\ test\\a\\ b.o: \\\r\n"
                "  C:/Work/dep\\ test/a\\ b.c \\\r\n"
                "  C:/Work/dep\\ test/two\\ words.h \\\r\n"
                "  C:/Work/dep\\ test/sub\\ dir/inner.h\r\n")
        self.assertEqual(build.depfile_paths(text), ["C:/Work/dep test/a b.c", "C:/Work/dep test/two words.h",
                                                     "C:/Work/dep test/sub dir/inner.h"])
        self.assertEqual(build.depfile_paths("/w/vk_x.o: /w/vk_x.cpp /w/a$$b.h /w/c\\#d.h\n"),
                         ["/w/vk_x.cpp", "/w/a$b.h", "/w/c#d.h"])
        self.assertEqual(build.depfile_paths("no rule here"), [])

    def test_md_is_not_part_of_a_key(self):
        self.assertEqual(build.flag_text(["-O2", "-MD", "-DX"]), build.flag_text(["-O2", "-DX"]))

    def test_depfile_beside_the_object(self):
        self.assertEqual(build.depfile_of(os.path.join("obj", "vk_draw.o")), os.path.join("obj", "vk_draw.d"))


class RendererDepsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hookshot depfiles ")   # (a space in the path, as on Windows)
        self.addCleanup(self.temporary.cleanup)
        d = Path(self.temporary.name)
        self.vk, self.other, self.obj_dir = d / "gpu" / "vk", d / "elsewhere", d / "obj"
        for p in (self.vk, self.other, self.obj_dir):
            p.mkdir(parents=True)
        self.read = self.vk / "vk_present_rect.h"
        self.unread = self.vk / "vk_menu.h"
        self.outside = self.other / "vulkan.h"
        for p, text in ((self.read, "int a;\n"), (self.unread, "int b;\n"), (self.outside, "int c;\n")):
            p.write_bytes(text.encode())
        self.src = self.vk / "vk_present.cpp"
        self.src.write_bytes(b'#include "vk_present_rect.h"\n')
        self.obj = str(self.obj_dir / "vk_present.o")
        self.roots = (str(self.vk),)
        build._HEADER_DIGESTS.clear()

    def deps(self):
        build._HEADER_DIGESTS.clear()   # (a new build)
        return build.renderer_deps(BLOB, self.roots, self.obj)

    def write_depfile(self, *headers):
        esc = lambda p: str(p).replace("\\", "/").replace(" ", "\\ ")
        Path(build.depfile_of(self.obj)).write_text("%s: %s %s\n" % (esc(self.obj), esc(self.src), " ".join(esc(h) for h in headers)))

    def test_no_depfile_yet_keeps_the_blob(self):
        self.assertEqual(self.deps(), BLOB)

    def test_a_header_it_does_not_read_changes_nothing_and_one_it_reads_does(self):
        self.write_depfile(self.read, self.outside)
        first = self.deps()
        self.assertTrue(first.startswith(b"depfile:"))
        self.unread.write_bytes(b"int b; /* an edit */\n")
        self.outside.write_bytes(b"int c; /* not under the roots: the flags and the system headers' stamp count it */\n")
        self.assertEqual(self.deps(), first)
        self.read.write_bytes(b"int a; /* an edit */\n")
        self.assertNotEqual(self.deps(), first)

    def test_a_header_gone_changes_the_key(self):
        self.write_depfile(self.read)
        first = self.deps()
        self.read.unlink()
        self.assertNotEqual(self.deps(), first)

    def test_a_depfile_naming_nothing_under_the_folders_keeps_the_blob(self):
        self.write_depfile(self.outside)
        self.assertEqual(self.deps(), BLOB)

    def test_an_object_compiled_now_is_cached_under_its_new_depfiles_key(self):
        cache = Path(self.temporary.name) / "objcache"
        fl = ["-O2", "-MD"]
        planned = build.object_key(str(self.src), fl, BLOB)   # (no depfile when the build planned it)
        Path(self.obj).write_bytes(b"object")
        Path(self.obj + ".sha1").write_text(planned)
        self.write_depfile(self.read)   # (the compile wrote it)
        job = ("c++", str(self.src), self.obj, fl, BLOB)
        with mock.patch.object(build, "OBJ_CACHE", str(cache)), mock.patch.dict(build.DEPFILE_JOBS, {self.obj: (BLOB, self.roots, b"")}), \
                mock.patch.dict(build.PLANNED, {(str(self.src), self.obj): planned}):
            build._HEADER_DIGESTS.clear()
            build.rekey_depfiles([job])
        key = Path(self.obj + ".sha1").read_text()
        self.assertEqual(key, build.object_key(str(self.src), fl, self.deps()))
        self.assertNotEqual(key, planned)
        self.assertTrue((cache / (key + ".o")).exists())

    def test_an_object_not_of_this_build_is_left_alone(self):
        cache = Path(self.temporary.name) / "objcache"
        fl = ["-O2", "-MD"]
        Path(self.obj).write_bytes(b"object")
        Path(self.obj + ".sha1").write_text("0" * 40)   # (another build's: not this build's key for it)
        self.write_depfile(self.read)
        with mock.patch.object(build, "OBJ_CACHE", str(cache)), mock.patch.dict(build.DEPFILE_JOBS, {self.obj: (BLOB, self.roots, b"")}):
            build.rekey_depfiles([("c++", str(self.src), self.obj, fl, BLOB)])
        self.assertEqual(Path(self.obj + ".sha1").read_text(), "0" * 40)
        self.assertFalse(cache.exists())

    def test_an_include_added_taken_out_and_back_never_reuses_an_old_headers_object(self):
        """hckrman101's steps on #2706: an object keyed by the last compile's depfile, which lacks a header the new source reads,
        must not be cached by that key, or putting the include back after editing that header reuses the old header's object"""
        d = Path(self.temporary.name)
        cc_script = d / "fake_cc.py"
        cc_script.write_text(FAKE_CC)
        a_h, b_h = self.vk / "a.h", self.vk / "b.h"
        a_h.write_bytes(b"/* a v1 */\n")
        b_h.write_bytes(b"/* b v1 */\n")
        cache = d / "objcache"
        fl = [str(cc_script), "-MD"]

        def build_once():
            build._HEADER_DIGESTS.clear()
            build.PLANNED.clear()
            blob = build.tree_headers(*self.roots)
            deps = build.renderer_deps(blob, self.roots, self.obj)
            job = (sys.executable, str(self.src), self.obj, fl, deps)
            build.DEPFILE_JOBS[self.obj] = (blob, self.roots, b"")
            build.PLANNED[(str(self.src), self.obj)] = build.object_key(str(self.src), fl, deps)
            _, _, err = build.compile_one(job)
            self.assertIsNone(err)
            build.rekey_depfiles([job])
            return Path(self.obj).read_bytes()

        with mock.patch.object(build, "OBJ_CACHE", str(cache)), mock.patch.object(build, "GATE", None), \
                mock.patch.dict(build.DEPFILE_JOBS, {}):
            with_b = b'#include "a.h"\n#include "b.h"\n'
            self.src.write_bytes(b'#include "a.h"\n')
            build_once()                                   # 1. a.h only: its depfile says a.h
            self.src.write_bytes(with_b)
            self.assertIn(b"b v1", build_once())          # 2. b.h added (keyed by step 1's depfile: a.h alone)
            self.src.write_bytes(b'#include "a.h"\n')
            build_once()                                   # 3. taken out again: the depfile says a.h
            b_h.write_bytes(b"/* b v2 */\n")
            self.src.write_bytes(with_b)
            obj = build_once()                             # 4. b.h edited and the include back
            self.assertIn(b"b v2", obj, "an object built with the old b.h came back from the cache")
            self.assertNotIn(b"b v1", obj)
            stamp = Path(self.obj + ".sha1").read_text()
            self.assertNotEqual(stamp, build.DEPFILE_PENDING)
            self.assertTrue((cache / (stamp + ".o")).exists())

    def test_the_build_uses_them(self):
        """The back end's own files (not eden's, not sirit's) get -MD and renderer_deps; the re-keying follows the compile"""
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        loop = src[src.index("        for src in vk_sources():"):]
        loop = loop[:loop.index("        if NGX_SDK and not LINUX")]
        # (eden and sirit get neither -MD nor the renderer's play profile: both are in the one "if lib else" of the flags)
        # (since #629 eden and sirit take tp_vflags and tp_deps, the third-party objects' own)
        self.assertIn('(tp_vflags if lib else vflags + vk_pgo_flags) + ([] if lib else ["-MD"]) +', loop)
        self.assertIn("vk_lib_deps + tp_deps if lib else renderer_deps(vdeps, vdeps_roots, obj) + extras", loop)
        self.assertIn("DEPFILE_JOBS[obj] = (vdeps, vdeps_roots, extras)", loop)
        main = src[src.index("\ndef main("):]
        # (jobs: the back end's own objects are in it with the host's, tests/test_host_depfiles.py)
        self.assertIn("        jobs += vk_jobs\n", main)
        self.assertLess(main.index("    if still:\n        return 1"), main.index("rekey_depfiles(jobs)"))
        # (the objects rekey_depfiles caches by their depfile's key go to the object store with the rest)
        self.assertLess(main.index("rekey_depfiles(jobs)"), main.index('"object store: %d new objects to it" % object_store.share('))


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
