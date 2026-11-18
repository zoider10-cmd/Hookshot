"""nx2/build.py's links skipped when what they read and write is as the last successful link left it (run_link; the dev-loop
proposal's A4). The record beside the output (<output>.linkkey): the key (the command, the compiler, each object's key, the
files the command names by content), every file the linker itself says it read (the libraries it found by search path and
the runtime's archives too), the linker program, and the outputs (the binary and its maps) by size, time and file id. A
changed library reached through -L/-l, a map deleted, a file written over the output, another linker, or a failed link: the
link runs again.

Two halves: a stand-in "linker" (this Python, which lists what it reads as lld's MinGW driver does when verbose) for every
case, counted; and, given --cxx, real links with that compiler: an archive found through -L/-l replaced with another
implementation, and a map deleted.

python -I -B tests/test_link_skip.py [--cxx clang++]
"""
import argparse
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
spec = importlib.util.spec_from_file_location("build_link_skip", ROOT / "nx2" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
CXX = None

# (the stand-in: writes the output and the map the command asks for, says "Reading <file>" for every file it is given and for
# the runtime archive it "finds by search path" (LINK_RUNTIME, never on its command), and counts its runs)
LINKER = ("import os, sys\n"
          "out, runs = sys.argv[1], os.environ['LINK_RUNS']\n"   # (the count by the environment: a named file would be an input)
          "open(runs, 'a').write('x')\n"
          "if os.path.exists(runs + '.fail'): sys.exit(1)\n"
          "open(out, 'wb').write(b'linked ' + open(os.environ['LINK_RUNTIME'], 'rb').read())\n"
          "for a in sys.argv[2:]:\n"
          "    if '/map:' in a: open(a.split('/map:', 1)[1], 'w').write('map')\n"
          "    p = a[1:] if a.startswith('@') else a\n"
          "    if os.path.isfile(p): print('lld-link: Reading ' + p)\n"
          "    if a.startswith('@'):\n"
          "        for o in open(p).read().split(): print('lld-link: Reading ' + o.strip('\"'))\n"
          "print('lld-link: Reading ' + os.environ['LINK_RUNTIME'])\n"
          "print('lld-link: Loaded runtime.a(member.o) for something')\n")


class LinkSkipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hookshot link skip ")
        self.addCleanup(self.temporary.cleanup)
        d = Path(self.temporary.name)
        self.d, self.out, self.runs = d, str(d / "hookshot.exe"), str(d / "runs.txt")
        self.map = self.out[:-4] + ".map"
        self.obj = d / "a.o"
        self.obj.write_bytes(b"object")
        (d / "a.o.sha1").write_text("1" * 40)
        self.rsp = d / "objs.rsp"
        self.rsp.write_text('"%s"' % str(self.obj).replace("\\", "/"), encoding="utf-8")
        self.lib = d / "lib.a"
        self.lib.write_bytes(b"library")
        self.runtime = d / "toolchain" / "libruntime.a"   # (found by search path: on no command line)
        self.runtime.parent.mkdir()
        self.runtime.write_bytes(b"runtime 1")
        self.order = d / "hot_order.txt"
        self.order.write_text("f_80000000\n")
        self.script = d / "linker.py"
        self.script.write_text(LINKER)
        self.program = d / "ld.lld"   # (the linker program -### names)
        self.program.write_bytes(b"lld 1")

    def link(self, fail=False):
        """(fail: the linker fails, told by a file beside its count: not by its command, which is part of the key)"""
        if fail:
            Path(self.runs + ".fail").write_text("")
        elif os.path.exists(self.runs + ".fail"):
            os.remove(self.runs + ".fail")
        cmd = [sys.executable, str(self.script), self.out, "@" + str(self.rsp), str(self.lib),
               "-Xlinker", "-Xlink=/order:@" + str(self.order), "-Xlinker", "-Xlink=/map:" + self.map]
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.dict(os.environ, {"LINK_RUNS": self.runs, "LINK_RUNTIME": str(self.runtime)}), \
                mock.patch.object(build, "link_trace", lambda cmd: []), \
                mock.patch.object(build, "link_program", lambda cmd: str(self.program)):
            self.result = build.run_link(cmd, self.out)
        return self.result.returncode

    def count(self):
        return len(Path(self.runs).read_text()) if os.path.exists(self.runs) else 0

    def test_the_same_inputs_are_not_linked_again(self):
        self.assertEqual((self.link(), self.count()), (0, 1))
        self.assertEqual((self.link(), self.count()), (0, 1))

    def test_the_linkers_list_is_not_its_output(self):
        self.link()
        self.assertNotIn("Reading", self.result.stdout)
        self.assertNotIn("Loaded", self.result.stdout)

    def test_a_changed_object_library_or_symbol_order_is_linked_again(self):
        self.link()
        for change in (lambda: (self.d / "a.o.sha1").write_text("2" * 40), lambda: self.lib.write_bytes(b"library 2"),
                       lambda: self.order.write_text("f_80000004\n")):
            before = self.count()
            change()
            self.link()
            self.assertEqual(self.count(), before + 1)

    def test_a_library_found_by_search_path_is_an_input(self):
        """(mooki on #30: -l, -static-libstdc++, the runtime's archives: none is on the command line, the linker finds them)"""
        self.link()
        self.runtime.write_bytes(b"runtime 2")
        os.utime(self.runtime, ns=(1, 1))   # (another time too, whatever the file system's clock step)
        self.link()
        self.assertEqual(self.count(), 2)
        self.assertTrue(Path(self.out).read_bytes().endswith(b"runtime 2"))

    def test_another_linker_program_links_again(self):
        self.link()
        self.program.write_bytes(b"lld 2, a newer one")
        self.link()
        self.assertEqual(self.count(), 2)

    def test_a_map_deleted_is_written_again(self):
        """(mooki on #30: the build asks every link for a map, which prof.py and samap.py read)"""
        self.link()
        os.remove(self.map)
        self.link()
        self.assertEqual(self.count(), 2)
        self.assertTrue(os.path.exists(self.map))

    def test_an_output_written_over_or_gone_is_linked_again(self):
        """(HumanBean on #30: a file of the same size written over it is not the link's output)"""
        self.link()
        size = os.path.getsize(self.out)
        Path(self.out).write_bytes(b"x" * size)
        os.utime(self.out, ns=(1, 1))
        self.link()
        self.assertEqual(self.count(), 2)
        os.remove(self.out)
        self.link()
        self.assertEqual(self.count(), 3)

    def test_no_list_from_the_linker_keeps_no_record(self):
        """A linker this does not know how to ask (link_trace None), or one that names no file: always linked"""
        cmd = [sys.executable, str(self.script), self.out]
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.dict(os.environ, {"LINK_RUNS": self.runs, "LINK_RUNTIME": str(self.runtime)}), \
                mock.patch.object(build, "link_trace", lambda cmd: None), \
                mock.patch.object(build, "link_program", lambda cmd: str(self.program)):
            build.run_link(cmd, self.out)
            build.run_link(cmd, self.out)
        self.assertEqual(self.count(), 2)
        self.assertFalse(os.path.exists(self.out + ".linkkey"))

    def test_a_failed_link_forgets_the_key(self):
        self.link()
        self.assertEqual(self.link(fail=True), 0)   # (skipped: the inputs are the last good link's)
        (self.d / "a.o.sha1").write_text("3" * 40)
        self.assertEqual(self.link(fail=True), 1)
        self.assertFalse(os.path.exists(self.out + ".linkkey"))

    def test_the_files_inside_options_are_inputs_and_the_maps_outputs(self):
        cmd = ["clang", "@" + str(self.rsp), "-Xlink=/order:@" + str(self.order), "--symbol-ordering-file=" + str(self.order),
               str(self.lib), "-o", self.out, "-Xlink=/map:" + self.map, "-Wl,-Map=" + self.out + ".map", "/map:other.map"]
        objs, others = build.link_inputs(cmd, self.out)
        self.assertEqual(objs, [str(self.obj).replace("\\", "/")])
        self.assertIn(str(self.order), others)
        self.assertIn(str(self.lib), others)
        self.assertNotIn(self.out, others)
        self.assertEqual(build.link_maps(cmd), [self.map, self.out + ".map", "other.map"])

    def test_the_linkers_lists_are_read(self):
        lld_mingw = ("lld-link -lldmingw -out:x.exe\nld.lld: Reading %s\nld.lld: Reading lib.a(member.o)\n"
                     "ld.lld: Loaded lib.a(member.o) for foo\nld.lld: error: undefined symbol: bar\n" % self.lib)
        files, rest = build.traced_files(lld_mingw)
        self.assertEqual(files, [os.path.abspath(self.lib)])
        self.assertEqual(rest, "ld.lld: error: undefined symbol: bar\n")
        elf = "%s\n%s(member.o)\nld.lld: warning: something\n" % (self.runtime, self.lib)   # (lld's and GNU ld's --trace)
        files, rest = build.traced_files(elf)
        self.assertEqual(files, [os.path.abspath(self.runtime), os.path.abspath(self.lib)])
        self.assertEqual(rest, "ld.lld: warning: something\n")
        files, rest = build.traced_files("/usr/bin/ld: mode elf_x86_64\n-lruntime (%s)\n" % self.runtime)   # (GNU ld's -t)
        self.assertEqual(files, [os.path.abspath(self.runtime)])
        self.assertEqual(rest, "/usr/bin/ld: mode elf_x86_64\n")

    def test_the_compile_commands_are_the_compiles(self):
        import json
        gen = self.d / "gen"
        jobs = [("clang", str(self.d / "a.c"), str(self.obj), ["-O1", "-Ifoo"], b"deps"),
                ("clang", str(gen / "code_000.c"), str(self.d / "code_000.o"), ["-O1"], b"deps")]
        build.write_compdb(str(self.d), jobs, str(gen))
        entries = json.loads((self.d / build.COMPDB).read_text(encoding="utf-8"))
        self.assertEqual(entries, [{"directory": os.getcwd(), "file": str(self.d / "a.c"), "output": str(self.obj),
                                    "arguments": ["clang", "-O1", "-Ifoo", "-c", str(self.d / "a.c"), "-o", str(self.obj)]}])
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        main = src[src.index("\ndef main("):]
        self.assertLess(main.index("write_compdb(out, jobs, gen)"), main.index("plan_jobs(jobs)"))
        one = src[src.index("\ndef compile_one("):src.index("\ndef ", src.index("\ndef compile_one(") + 1)]
        # (compile_one's own command: the same compiler and flags; since #385 its file can be a temporary copy, c_src, and the
        # database names the source, which an editor can still open)
        self.assertIn('[cc] + fl + ["-c", c_src, "-o", obj]', one)

    def test_the_build_links_through_it(self):
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        tail = src[src.index("    vk_objs = {j[2] for j in vk_jobs}"):]
        self.assertEqual(tail.count("run_link("), 3)   # (the exe on Linux and on Windows, the back end's library)


class RealLinkTests(unittest.TestCase):
    """With a real compiler and its linker: an archive reached only through -L/-l, replaced; a map deleted"""

    def setUp(self):
        if not CXX:
            self.skipTest("no --cxx")
        self.temporary = tempfile.TemporaryDirectory(prefix="hookshot real link ")
        self.addCleanup(self.temporary.cleanup)
        self.d = Path(self.temporary.name)
        here = os.path.dirname(shutil.which(CXX) or CXX)
        self.ar = next((p for p in (os.path.join(here, "llvm-ar"), os.path.join(here, "llvm-ar.exe"), shutil.which("llvm-ar"),
                                    shutil.which("ar")) if p and os.path.isfile(p)), None)
        if not self.ar:
            self.skipTest("no archiver beside %s" % CXX)
        (self.d / "lib").mkdir()
        (self.d / "main.cpp").write_text('extern "C" const char *which();\nint main() { return which()[0] == 0; }\n')
        self.cc(self.d / "main.cpp", self.d / "main.o")
        (self.d / "main.o.sha1").write_text("1" * 40)
        self.archive("ONE_IMPLEMENTATION")
        self.out = str(self.d / ("prog.exe" if os.name == "nt" else "prog"))
        self.map = str(self.d / "prog.map")

    def cc(self, src, obj):
        subprocess.run([CXX, "-c", str(src), "-o", str(obj)], check=True, capture_output=True)

    def archive(self, text):
        (self.d / "which.cpp").write_text('extern "C" const char *which() { return "%s"; }\n' % text)
        self.cc(self.d / "which.cpp", self.d / "which.o")
        lib = self.d / "lib" / "libwhich.a"
        if lib.exists():
            lib.unlink()
        subprocess.run([self.ar, "rcs", str(lib), str(self.d / "which.o")], check=True, capture_output=True)

    def link(self):
        cmd = [CXX, "-o", self.out, str(self.d / "main.o"), "-L" + str(self.d / "lib"), "-lwhich", "-Wl,-Map=" + self.map]
        with contextlib.redirect_stdout(io.StringIO()) as said:
            r = build.run_link(cmd, self.out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return "not linked again" in said.getvalue()

    def test_an_archive_found_by_search_path_replaced_is_linked_in(self):
        self.assertFalse(self.link())
        self.assertTrue(os.path.exists(self.out + ".linkkey"), "the linker's list was not read: no record kept")
        self.assertTrue(self.link(), "the same link ran again")
        self.archive("TWO_IMPLEMENTATION")
        self.assertFalse(self.link())
        data = Path(self.out).read_bytes()
        self.assertIn(b"TWO_IMPLEMENTATION", data)
        self.assertNotIn(b"ONE_IMPLEMENTATION", data)

    def test_a_map_deleted_is_written_again(self):
        self.assertFalse(self.link())
        os.remove(self.map)
        self.assertFalse(self.link())
        self.assertTrue(os.path.exists(self.map))
        self.assertTrue(self.link())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cxx")
    a, rest = p.parse_known_args()
    CXX = a.cxx
    raise SystemExit(unittest.main(argv=[sys.argv[0]] + rest, verbosity=1))
