"""tools.lock and scripts/tools.py (docs/releases.md, "tools.lock"), with authored archives and no network: the lock in the
repository reads and names only https links; a bad line is refused; a tool comes from the first URL that gives the bytes the
lock names (the next one when upstream is gone or changed); the download cache is shared; only the archive's prefix is
unpacked, and nothing outside the install; a line is replaced in place; and the archives Hookshot assembles (Python with the
prompt packages, the CPM cache with dav1d, the third_party prebuilt files, the play profile) are deterministic and hold only
what they should. The Linux lines (linux-x64) unpack with their modes and relative links, a changed line is unpacked again,
and an archive packed from a folder is deterministic. builder/setup/setup.c, builder/linux/linux_tools.py and the
launcher's Core/ToolsLock.cs read the same lines.

    python -I tests/test_tools_lock.py
"""
import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tools", ROOT / "scripts" / "tools.py")
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)


def zip_of(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


class Lock(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tools-lock-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.out = io.StringIO()
        ctx = contextlib.redirect_stdout(self.out)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def test_the_repository_lock(self):
        lock = tools.load()
        self.assertTrue(lock)
        for t in lock:
            self.assertTrue(all(u.startswith("https://") for u in t.urls), t.name)
            self.assertIn(t.system, tools.SYSTEMS)
            # (Windows: under the builder's tools folder; Linux: where the AppImage had them, beside its usr/share/hookshot)
            if t.system == "windows-x64":
                self.assertTrue(t.dest.startswith("HookshotBuilder/tools/"), t.name)
            else:
                self.assertRegex(t.dest, r"^usr/(lib|share)/hookshot/[a-z0-9]+$", t.name)
                self.assertEqual(t.prefix, t.name, t.name)   # (scripts/tools.py pack: the folder's own name)
            # (the forge's copy first, from Cloudflare's edge and then from the forge itself, where it came from as the
            # fallback: never a repository we do not control alone)
            self.assertEqual(t.urls[:2], tools.store_urls(t), "%s: its copies in Hookshot's store are not its first URLs" % t.name)
            self.assertTrue(t.urls[0].startswith(tools.CDN + "/api/packages/"), t.name)
            self.assertTrue(all(not tools.in_store(u) and not u.startswith(tools.CDN) for u in t.urls[2:]), t.name)
        self.assertEqual(tools.named(lock, "llvm-mingw").prefix, "llvm-mingw-20261104-ucrt-x86_64")
        # (every tool the Linux builder needs is in the lock: the AppImage carries none, builder/linux/linux_tools.py)
        self.assertEqual(sorted(t.name for t in tools.of_system(lock, "linux-x64")), sorted(tools.REQUIRED["linux-x64"]))
        self.assertNotEqual(tools.named(lock, "emsdk", "linux-x64").sha256, tools.named(lock, "emsdk").sha256)
        # (the release workflow requires every tool; what is still to assemble is listed in RELEASING.md)
        with self.assertRaises(SystemExit):
            tools.named(lock, "nothing")

    def test_a_bad_line_is_refused(self):
        good = "tool zstd 1.0 windows-x64 %s 10 HookshotBuilder/tools/zstd - https://x/z.zip" % ("a" * 64)
        self.assertEqual(tools.parse(good)[0].prefix, "-")
        for bad in (good.replace("https://", "http://"), good.replace("a" * 64, "A" * 64), good.replace(" 10 ", " -1 "),
                    good.replace("HookshotBuilder/tools/zstd", "../zstd"), good.replace("HookshotBuilder/tools/zstd", "/etc"),
                    good.replace(" - ", " a/../b "), good.replace("windows-x64", "mac"), good + "\n" + good, "part x"):
            with self.assertRaises(SystemExit, msg=bad):
                tools.parse(bad)

    def test_fetch_tries_the_next_url_and_shares_the_cache(self):
        sha, size = zip_of(self.dir / "a.zip", {"t/x.txt": "x"})
        data = (self.dir / "a.zip").read_bytes()
        t = tools.parse("tool t 1 windows-x64 %s %d T t https://upstream/a.zip https://mirror/a.zip" % (sha, size))[0]
        asked = []

        def getter(url):
            asked.append(url)
            return b"changed upstream" if "upstream" in url else data
        path = tools.fetch(t, str(self.dir / "cache"), getter)
        self.assertEqual((Path(path).read_bytes(), asked), (data, ["https://upstream/a.zip", "https://mirror/a.zip"]))
        self.assertEqual(tools.fetch(t, str(self.dir / "cache"), lambda url: self.fail("downloaded again")), path)
        with self.assertRaises(SystemExit):
            tools.fetch(t, str(self.dir / "cache2"), lambda url: b"nothing right")

    def test_install_unpacks_only_the_prefix_and_stays_inside(self):
        sha, size = zip_of(self.dir / "a.zip", {"HookshotBuilder/tools/python/python.exe": "py", "HookshotBuilder/app.exe": "no"})
        t = tools.parse("tool python 3 windows-x64 %s %d HookshotBuilder/tools/python HookshotBuilder/tools/python https://x/a"
                        % (sha, size))[0]
        data = (self.dir / "a.zip").read_bytes()
        tools.install(str(self.dir / "install"), [t], str(self.dir / "cache"), lambda url: data)
        self.assertEqual(sorted(str(p.relative_to(self.dir / "install")) for p in (self.dir / "install").rglob("*") if p.is_file()),
                         [os.path.join(".tools", "python"), os.path.join("HookshotBuilder", "tools", "python", "python.exe")])
        self.assertEqual(tools.stamp_of(str(self.dir / "install"), "python"), sha)
        tools.install(str(self.dir / "install"), [t], str(self.dir / "cache"), lambda url: self.fail("again"))   # (there already)
        sha, size = zip_of(self.dir / "b.zip", {"p/../../evil.txt": "x"})
        bad = tools.parse("tool p 1 windows-x64 %s %d T p https://x/b" % (sha, size))[0]
        bdata = (self.dir / "b.zip").read_bytes()
        with self.assertRaises(SystemExit):
            tools.install(str(self.dir / "i2"), [bad], str(self.dir / "cache"), lambda url: bdata)
        self.assertFalse((self.dir / "evil.txt").exists())

    def test_a_changed_line_is_unpacked_again(self):
        install = self.dir / "install"
        sha, size = zip_of(self.dir / "a.zip", {"t/old.txt": "1"})
        old = tools.parse("tool t 1 linux-x64 %s %d usr/lib/hookshot/t t https://x/a" % (sha, size))[0]
        tools.install(str(install), [old], str(self.dir / "cache"), lambda url: (self.dir / "a.zip").read_bytes())
        sha, size = zip_of(self.dir / "b.zip", {"t/new.txt": "2"})
        new = tools.parse("tool t 2 linux-x64 %s %d usr/lib/hookshot/t t https://x/b" % (sha, size))[0]
        tools.install(str(install), [new], str(self.dir / "cache"), lambda url: (self.dir / "b.zip").read_bytes())
        self.assertEqual(sorted(p.name for p in (install / "usr/lib/hookshot/t").iterdir()), ["new.txt"])
        self.assertEqual(tools.stamp_of(str(install), "t"), sha)

    def test_systems_are_apart(self):
        lock = self.dir / "tools.lock"
        lines = ["tool cpm 1 windows-x64 %s 10 HookshotBuilder/tools/cpm cpm https://x/w" % ("a" * 64),
                 "tool cpm 1 linux-x64 %s 11 usr/share/hookshot/cpm cpm https://x/l" % ("b" * 64)]
        lock.write_text("\n".join(lines) + "\n")
        both = tools.load(str(lock))   # (one name on each system: not "twice")
        self.assertEqual((tools.named(both, "cpm").size, tools.named(both, "cpm", "linux-x64").size), (10, 11))
        self.assertEqual([t.system for t in tools.of_system(both, "linux-x64")], ["linux-x64"])
        with self.assertRaises(SystemExit):
            tools.parse(lines[1] + "\n" + lines[1])
        t = tools.named(both, "cpm", "linux-x64")
        t.version = "2"
        tools.write_line(t, str(lock))   # (the Linux line replaced, the Windows one kept)
        self.assertEqual([(x.system, x.version) for x in tools.load(str(lock))], [("windows-x64", "1"), ("linux-x64", "2")])

    def test_a_line_is_replaced_in_place(self):
        lock = self.dir / "tools.lock"
        shutil.copy(tools.LOCK, lock)
        before = lock.read_text()
        t = tools.named(tools.load(str(lock)), "cpm")
        t.version, t.urls = "dav1d", ["https://git.magicbean.dev/api/packages/MagicBeanDev/generic/cpm-windows-x64/dav1d/x.zip"]
        tools.write_line(t, str(lock))
        after = lock.read_text()
        self.assertEqual(len(after.splitlines()), len(before.splitlines()))
        self.assertIn("tool cpm dav1d windows-x64", after)
        self.assertTrue(after.startswith("# "))
        tools.write_line(tools.Tool("profile", "1", "windows-x64", "b" * 64, 5, "HookshotBuilder/tools/work", "work",
                                    ["https://git.magicbean.dev/api/packages/MagicBeanDev/generic/profile-windows-x64/1/p.zip"]), str(lock))
        self.assertEqual(tools.named(tools.load(str(lock)), "profile").prefix, "work")

    def test_the_store_is_the_package_registry(self):
        t = tools.parse("tool emsdk 23.1.5 linux-x64 %s 10 usr/lib/hookshot/emsdk emsdk https://x/e" % ("a" * 64))[0]
        url = "https://git.magicbean.dev/api/packages/MagicBeanDev/generic/emsdk-linux-x64/23.1.5/" + "a" * 64 + "-emsdk.zip"
        self.assertEqual(tools.store_url(t), url)
        self.assertTrue(tools.in_store(url) and not tools.in_store("https://github.com/x/y.zip"))
        # (the upload: one PUT to the address without Cloudflare when it is set; a copy there already of the same size is kept)
        archive = self.dir / "e.zip"
        archive.write_bytes(b"0123456789")
        sent = []

        class Answer(object):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout):
            sent.append((req.get_method(), req.full_url))
            return Answer()
        with mock.patch.dict(os.environ, {"RELEASE_TOKEN": "t", "FORGEJO_UPLOAD_API": "http://forgejo:3000/api/v1"}), \
                mock.patch.object(tools.urllib.request, "urlopen", urlopen):
            self.assertEqual(tools.store(str(archive), t), url)
        self.assertEqual(sent, [("PUT", url.replace("https://git.magicbean.dev", "http://forgejo:3000"))])

        def conflict(req, timeout):
            raise tools.urllib.error.HTTPError(req.full_url, 409, "exists", {}, io.BytesIO(b""))
        with mock.patch.dict(os.environ, {"RELEASE_TOKEN": "t"}), mock.patch.object(tools.urllib.request, "urlopen", conflict):
            with mock.patch.object(tools, "exists", lambda u: (True, 10, "a" * 64)):
                self.assertEqual(tools.store(str(archive), t), url)
            with mock.patch.object(tools, "exists", lambda u: (True, 10, "c" * 64)), self.assertRaises(SystemExit):
                tools.store(str(archive), t)   # (a version's file never changes: other bytes need a new version)

    def test_check_requires_every_tool(self):
        lock = self.dir / "tools.lock"
        lock.write_text("tool llvm-mingw 1 windows-x64 %s 10 HookshotBuilder/tools/llvm-mingw - https://x/l\n" % ("a" * 64))
        self.assertEqual(tools.main(["--lock", str(lock), "check"]), 0)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(tools.main(["--lock", str(lock), "check", "--require"]), 1)
        self.assertIn("sysroot (linux-x64)", err.getvalue())   # (each system's tools)
        full = [("windows-x64", n, "HookshotBuilder/tools/" + n) for n in tools.REQUIRED["windows-x64"]] + \
               [("linux-x64", n, "usr/lib/hookshot/" + n) for n in tools.REQUIRED["linux-x64"]]
        lock.write_text("".join("tool %s 1 %s %s 10 %s - https://x/%s\n" % (n, s, "a" * 64, d, n) for s, n, d in full))
        self.assertEqual(tools.main(["--lock", str(lock), "check", "--require"]), 0)
        # (a line's copy in the store must answer, with its size; upstream links are not asked)
        t = tools.parse("tool zlib 1 linux-x64 %s 10 usr/lib/hookshot/zlib zlib https://x/z" % ("b" * 64))[0]
        with open(lock, "a") as f:
            f.write("tool zlib 1 linux-x64 %s 10 usr/lib/hookshot/zlib zlib %s\n" % ("b" * 64, " ".join(tools.store_urls(t))))
        asked = []
        for answer, rc in (((True, 10, "b" * 64), 0), ((False, None, None), 1), ((True, 9, "b" * 64), 1), ((True, 10, "c" * 64), 1)):
            with mock.patch.object(tools, "exists", lambda u, answer=answer: asked.append(u) or answer), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tools.main(["--lock", str(lock), "check", "--require"]), rc, answer)
            self.assertEqual(rc == 1, "zlib (linux-x64)" in err.getvalue())
        self.assertEqual(asked, [tools.store_url(t)] * 4)   # (the store's own address: the edge's copy is the same file)
        # (a line with the store's copy but not the edge's first fails: every player would download it from the forge)
        good = lock.read_text()
        lock.write_text(good.replace(" ".join(tools.store_urls(t)), tools.store_url(t)))
        with mock.patch.object(tools, "exists", lambda u: (True, 10, "b" * 64)), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(tools.main(["--lock", str(lock), "check", "--require"]), 1)
        self.assertIn("zlib (linux-x64): its first URLs are not", err.getvalue())
        lock.write_text(good)
        # (the play profile is optional: a release is made without one, and the game built without it)
        self.assertNotIn("profile", tools.REQUIRED["windows-x64"] + tools.REQUIRED["linux-x64"])
        self.assertIn("work/hot_order.txt", [n for n in ("work/" + f for f in tools.PROFILE)])   # (assemble profile stays)
        lock.write_text("".join("tool %s 1 %s %s 10 %s - https://x/%s\n" % (n, s, "a" * 64, d, n) for s, n, d in full
                                if (s, n) != ("linux-x64", "emsdk")))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(tools.main(["--lock", str(lock), "check", "--require"]), 1)
        self.assertIn("emsdk (linux-x64)", err.getvalue())


@unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "modes and links: the Linux tools")
class Pack(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tools-pack-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        ctx = contextlib.redirect_stdout(io.StringIO())
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.tool = self.dir / "src" / "emsdk"
        (self.tool / "upstream/bin").mkdir(parents=True)
        (self.tool / "upstream/bin/clang-23").write_text("#!/bin/sh\n")
        (self.tool / "upstream/bin/clang-23").chmod(0o755)
        (self.tool / "LICENSE.TXT").write_text("license")
        os.symlink("clang-23", self.tool / "upstream/bin/clang")
        os.symlink("upstream/bin", self.tool / "bin")   # (a link to a folder stays a link)

    def test_modes_and_links_round_trip(self):
        sha, size = tools.pack(str(self.tool), str(self.dir / "a.zip"))
        self.assertEqual((sha, size), (tools.sha256_file(str(self.dir / "a.zip")), (self.dir / "a.zip").stat().st_size))
        again = tools.pack(str(self.tool), str(self.dir / "b.zip"))
        self.assertEqual(again, (sha, size))   # (deterministic)
        with zipfile.ZipFile(self.dir / "a.zip") as z:
            self.assertTrue(all(n.startswith("emsdk/") for n in z.namelist()))
        t = tools.parse("tool emsdk 1 linux-x64 %s %d usr/lib/hookshot/emsdk emsdk https://x/a" % (sha, size))[0]
        tools.install(str(self.dir / "install"), [t], str(self.dir / "cache"), lambda url: (self.dir / "a.zip").read_bytes())
        out = self.dir / "install/usr/lib/hookshot/emsdk"
        self.assertTrue(os.access(out / "upstream/bin/clang-23", os.X_OK))
        self.assertFalse(os.access(out / "LICENSE.TXT", os.X_OK))
        self.assertEqual(os.readlink(out / "upstream/bin/clang"), "clang-23")
        self.assertEqual(os.readlink(out / "bin"), "upstream/bin")
        self.assertEqual((out / "bin" / "clang").read_text(), "#!/bin/sh\n")

    def test_a_link_that_leaves_is_refused(self):
        for target in ("/usr/bin/clang", "../../outside", "upstream/../../x"):
            os.symlink(target, self.tool / "bad")
            with self.assertRaises(SystemExit, msg=target):
                tools.pack(str(self.tool), str(self.dir / "bad.zip"))
            os.remove(self.tool / "bad")
        # (and an archive made elsewhere with one is refused when it is unpacked, before anything is written outside)
        with zipfile.ZipFile(self.dir / "evil.zip", "w") as z:
            info = zipfile.ZipInfo("t/link")
            info.create_system, info.external_attr = 3, 0o120777 << 16
            z.writestr(info, "../../../etc")
        with self.assertRaises(SystemExit):
            tools.unpack(str(self.dir / "evil.zip"), "t", str(self.dir / "t"))
        self.assertFalse((self.dir / "t").exists())


class Assemble(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="tools-assemble-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        ctx = contextlib.redirect_stdout(io.StringIO())
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def test_cpm_gets_dav1d_once(self):
        zip_of(self.dir / "cpm.zip", {"HookshotBuilder/tools/cpm/ffmpeg/9/lib/avcodec.lib": "ffmpeg"})
        add = self.dir / "add" / "dav1d" / "1.5.4" / "lib"
        add.mkdir(parents=True)
        (add / "libdav1d.a").write_bytes(b"!<arch>\n")
        t = tools.Tool("cpm", "1", "windows-x64", "a" * 64, 1, "HookshotBuilder/tools/cpm", "HookshotBuilder/tools/cpm", ["https://x"])
        first = tools.assemble_cpm(t, str(self.dir / "cpm.zip"), str(self.dir / "add"), str(self.dir / "new.zip"))
        with zipfile.ZipFile(self.dir / "new.zip") as z:
            self.assertEqual(sorted(z.namelist()), ["cpm/dav1d/1.5.4/lib/libdav1d.a", "cpm/ffmpeg/9/lib/avcodec.lib"])
        again = tools.assemble_cpm(t, str(self.dir / "cpm.zip"), str(self.dir / "add"), str(self.dir / "again.zip"))
        self.assertEqual(first, again)                                   # (deterministic)
        t2 = tools.Tool("cpm", "2", "windows-x64", "a" * 64, 1, "HookshotBuilder/tools/cpm", "cpm", ["https://x"])
        self.assertIsNone(tools.assemble_cpm(t2, str(self.dir / "new.zip"), str(self.dir / "add"), str(self.dir / "n.zip")))

    def test_python_gets_the_missing_pins_for_its_version(self):
        zip_of(self.dir / "py.zip", {"HookshotBuilder/tools/python/python314.dll": "dll",
                                     "HookshotBuilder/tools/python/Lib/site-packages/pillow-13.0.0.dist-info/METADATA": "m"})
        req = self.dir / "req.txt"
        req.write_text("pillow==13.0.0\nfonttools==4.68.0  # a comment\n")
        t = tools.Tool("python", "1", "windows-x64", "a" * 64, 1, "HookshotBuilder/tools/python", "HookshotBuilder/tools/python", ["https://x"])
        ran = []

        def pip(args, check):
            ran.append(args)
            target = Path(args[args.index("--target") + 1])
            (target / "fontTools").mkdir(parents=True)
            (target / "fontTools" / "__init__.py").write_text("")
        tools.assemble_python(t, str(self.dir / "py.zip"), str(req), str(self.dir / "new.zip"), pip=pip)
        self.assertEqual(ran[0][-1], "fonttools==4.68.0")
        self.assertIn("3.14", ran[0])
        self.assertIn("win_amd64", ran[0])
        with zipfile.ZipFile(self.dir / "new.zip") as z:
            self.assertIn("python/Lib/site-packages/fontTools/__init__.py", z.namelist())
            self.assertIn("python/python314.dll", z.namelist())

    def test_third_party_keeps_only_prebuilt_files(self):
        zip_of(self.dir / "tp.zip", {"HookshotBuilder/tools/third_party/a64-kit/lift/a64emit.dll": "dll",
                                     "HookshotBuilder/tools/third_party/a64-kit/lift/a64_lift.py": "Hookshot's source",
                                     "HookshotBuilder/tools/third_party/sdl2/SDL3.dll": "sdl"})
        tools.assemble_third_party(str(self.dir / "tp.zip"), "HookshotBuilder/tools/third_party", str(self.dir / "o.zip"),
                                   {"third_party/a64-kit/lift/a64_lift.py"})
        with zipfile.ZipFile(self.dir / "o.zip") as z:
            self.assertEqual(sorted(z.namelist()), ["third_party/a64-kit/lift/a64emit.dll", "third_party/sdl2/SDL3.dll"])

    def test_the_profile(self):
        work = self.dir / "work"
        work.mkdir()
        for n in ("hot_order.txt", "hookshot_pieces.prof", "image.bin", "dump.txt"):
            (work / n).write_text(n)
        tools.assemble_profile(str(work), str(self.dir / "p.zip"))
        with zipfile.ZipFile(self.dir / "p.zip") as z:
            self.assertEqual(sorted(z.namelist()), ["work/hot_order.txt", "work/hookshot_pieces.prof"])   # (nothing of the game)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
