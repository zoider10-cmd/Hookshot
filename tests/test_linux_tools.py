"""The Linux builder's build tools (builder/linux/linux_tools.py, builder/linux/AppRun), with authored archives and no network:
the AppImage carries none of tools.lock's linux-x64 tools. They are found where the Hookshot Launcher unpacked them (beside
the builder, or in its own copy of the version), else in the builder's toolchains folder, where the first start downloads
them, checked by their SHA-256, with progress, and where a later start finds them with no connection. A tool another
version has is linked, not downloaded again. AppRun's --cli (RecompLauncher's --cli --prepare) gets them first and stops
without them; --play and --launch need none, and anything else is a message: the AppImage has no window.

    python -I -B tests/test_linux_tools.py
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

RUN_ALL_SKIP = {"windows": "the Linux builder's start (sh, links)"}

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("linux_tools", ROOT / "builder" / "linux" / "linux_tools.py")
linux_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linux_tools)
tools = linux_tools.tools
TAG = "v3.1.0"


def archive(path, top, files):
    """A tool's archive as scripts/tools.py pack makes it: files under top/, executable ones 0755"""
    with zipfile.ZipFile(path, "w") as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(top + "/" + name)
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith("clang") else 0o100644) << 16
            z.writestr(info, data)
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data), data


