"""The Quality preset Auto (this PC)'s handheld detection (gpu/vk/vk_main.cpp auto_profile), cut out of the source and compiled
with stubs (no game, no GPU), then given to gpu/vk/auto_settings.h's choose().

Steam sets SteamDeck=1 for the games it starts whenever it runs as on a Deck (-steamdeck), which Steam's Gaming Mode sessions on
other PCs do too (gamescope-session, Bazzite's HTPC images: their `sd0` launch option turns it off). A desktop there with a
discrete card is no handheld: Auto must choose by its card, not Minimum. The Steam Deck itself (LCD 0405, OLED 0932) stays
Minimum, by its GPU's name.

python -I -B tests/test_auto_handheld.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def body(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def detection():
    """The statements of auto_profile from `hw.integrated = ` up to and including the one that sets hw.handheld"""
    src = body((ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8"), "void auto_profile() {")
    start = src.index("hw.integrated = ")
    m = re.compile(r"hw\.handheld = [^;]*;").search(src, start)
    if not m:
        raise SystemExit("vk_main.cpp auto_profile: no `hw.handheld = ...;` after `hw.integrated = `")
    lines = [l for l in src[start:m.end()].splitlines()
             if not re.match(r"\s*(hw\.vram_mb|hw\.mesh|hw\.rtx|hw\.rdna4|for \(|if \(dev\.memory)", l)
             and "dev.memory" not in l and "dev.mesh" not in l]
    text = "\n".join(lines)
    if "hw.handheld" not in text or "hw.integrated" not in text:
        raise SystemExit("vk_main.cpp auto_profile: the handheld detection could not be cut out")
    return text


CPP = r"""
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include "gpu/vk/auto_settings.h"
enum { VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU = 1, VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU = 2 };
struct Props { int deviceType; char deviceName[256]; unsigned vendorID; };
static ::auto_settings::Hardware detect(const Props& p) {
    ::auto_settings::Hardware hw;
    hw.vendor = ::auto_settings::AMD;
@DETECT@
    return hw;
}
static int fails;
static void check(const char* what, int type, const char* name, const char* steamdeck, int handheld, int tier, unsigned vram) {
    // (handheld -1: either; an integrated GPU is Minimum whichever)
    Props p{type, {}, 0x1002};
    std::snprintf(p.deviceName, sizeof p.deviceName, "%s", name);
    if (steamdeck) setenv("SteamDeck", steamdeck, 1); else unsetenv("SteamDeck");
    ::auto_settings::Hardware hw = detect(p);
    hw.vram_mb = vram, hw.ram_mb = 32768, hw.mesh_native = true;
    const ::auto_settings::Choice c = ::auto_settings::choose(hw);
    if ((handheld >= 0 && (int)hw.handheld != handheld) || c.tier != tier) {
        std::printf("FAIL %s: handheld %d (want %d), tier %d (want %d): %s\n", what, hw.handheld, handheld, c.tier, tier, c.why);
        fails++;
    } else {
        std::printf("ok   %s: tier %d (%s)\n", what, c.tier, c.why);
    }
}
int main() {
    const int I = VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU, D = VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU;
    check("Steam Deck OLED", I, "AMD Custom GPU 0932 (RADV VANGOGH)", "1", 1, 1, 8192);
    check("Steam Deck LCD outside Steam", I, "AMD Custom GPU 0405 (RADV VANGOGH)", nullptr, 1, 1, 8192);
    check("another integrated GPU under Steam's Gaming Mode", I, "AMD Radeon 780M (RADV PHOENIX)", "1", -1, 1, 8192);
    check("RX 7900 XTX under Steam's Gaming Mode (SteamDeck=1)", D, "AMD Radeon RX 7900 XTX (RADV NAVI31)", "1", 0, 5, 24560);
    check("RX 7900 XTX on the desktop", D, "AMD Radeon RX 7900 XTX (RADV NAVI31)", nullptr, 0, 5, 24560);
    check("RX 6600 under Steam's Gaming Mode (SteamDeck=1)", D, "AMD Radeon RX 6600 (RADV NAVI23)", "1", 0, 3, 8176);
    return fails ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    code = CPP.replace("@DETECT@", detection())
    with tempfile.TemporaryDirectory(prefix="auto-handheld-") as tmp:
        src, exe = Path(tmp) / "t.cpp", Path(tmp) / "t"
        src.write_text(code, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(src), "-o", str(exe)],
                       check=True)
        r = subprocess.run([str(exe)])
        if r.returncode:
            raise SystemExit("the handheld detection takes a desktop for a handheld (vk_main.cpp auto_profile)")


if __name__ == "__main__":
    main()
