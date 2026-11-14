"""The Linux game folder's launcher: a packaged build puts it in the folder and the game in bin/, the folder launcher starts
the program that made the game (or the game), and the sysroot packed as tools.lock's archive.

python -I -B tests/test_linux_update.py
"""
import contextlib
import importlib.util
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

# (Linux only)
RUN_ALL_SKIP = {"windows": "the Linux folder launcher, POSIX files and shell scripts"}

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder" / "linux"))
sys.path.insert(0, str(ROOT / "nx2"))


class FolderTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "the Linux folder layout")
    def test_a_packaged_build_puts_the_launcher_in_the_folder_and_the_game_in_bin(self):
        import ast
        from unittest import mock
        import make_game
        main = next(n for n in ast.parse((ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")).body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        start = next(i for i, n in enumerate(main.body) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "staged" for t in n.targets))
        end = next(i for i, n in enumerate(main.body[start + 1:], start + 1) if isinstance(n, ast.If)
                   and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "shader_census_cmd"
                           for c in ast.walk(n)))
        finish = compile(ast.Module(body=main.body[start:end], type_ignores=[]), "make_game.py", "exec")
        with tempfile.TemporaryDirectory(prefix="hookshot-finish-") as tmp:
            work, out = Path(tmp) / "work", Path(tmp) / "game"
            built = work / "sa" / "build"
            built.mkdir(parents=True)
            (work / "sa" / "image").mkdir()
            (work / "sa" / "image" / "image.bin").write_bytes(b"image")
            for name in make_game.BESIDE:
                (built / name).write_bytes(b"new " + name.encode())
            out.mkdir()
            for name in make_game.BESIDE:   # (a folder from a builder before the launcher: the game and its libraries in it)
                (out / name).write_bytes(b"old " + name.encode())
            with mock.patch.dict(os.environ, {"HOOKSHOT_TOOLS": str(ROOT)}):
                exec(finish, make_game.__dict__, {"built": str(built), "out": str(out), "work": str(work),
                                                   "a": SimpleNamespace(fsr=False, no_fsr=False, update=None, fetch_fsr_runtime=False)})
            self.assertEqual((out / "hookshot").read_bytes(), (ROOT / "builder" / "linux" / "hookshot-folder").read_bytes())
            self.assertTrue((out / "hookshot").stat().st_mode & stat.S_IXUSR)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["bin", "image.bin", "hookshot"])
            self.assertEqual(sorted(p.name for p in (out / "bin").iterdir()), sorted(make_game.BESIDE))
            self.assertEqual((out / "bin" / "hookshot").read_bytes(), b"new hookshot")

    def test_the_sysroot_path_is_not_part_of_an_object_key(self):
        import build
        handle, name = tempfile.mkstemp()
        os.write(handle, b"int x;\n")
        os.close(handle)
        try:
            one = build.object_key(name, ["--sysroot=/tmp/.mount_aaa/usr/lib/hookshot/sysroot", "-O2"], b"deps")
            two = build.object_key(name, ["--sysroot=/tmp/.mount_bbb/usr/lib/hookshot/sysroot", "-O2"], b"deps")
        finally:
            os.remove(name)
        self.assertEqual(one, two)

    def test_the_folder_launcher_starts_the_builder(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-folder-") as tmp:
            root = Path(tmp)
            game = root / "game"
            (game / "bin").mkdir(parents=True)
            (game / "image.bin").write_bytes(b"image")
            started = root / "started"
            builder = root / "builder"
            builder.write_text("#!/bin/sh\nprintf '%%s\\n' \"$0\" \"$@\" > '%s'\n" % started, encoding="utf-8")
            builder.chmod(0o755)
            (game / "hookshot_version.txt").write_text("version=v1\nbuilder=%s\n" % builder, encoding="utf-8")
            script = game / "hookshot"
            shutil.copyfile(ROOT / "builder" / "linux" / "hookshot-folder", script)
            script.chmod(0o755)
            env = os.environ.copy()
            ran = subprocess.run([str(script)], env=env, check=False, text=True, capture_output=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            lines = started.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[1], "--launch")
            self.assertEqual(lines[2], str(game))

    def test_the_folder_launcher_starts_the_game_when_its_builder_is_gone(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-folder-") as tmp:
            root = Path(tmp)
            game = root / "game"
            (game / "bin").mkdir(parents=True)
            (game / "bin" / "hookshot").write_text("#!/bin/sh\nprintf 'game\\n'\n", encoding="utf-8")
            (game / "bin" / "hookshot").chmod(0o755)
            (game / "hookshot_version.txt").write_text("version=v1\nbuilder=%s\n" % (root / "gone"), encoding="utf-8")
            script = game / "hookshot"
            shutil.copyfile(ROOT / "builder" / "linux" / "hookshot-folder", script)
            script.chmod(0o755)
            env = os.environ.copy()
            ran = subprocess.run([str(script)], env=env, check=False, text=True, capture_output=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertEqual(ran.stdout.strip(), "game")

    @unittest.skipUnless(sys.platform.startswith("linux"), "the Linux sysroot copy loop")
    def test_sysroot_system_aliases_round_trip_as_library_bytes(self):
        # (the sysroot is made by deps.sh tools, then packed as tools.lock's archive: scripts/tools.py pack and unpack, the
        # builder's first start and the launcher, carry it)
        script = (ROOT / "scripts" / "linux" / "deps.sh").read_text(encoding="utf-8")
        start = script.index("for f in crt1.o ")
        loop = script[start:script.index("\n    done", start) + len("\n    done")]
        with tempfile.TemporaryDirectory(prefix="hookshot-sysroot-") as tmp:
            root = Path(tmp)
            system = root / "system"
            system.mkdir()
            real = system / "libmvec.so.1"
            real.write_bytes(b"private library bytes")
            alias = system / "libmvec.so"
            alias.symlink_to(real)
            source = root / "sysroot"
            (source / "usr" / "lib" / "x86_64-linux-gnu").mkdir(parents=True)
            (source / "lib").symlink_to("usr/lib")
            env = dict(os.environ, M=str(system), S=str(source))
            subprocess.run(["bash", "-euo", "pipefail", "-c", loop], env=env, check=True)
            copied = source / "usr" / "lib" / "x86_64-linux-gnu" / alias.name
            self.assertFalse(copied.is_symlink(), "the sysroot must carry the alias's bytes, not an absolute target")
            spec = importlib.util.spec_from_file_location("tools", ROOT / "scripts" / "tools.py")
            tools = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(tools)
            with contextlib.redirect_stdout(io.StringIO()):
                tools.pack(str(source), str(root / "sysroot.zip"))
            tools.unpack(str(root / "sysroot.zip"), "sysroot", str(root / "tool"))
            self.assertEqual(os.readlink(root / "tool" / "lib"), "usr/lib")   # (the one link: relative, as packed)
            self.assertEqual((root / "tool" / "lib" / "x86_64-linux-gnu" / alias.name).read_bytes(), real.read_bytes())
            self.assertEqual(os.readlink(alias), str(real))
            self.assertEqual(real.read_bytes(), b"private library bytes")


if __name__ == "__main__":
    unittest.main()