@unittest.skipUnless(os.name == "posix", "the Linux builder")
class Tools(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hookshot-linux-tools-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.data = {}
        self.app = self.dir / "AppDir"   # (the mounted AppImage: read-only on a player's PC)
        self.share = self.app / "usr/share/hookshot"
        self.share.mkdir(parents=True)
        (self.app / "AppRun").write_text("#!/bin/sh\n")
        (self.share / "VERSION").write_text(TAG + "\n")
        self.env = {"HOOKSHOT_BUILDER_HOME": str(self.dir / "data"), "HOOKSHOT_LAUNCHER_HOME": str(self.dir / "launcher"),
                    "HOME": str(self.dir / "home")}
        self.write_lock(emsdk="clang 1", sdl2="sdl 1")
        self.asked = []

    def write_lock(self, **contents):
        lines = []
        for name, text in contents.items():
            files = {"emsdk": {"upstream/bin/clang": "#!/bin/sh\n" + text}, "sdl2": {"libSDL2-2.0.so.0": text}}[name]
            sha, size, data = archive(self.dir / ("%s-%s.zip" % (name, text.replace(" ", ""))), name, files)
            self.data["https://tools.example/" + sha] = data
            dest = "usr/lib/hookshot/" + name
            lines.append("tool %s 1 linux-x64 %s %d %s %s https://tools.example/%s" % (name, sha, size, dest, name, sha))
        lines.append("tool emsdk 1 windows-x64 %s 10 HookshotBuilder/tools/emsdk emsdk https://tools.example/w" % ("c" * 64))
        (self.share / "tools.lock").write_text("\n".join(lines) + "\n")

    def getter(self, url):
        self.asked.append(url)
        if url not in self.data:
            raise OSError("no connection")
        return self.data[url]

    def offline(self, url):
        self.asked.append(url)
        raise OSError("no connection")

    def ensure(self, install=True, getter=None, say=None):
        said = []
        found, error = linux_tools.ensure(install, say or (lambda text, fraction: said.append((text, fraction))),
                                          str(self.share), self.env, getter or self.getter)
        return {t.name: root for t, root in found.items()}, error, said

    def env_of(self, found):
        return linux_tools.environment({t: found[t.name] for t in linux_tools.lock(str(self.share)) if found[t.name]})

    def test_only_this_systems_lines(self):
        self.assertEqual(sorted(t.name for t in linux_tools.lock(str(self.share))), ["emsdk", "sdl2"])

    def test_the_first_start_downloads_them_and_the_next_needs_no_connection(self):
        found, error, said = self.ensure()
        self.assertIsNone(error)
        mine = self.dir / "data/hookshot/builder/toolchains" / TAG
        self.assertEqual(found, {"emsdk": str(mine), "sdl2": str(mine)})
        clang = mine / "usr/lib/hookshot/emsdk/upstream/bin/clang"
        self.assertTrue(os.access(clang, os.X_OK))
        self.assertEqual(tools.stamp_of(str(mine), "emsdk"), linux_tools.lock(str(self.share))[0].sha256)
        self.assertEqual(len(self.asked), 2)
        # (progress: a line per tool, the fraction of the bytes, ending at the whole)
        self.assertTrue(any(text and "Downloading the build tools (1 of 2" in text for text, _ in said), said)
        self.assertEqual(said[-1], ("The build tools are ready", 1.0))
        self.assertFalse(list((mine.parent / ".downloads").glob("*.zip")))   # (the archives go once unpacked)
        env = self.env_of(found)
        self.assertEqual(env["EMSDK"], str(mine / "usr/lib/hookshot/emsdk"))
        self.assertEqual(env["HOOKSHOT_SDL2"], str(mine / "usr/lib/hookshot/sdl2/libSDL2-2.0.so.0"))
        self.asked.clear()
        again, error, said = self.ensure(getter=self.offline)
        self.assertEqual((again, error, self.asked, said), (found, None, [], []))
        # (nothing written into the image)
        self.assertEqual(sorted(p.name for p in self.app.rglob("*")), ["AppRun", "VERSION", "hookshot", "share", "tools.lock", "usr"])

    def test_another_version_links_what_it_shares_and_downloads_what_changed(self):
        self.ensure()
        old = self.dir / "data/hookshot/builder/toolchains" / TAG / "usr/lib/hookshot/sdl2/libSDL2-2.0.so.0"
        (self.share / "VERSION").write_text("v3.2.0\n")
        self.write_lock(emsdk="clang 2", sdl2="sdl 1")
        self.asked.clear()
        found, error, said = self.ensure()
        self.assertIsNone(error)
        new = self.dir / "data/hookshot/builder/toolchains/v3.2.0"
        self.assertEqual(len(self.asked), 1)   # (emsdk only: SDL2 is the same archive)
        self.assertIn(("sdl2: kept from " + TAG, None), said)
        self.assertEqual(os.stat(new / "usr/lib/hookshot/sdl2/libSDL2-2.0.so.0").st_ino, os.stat(old).st_ino)
        self.assertIn("clang 2", (new / "usr/lib/hookshot/emsdk/upstream/bin/clang").read_text())

    def test_the_launchers_tools_are_used_as_they_are(self):
        # (the launcher unpacked the AppImage into toolchains/<version>/ and each tool beside it, at its dest)
        for t in linux_tools.lock(str(self.share)):
            (self.app / t.dest).mkdir(parents=True)
        found, error, _ = self.ensure(getter=self.offline)
        self.assertEqual((found, error, self.asked), ({"emsdk": str(self.app), "sdl2": str(self.app)}, None, []))
        self.assertFalse((self.dir / "data").exists())

    def test_the_launchers_copy_of_this_version_is_used(self):
        theirs = self.dir / "launcher/toolchains" / TAG
        lock = linux_tools.lock(str(self.share))
        for t in lock:
            (theirs / t.dest).mkdir(parents=True)
        # (only once its record names the archive: a version the launcher is still unpacking has none)
        found, _, _ = self.ensure(install=False)
        self.assertEqual(found, {"emsdk": None, "sdl2": None})
        (theirs / "toolchain.json").write_text(json.dumps({"Tag": TAG, "Parts": [{"Sha": t.sha256} for t in lock]}))
        found, error, _ = self.ensure(getter=self.offline)
        self.assertEqual((found, error, self.asked), ({"emsdk": str(theirs), "sdl2": str(theirs)}, None, []))

    def test_a_download_that_differs_installs_nothing(self):
        for url in self.data:
            self.data[url] = b"changed on the server"
        found, error, _ = self.ensure()
        self.assertIn("could not be installed", error)
        self.assertEqual(found, {"emsdk": None, "sdl2": None})
        self.assertEqual(self.env_of(found), {})
        mine = self.dir / "data/hookshot/builder/toolchains" / TAG
        self.assertFalse((mine / "usr/lib/hookshot/emsdk").exists())
        self.assertIsNone(tools.stamp_of(str(mine), "emsdk"))

    def test_a_tool_with_another_stamp_is_installed_again(self):
        self.ensure()
        self.write_lock(emsdk="clang 3", sdl2="sdl 1")   # (a rebuilt dev AppImage with the same name)
        found, error, _ = self.ensure()
        mine = self.dir / "data/hookshot/builder/toolchains" / TAG
        self.assertIsNone(error)
        self.assertIn("clang 3", (mine / "usr/lib/hookshot/emsdk/upstream/bin/clang").read_text())

    def test_the_text_progress_goes_to_stderr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as out:
            self.ensure(say=linux_tools.text_say())
        self.assertIn("Downloading the build tools (2 of 2, sdl2", err.getvalue())
        self.assertIn("100%", err.getvalue())
        self.assertEqual(out.getvalue(), "")   # (stdout is the environment AppRun reads)


@unittest.skipUnless(sys.platform.startswith("linux"), "AppRun is the Linux builder's")
class AppRun(unittest.TestCase):
    """AppRun itself, in a stand-in image: its Python is this one, nx2/make_game.py prints what it was given"""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hookshot-apprun-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        app = self.app = self.dir / "AppDir"
        share = app / "usr/share/hookshot"
        for rel in ("builder/linux/linux_tools.py", "builder/linux/hookshot-launch", "scripts/tools.py"):
            (share / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, share / rel)
        shutil.copy2(ROOT / "builder/linux/AppRun", app / "AppRun")
        (app / "usr/python/bin").mkdir(parents=True)
        os.symlink(sys.executable, app / "usr/python/bin/python3")
        (share / "nx2").mkdir()
        (share / "nx2/make_game.py").write_text("import os, sys\nprint('make_game', sys.argv[1:], os.environ.get('EMSDK'))\n")
        (share / "VERSION").write_text(TAG + "\n")
        sha, size, self.data = archive(self.dir / "emsdk.zip", "emsdk", {"upstream/bin/clang": "#!/bin/sh\n"})
        # (a link no server answers: a download is "no connection" at once, and nothing leaves this PC)
        (share / "tools.lock").write_text("tool emsdk 1 linux-x64 %s %d usr/lib/hookshot/emsdk emsdk https://127.0.0.1:9/e.zip\n"
                                          % (sha, size))
        self.sha = sha
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(self.dir / "home"), "LANG": "C.UTF-8",
                    "HOOKSHOT_BUILDER_HOME": str(self.dir / "data")}

    def run_app(self, *args):
        return subprocess.run([str(self.app / "AppRun"), *args], env=self.env, capture_output=True, text=True, timeout=60)

    def test_cli_stops_without_the_tools(self):
        r = self.run_app("--cli", "--prepare", "--game", "/nowhere")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("make_game", r.stdout)
        self.assertIn("could not be installed", r.stderr)

    def test_cli_prepare_runs_with_the_tools_found_offline(self):
        # (RecompLauncher's prepare: --cli --prepare --game <copy>, with the tools a first start put there)
        mine = self.dir / "data/hookshot/builder/toolchains" / TAG
        tools.unpack(str(self.dir / "emsdk.zip"), "emsdk", str(mine / "usr/lib/hookshot/emsdk"))
        tools.write_stamp(str(mine), tools.parse((self.app / "usr/share/hookshot/tools.lock").read_text())[0])
        r = self.run_app("--cli", "--prepare", "--game", "/nowhere")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("make_game ['--prepare', '--game', '/nowhere'] %s" % (mine / "usr/lib/hookshot/emsdk"), r.stdout)

    def test_play_needs_no_build_tool(self):
        r = self.run_app("--play", str(self.dir / "no-game"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no built game to start", r.stderr)
        self.assertNotIn("build tools", r.stderr)
        self.assertFalse((self.dir / "data").exists())

    def test_launch_plays_that_folder_with_no_build_tool(self):
        # (a game folder's hookshot starts the AppImage that built it with --cli with --launch <folder>: builder/linux/hookshot-folder)
        folder = self.dir / "no-game"
        folder.mkdir()
        r = self.run_app("--launch", str(folder))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no built game to start", r.stderr)
        self.assertNotIn("build tools", r.stderr)
        self.assertFalse((self.dir / "data").exists())

    def test_no_window_only_the_launcher_message(self):
        # (no display here: the message on stderr, no dialog. Nothing downloaded, make_game.py not run)
        for args in ((), ("--update", str(self.dir)), ("--repair",), ("--launch",)):
            r = self.run_app(*args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("Hookshot Launcher", r.stderr, args)
            self.assertIn("https://hookshot.magicbean.dev/download", r.stderr, args)
            self.assertEqual(r.stdout, "", args)
        self.assertFalse((self.dir / "data").exists())

    def test_the_order_in_apprun(self):
        text = (ROOT / "builder/linux/AppRun").read_text(encoding="utf-8")
        cli = text[text.index('if [ "${1:-}" = "--cli" ]'):text.index('if [ "${1:-}" = "--play" ]')]
        self.assertLess(cli.index("build_tools || exit 1"), cli.index("make_game.py"))
        play = text[text.index('if [ "${1:-}" = "--play" ]'):]
        self.assertNotIn("build_tools", play)
        self.assertNotIn("--gui", text)
        self.assertNotIn("hookshot_builder.py", text)

if __name__ == "__main__":
    unittest.main()
