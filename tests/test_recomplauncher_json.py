"""Game-free checks of recomplauncher.json: it parses, and every settings key is a row of the in-game menu.

Run with: python -I tests/test_recomplauncher_json.py
"""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecompLauncherJsonTests(unittest.TestCase):
    def test_settings_are_menu_rows(self):
        manifest = json.loads((ROOT / "recomplauncher.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], 1)
        menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
        rows = {re.sub(" ", "_", name.lower()) for name in re.findall(r'\{TAB_[A-Z]+, "([^"]+)"', menu)}
        # (vk_menu.cpp ini_key: the rows whose key is not their name, renamed rows keeping the key an options file has:
        # output_res, resolution, upscaling, frame_rate_cap, dlss)
        ini_key = menu.split("const char* ini_key(const Row& r) {", 1)[1].split("\n}", 1)[0]
        rows |= set(re.findall(r'return "([a-z_0-9]+)";', ini_key))
        keys = {key for setting in manifest["settings"] for choice in setting["choices"] for key in choice["set"]}
        self.assertTrue(keys)
        # (keys the game reads that are no menu row: Compile shaders, which the preparation reads, vk_draw.cpp compile_all)
        draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
        read_elsewhere = {"compile_shaders"} if '"compile_shaders="' in draw else set()
        self.assertEqual(keys - rows - read_elsewhere, set())

    def test_appimage_carries_it(self):
        self.assertIn('cp recomplauncher.json "$APPDIR/recomplauncher.json"',
                      (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8"))

    def test_windows_zip_carries_it(self):
        # (scripts/builder_package.py zip: the setup as HookshotBuilder.exe, the builder, tools.lock and VERSION, and this
        # file at the top, where RecompLauncher reads it; the setup installs the tools tools.lock names, with no release lookup)
        import importlib.util, tempfile, zipfile
        spec = importlib.util.spec_from_file_location("builder_package", ROOT / "scripts" / "builder_package.py")
        bp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bp)
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            (package / "tools").mkdir(parents=True)
            (package / "HookshotBuilder.exe").write_bytes(b"MZ builder")
            setup = Path(tmp) / "setup.exe"
            setup.write_bytes(b"MZ setup")
            out = Path(tmp) / "HookshotBuilder-v3.0.0-windows-x64.zip"
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                bp.make_zip(str(package), "v3.0.0", str(setup), str(out))
            with zipfile.ZipFile(out) as z:
                self.assertEqual(sorted(z.namelist()), ["HookshotBuilder.exe", "HookshotBuilder/HookshotBuilder.exe",
                                                        "HookshotBuilder/tools/version.txt", "VERSION",
                                                        "recomplauncher.json", "tools.lock"])
                self.assertEqual(z.read("HookshotBuilder.exe"), b"MZ setup")
                self.assertEqual(z.read("VERSION"), b"v3.0.0\n")
                # (and where the builder and the game read it: without it a release's game logged "hookshot unknown")
                self.assertEqual(z.read("HookshotBuilder/tools/version.txt"), b"v3.0.0\n")
        manifest = json.loads((ROOT / "recomplauncher.json").read_text(encoding="utf-8"))
        self.assertIn("HookshotBuilder.exe", manifest["start"]["program"])
        self.assertIn("HookshotBuilder.exe", manifest["prepare"]["program"])
        workflow = (ROOT / ".forgejo" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
        self.assertIn('--out "dist/HookshotBuilder-$TAG-windows-x64.zip"', workflow)

    def test_no_repository_it_cannot_read(self):
        # (RecompLauncher's "repo" is a GitHub owner/name, and Hookshot's releases are on git.magicbean.dev: none is named)
        manifest = json.loads((ROOT / "recomplauncher.json").read_text(encoding="utf-8"))
        self.assertNotIn("repo", manifest)


if __name__ == "__main__":
    unittest.main()
