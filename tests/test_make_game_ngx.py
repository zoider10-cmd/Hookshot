"""nx2/make_game.py and NVIDIA DLSS: the runtime placed in the game folder's ngx folder (never beside the exe), and the
fetch a build with DLSS asks for (--fetch-ngx-sdk), which needs NVIDIA's license accepted. No network, no game.

Run with: python -I tests/test_make_game_ngx.py
"""
import importlib.util
import io
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_game_ngx_under_test", ROOT / "nx2" / "make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


class NgxRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hookshot-make-game-ngx-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sdk = self.root / "sdk"
        self.out = self.root / "game"
        (self.out / "bin").mkdir(parents=True)
        self.ngx = make_game.ngx_script()

    def sdk_files(self, platform, runtime=True, framegen=True):
        lib = Path(self.ngx.library(str(self.sdk), platform))
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_bytes(b"lib")
        if runtime:
            rt = Path(self.ngx.runtime(str(self.sdk), platform))
            rt.parent.mkdir(parents=True, exist_ok=True)
            rt.write_bytes(b"runtime")
            if framegen:
                Path(self.ngx.runtime(str(self.sdk), platform, "framegen")).write_bytes(b"framegen")

    def place(self, platform, sdk=None, said=None):
        env = {"HOOKSHOT_NGX_SDK": str(self.sdk) if sdk is None else sdk}
        with mock.patch.object(make_game, "LINUX", platform == "linux"), mock.patch.dict(os.environ, env), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            dst = make_game.place_ngx_runtime(str(self.out))
        if said is not None:
            said.append(out.getvalue())
        return dst

    def test_windows_runtime_goes_to_the_ngx_folder(self):
        self.sdk_files("windows")
        dst = self.place("windows")
        self.assertEqual(Path(dst), self.out / "ngx" / "nvngx_dlss.dll")
        self.assertEqual(Path(dst).read_bytes(), b"runtime")
        # (DLSS Frame Generation's runtime beside it, where NGX looks before the driver's own copy)
        self.assertEqual((self.out / "ngx" / "nvngx_dlssg.dll").read_bytes(), b"framegen")
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["bin", "ngx"])
        self.assertEqual(list((self.out / "bin").iterdir()), [])   # (nothing beside the exe)
        self.assertFalse([p for p in self.out.rglob("*") if p.name.lower() == "_nvngx.dll"])

    def built(self, platform, sdk=None):
        env = {"HOOKSHOT_NGX_SDK": str(self.sdk) if sdk is None else sdk}
        with mock.patch.object(make_game, "LINUX", platform == "linux"), mock.patch.dict(os.environ, env):
            return make_game.ngx_built()

    def test_built_with_this_platforms_library(self):
        # (the camera jitter is no longer tied to this: nx2/oot_jitter.py is in every standalone lift, for FSR 3.1 as well)
        self.assertFalse(self.built("linux", sdk=""))
        self.assertFalse(self.built("linux"))   # (no library yet)
        self.sdk_files("linux", runtime=False)
        self.assertTrue(self.built("linux"))
        self.assertFalse(self.built("windows"))   # (another platform's library only)

    def test_fsr_build(self):
        """--fsr: HOOKSHOT_FSR=1 for nx2/build.py; an --update of that folder keeps it (its mark), --no-fsr takes it out. (The
        camera jitter FSR 4 needs is in every build: nx2/lift.py)"""
        out = str(self.out)
        mark = self.out / make_game.FSR_MARK
        plain = SimpleNamespace(fsr=False, no_fsr=False, update=None)
        self.assertFalse(make_game.fsr_wanted(plain, out))
        self.assertTrue(make_game.fsr_wanted(SimpleNamespace(fsr=True, no_fsr=False, update=None), out))
        update = SimpleNamespace(fsr=False, no_fsr=False, update=out)
        self.assertFalse(make_game.fsr_wanted(update, out))
        mark.write_text("")
        self.assertTrue(make_game.fsr_wanted(update, out))
        self.assertFalse(make_game.fsr_wanted(SimpleNamespace(fsr=False, no_fsr=True, update=out), out))
        self.assertFalse(make_game.fsr_wanted(plain, out))   # (a new build without --fsr: the mark is for --update only)

    def test_linux_runtime(self):
        self.sdk_files("linux")
        self.assertEqual(Path(self.place("linux")), self.out / "ngx" / "libnvidia-ngx-dlss.so.310.9.16")
        self.assertTrue((self.out / "ngx" / "libnvidia-ngx-dlssg.so.310.9.16").is_file())

    def test_rebuilding_without_dlss_removes_stale_runtime(self):
        self.sdk_files("linux")
        self.assertTrue((Path(self.place("linux"))).is_file())
        self.assertIsNone(self.place("linux", sdk=""))
        self.assertFalse((self.out / "ngx").exists())   # (both runtimes gone, and the folder)

    def test_an_older_sdk_folder_says_how_to_get_frame_generations_runtime(self):
        self.sdk_files("windows", framegen=False)
        said = []
        self.assertEqual(Path(self.place("windows", said=said)), self.out / "ngx" / "nvngx_dlss.dll")
        self.assertEqual([p.name for p in (self.out / "ngx").iterdir()], ["nvngx_dlss.dll"])
        self.assertIn("has no nvngx_dlssg.dll yet", said[0])
        self.assertIn("scripts/ngx_sdk.py", said[0])

    def test_nothing_without_the_sdk_or_its_platform(self):
        self.assertIsNone(self.place("windows", sdk=""))
        self.sdk_files("linux")
        self.assertIsNone(self.place("windows"))   # (a Linux SDK folder: no Windows library, no DLSS in this build)
        self.sdk_files("windows", runtime=False)
        self.assertIsNone(self.place("windows"))
        self.assertFalse((self.out / "ngx").exists())


