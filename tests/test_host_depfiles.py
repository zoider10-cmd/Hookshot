"""nx2/build.py's host files keyed by the headers they read (renderer_deps, as the back end's own files are; the dev-loop
proposal's A6, the host's half): each is compiled with -MD, and the next build names its object by the headers its depfile
lists under host/, the lifted headers, gpu/, opus's and zstd's, not by every host header. A host header a file does not read
changes nothing; a gpu/ header it does read changes its key (before, only three gpu headers were in the host's key, so an
edit to gpu/render/rx_nvn.h kept the host objects built with the old one). A file with no depfile yet is named by host_blob,
which now covers gpu/'s own headers too.

Nothing here runs a compiler or needs the game.

python -I -B tests/test_host_depfiles.py
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
sys.path.insert(0, str(ROOT / "tests"))   # (tests/srccut.py: python -I leaves this folder off the path)
import srccut  # noqa: E402

spec = importlib.util.spec_from_file_location("build_host_depfiles", ROOT / "nx2" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def esc(p):
    return str(p).replace("\\", "/").replace(" ", "\\ ")


class HostDepfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hookshot host depfiles ")
        top = Path(self.temporary.name)
        self.host, self.gpu, self.gen = top / "host", top / "gpu", top / "work" / "sa" / "gen"
        for d in (self.host / "posix", self.gpu / "render", self.gpu / "vk" / "eden", self.gpu / "third_party", self.gen):
            d.mkdir(parents=True)
        self.files = {
            "hos.h": self.host / "hos.h", "other.h": self.host / "other.h", "rx_nvn.h": self.gpu / "render" / "rx_nvn.h",
            "a64.h": self.gen / "a64.h", "eden.h": self.gpu / "vk" / "eden" / "eden.h",
            "suyu.h": self.gpu / "third_party" / "suyu.h", "posix.h": self.host / "posix" / "posix.h",
        }
        for name, path in self.files.items():
            path.write_text("int %s;\n" % name.replace(".", "_"))
        # (nvn_native.c reads hos.h, the renderer's NVN header and a lifted one; display.c reads other.h)
        self.nvn, self.display = self.host / "nvn_native.c", self.host / "display.c"
        self.nvn.write_text('#include "hos.h"\n#include "../gpu/render/rx_nvn.h"\n')
        self.display.write_text('#include "other.h"\n')
        self.obj_dir = top / "obj"
        self.obj_dir.mkdir()
        self.roots = (str(self.host), str(self.gen), str(self.gpu))
        self.depfile("nvn_native", self.nvn, "hos.h", "rx_nvn.h", "a64.h")
        self.depfile("display", self.display, "other.h")

    def tearDown(self):
        self.temporary.cleanup()

    def obj(self, name):
        return str(self.obj_dir / ("host_" + name + ".o"))

    def depfile(self, name, src, *headers):
        obj = self.obj(name)
        Path(build.depfile_of(obj)).write_text("%s: %s %s\n" % (
            esc(obj), esc(src), " ".join(esc(self.files[h]) for h in headers)))

    def deps(self, name):
        build._HEADER_DIGESTS.clear()
        return build.renderer_deps(b"blob", self.roots, self.obj(name))

    def blob(self):
        # (as main() makes host_blob, without the lifted headers' part)
        return build.tree_headers(str(self.host)) + build.tree_headers(str(self.gpu), skip=("eden", "sirit", "third_party"))

    def edit(self, name):
        self.files[name].write_text(self.files[name].read_text() + "/* an edit */\n")

    def test_a_host_header_compiles_only_the_files_that_read_it(self):
        nvn, display = self.deps("nvn_native"), self.deps("display")
        self.assertTrue(nvn.startswith(build.DEPFILE_DEPS) and display.startswith(build.DEPFILE_DEPS))
        self.edit("other.h")
        self.assertEqual(self.deps("nvn_native"), nvn, "a host header nvn_native.c does not read changed its key")
        self.assertNotEqual(self.deps("display"), display)

    def test_a_gpu_header_the_host_reads_changes_its_key(self):
        nvn, display = self.deps("nvn_native"), self.deps("display")
        self.edit("rx_nvn.h")
        self.assertNotEqual(self.deps("nvn_native"), nvn, "an edit to gpu/render/rx_nvn.h kept nvn_native.c's old object")
        self.assertEqual(self.deps("display"), display)

    def test_a_lifted_header_it_reads_changes_its_key(self):
        nvn = self.deps("nvn_native")
        self.edit("a64.h")
        self.assertNotEqual(self.deps("nvn_native"), nvn)

    def test_the_blob_covers_gpus_own_headers_but_not_eden_sirit_or_third_party(self):
        first = self.blob()
        for name in ("eden.h", "suyu.h"):
            self.edit(name)
            self.assertEqual(self.blob(), first, "%s is not the host's: it must not compile the host again" % name)
        self.edit("rx_nvn.h")
        second = self.blob()
        self.assertNotEqual(second, first)
        self.edit("posix.h")
        self.assertNotEqual(self.blob(), second, "host/posix's headers are in the blob")

    def test_no_depfile_yet_keeps_the_blob(self):
        Path(build.depfile_of(self.obj("display"))).unlink()
        self.assertEqual(self.deps("display"), b"blob")

    def test_the_build_uses_them(self):
        """The host's files get -MD, renderer_deps over host_roots and DEPFILE_JOBS; the blob covers host/ and gpu/"""
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        main = src[srccut.find(src, "\ndef main(", "nx2/build.py"):]
        part = srccut.between(main, "    host_roots = ", "    # libopus", "nx2/build.py main()")
        roots = part[:part.index("\n")]
        for root in ("HOST", "gen", "rt64", "GPU"):
            self.assertIn(root, roots)
        self.assertIn('host_blob = deps + tree_headers(HOST) + tree_headers(GPU, skip=("eden", "sirit", "third_party"))', part)
        self.assertIn("DEPFILE_JOBS[obj] = (host_blob, host_roots, extras)", part)
        self.assertIn('host_fl + ["-MD"', part)
        self.assertIn("renderer_deps(host_blob, host_roots, obj) + extras", part)
        self.assertIn("    rekey_depfiles(jobs)", main)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
