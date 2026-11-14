"""The AppImage carries the licences of the third-party parts compiled into hookshot_vk.so: Dear ImGui (MIT), zstd (BSD), the
Libertinus fonts (OFL) and, in a build with AMD FSR 4, AMD's FSR API headers (MIT), each with its PROVENANCE.md. Runs the real copy block of scripts/linux/appimage.sh into a temporary
folder; nothing is built.

    python -I -B tests/test_appimage_licenses.py
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WANT = {
    "licenses/imgui/LICENSE.txt": "third_party/imgui/LICENSE.txt",
    "licenses/imgui/PROVENANCE.md": "third_party/imgui/PROVENANCE.md",
    "licenses/zstd/LICENSE": "third_party/zstd/LICENSE",
    "licenses/zstd/PROVENANCE.md": "third_party/zstd/PROVENANCE.md",
    "licenses/libertinus/OFL.txt": "third_party/fonts/libertinus/OFL.txt",
    "licenses/libertinus/PROVENANCE.md": "third_party/fonts/PROVENANCE.md",
    "licenses/fidelityfx/LICENSE.md": "third_party/fidelityfx/LICENSE.md",
    "licenses/fidelityfx/PROVENANCE.md": "third_party/fidelityfx/PROVENANCE.md",
}


class AppImageLicences(unittest.TestCase):
    # (the AppImage is made on Linux; Windows runners have no usable bash for the script's block)
    @unittest.skipUnless(sys.platform.startswith("linux"), "the AppImage is made on Linux")
    def test_copied(self):
        script = (ROOT / "scripts/linux/appimage.sh").read_text(encoding="utf-8")
        start = script.index("# ---- the licences of the third-party parts compiled into hookshot_vk.so")
        end = script.index("# ---- end of the licences ----", start)
        with tempfile.TemporaryDirectory(prefix="hookshot-appimage-licences-") as folder:
            env = dict(os.environ, T=folder)
            result = subprocess.run(["bash", "-eu", "-o", "pipefail", "-c", script[start:end]], cwd=ROOT, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for shipped, source in WANT.items():
                self.assertEqual((Path(folder) / shipped).read_bytes(), (ROOT / source).read_bytes(), shipped)

    def test_no_tk_licences(self):
        # (the AppImage carries no Tcl/Tk, libXft or libXrender any more: deps.sh has no licences folder of its own to copy)
        script = (ROOT / "scripts/linux/appimage.sh").read_text(encoding="utf-8")
        deps = (ROOT / "scripts/linux/deps.sh").read_text(encoding="utf-8")
        self.assertNotIn('"$DEPS/licenses"', script)
        self.assertNotIn('"$DEPS/tk', script)
        for gone in ("TCLTK_VER", "Tk-license", "libXft", "mark tk"):
            self.assertNotIn(gone, deps)

    def test_vk_third_party_covered(self):
        # (every third_party folder the Vulkan back end compiles in, from nx2/build.py, has its licence shipped)
        build = (ROOT / "nx2/build.py").read_text(encoding="utf-8") + (ROOT / "nx2/ui_fonts.py").read_text(encoding="utf-8")
        for part, licence in (("imgui", "licenses/imgui/"), ("zstd", "licenses/zstd/"), ("fonts", "licenses/libertinus/"),
                              ("fidelityfx", "licenses/fidelityfx/")):
            if '"third_party", "%s"' % part in build:
                self.assertTrue(any(k.startswith(licence) for k in WANT), part)

    def test_fsr_headers_carried(self):
        # (AMD FSR 4 on Linux: the back end compiled in the player's build reads AMD's FSR API headers from the image, where
        # nx2/build.py looks for them, and stops with a sentence when an older image has none)
        script = (ROOT / "scripts/linux/appimage.sh").read_text(encoding="utf-8")
        build = (ROOT / "nx2/build.py").read_text(encoding="utf-8")
        self.assertIn('cp -a third_party/fidelityfx "$T/third_party/"', script)
        self.assertIn('FSR_HEADERS = os.path.join(kit.HERE, "..", "third_party", "fidelityfx")', build)
        self.assertIn('return "" if NGX_SDK or FSR else os.environ.get("HOOKSHOT_VK_PREBUILT", "")', build)
        self.assertTrue((ROOT / "third_party/fidelityfx/api/include/ffx_api.h").is_file())


if __name__ == "__main__":
    unittest.main()