class FetchGateTests(unittest.TestCase):
    def fetch(self, accept, sdk="sdk"):
        calls = []
        ngx = SimpleNamespace(NOTICE="notice", fetch=lambda *a, **k: calls.append(a))
        with mock.patch.object(make_game, "ngx_script", return_value=ngx), mock.patch.dict(os.environ, {"HOOKSHOT_NGX_SDK": sdk}), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            try:
                make_game.fetch_ngx_sdk(SimpleNamespace(accept_nvidia_license=accept))
            except SystemExit as e:
                return calls, e.code, out.getvalue()
        return calls, 0, out.getvalue()

    def test_needs_the_license_accepted(self):
        calls, code, out = self.fetch(False)
        self.assertEqual((calls, code), ([], 1))
        self.assertIn("@@error", out)
        self.assertIn("license", out)

    def test_without_the_variable_the_sdk_goes_to_work_ngx_sdk(self):
        # (the Builder's --cli drops HOOKSHOT_NGX_SDK, so a launcher's --fetch-ngx-sdk has to work without it)
        calls, code, _ = self.fetch(True, sdk="")
        folder = os.path.join(make_game.ROOT, "work", "ngx-sdk")
        self.assertEqual((calls, code), ([(folder, make_game.ngx_platform())], 0))

    def test_fetches_this_platforms_files_after_the_notice(self):
        calls, code, out = self.fetch(True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("sdk", make_game.ngx_platform())])
        self.assertTrue(out.startswith("notice"))

    def test_flags_are_off_by_default(self):
        with mock.patch("sys.argv", ["make_game.py", "--out", "x", "--nup", "y"]):
            a = make_game.parse_args()
        self.assertFalse(a.fetch_ngx_sdk)
        self.assertFalse(a.accept_nvidia_license)


class NoScriptTests(unittest.TestCase):
    """The AppImage carries no scripts/ (scripts/linux/appimage.sh): with HOOKSHOT_NGX_SDK set there, ngx_script() says so and
    stops, not a FileNotFoundError traceback from importlib"""

    def test_missing_script_is_said_plainly(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-no-scripts-") as root, mock.patch.object(make_game, "ROOT", root), \
                mock.patch.dict(os.environ, {"HOOKSHOT_NGX_SDK": os.path.join(root, "sdk")}), \
                mock.patch("sys.stdout", io.StringIO()) as out:
            with self.assertRaises(SystemExit) as stopped:
                make_game.place_ngx_runtime(os.path.join(root, "game"))
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("@@error", out.getvalue())
        self.assertIn("ngx_sdk.py", out.getvalue())
        self.assertIn("Unset HOOKSHOT_NGX_SDK", out.getvalue())


class AppImageDlssTests(unittest.TestCase):
    def test_build_and_appimage_package_dlss_sources(self):
        build_py = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        self.assertIn('return "" if NGX_SDK or FSR else os.environ.get("HOOKSHOT_VK_PREBUILT", "")', build_py)
        self.assertIn('vk_prebuilt = prebuilt_renderer()', build_py)
        appimage = (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8")
        for piece in ("cp scripts/ngx_sdk.py", "cp -a gpu/vk gpu/compat gpu/third_party", "third_party/imgui"):
            self.assertIn(piece, appimage)
        # (the static C++ runtime the back end links with DLSS: in the sysroot, tools.lock's, which deps.sh tools packs)
        deps = (ROOT / "scripts" / "linux" / "deps.sh").read_text(encoding="utf-8")
        self.assertIn("libstdc++.a", deps[deps.index("# ---- the sysroot"):deps.index("# ---- each tool's licenses")])


if __name__ == "__main__":
    unittest.main()
