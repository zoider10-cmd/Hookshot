"""Intel XeSS Super Resolution's rules (gpu/vk/xess_rules.h): which quality preset takes a render size, the menu's names for
the Render resolution's stops under XeSS (upscaler_rows.h xess_mode_name), where Intel's libxess.dll is looked for and
RX_VK_XESS; and, read from the sources, that the DLL is only ever loaded at run time (never linked), every reason XeSS is
not offered has its line in the menu, and the presets are xess.h's. No game, GPU or Intel library required.

python -I -B tests/test_xess_rules.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

PROGRAM = r'''
#include "gpu/vk/xess_rules.h"
#include "gpu/vk/upscaler_rows.h"
#include <cstdio>
#include <cstring>

namespace xr = mkwvk::xess_rules;
namespace ur = mkwvk::upscaler_rows;
static int failed = 0;
#define CHECK(what, cond) do { if (!(cond)) { std::printf("FAIL %s (line %d)\n", what, __LINE__); failed++; } } while (0)

static int at(int percent) {   // (the preset for a share of 3840x2160, as the menu's twelfths make it)
    const int k = (int)(percent * 12 / 100.0f + 0.5f);
    return xr::preset_for((3840u * (unsigned)k + 11u) / 12u, 2160u * (unsigned)k / 12u, 3840, 2160, false);
}

int main() {
    CHECK("ratios", xr::min_input(3840, xr::ULTRA_QUALITY) == 2560 && xr::min_input(2160, xr::ULTRA_PERFORMANCE) == 720 &&
                        xr::min_input(2160, xr::BALANCED) == 1080 && xr::min_input(100, xr::NATIVE_AA) == 100 &&
                        xr::min_input(1, xr::ULTRA_PERFORMANCE) == 1);
    CHECK("92% Ultra Quality Plus", at(92) == xr::ULTRA_QUALITY_PLUS);
    CHECK("83% Ultra Quality Plus", at(83) == xr::ULTRA_QUALITY_PLUS);
    CHECK("75% Ultra Quality (past 1.3x)", at(75) == xr::ULTRA_QUALITY);
    CHECK("67% Ultra Quality", at(67) == xr::ULTRA_QUALITY);
    CHECK("58% Balanced", at(58) == xr::BALANCED);
    CHECK("50% Balanced", at(50) == xr::BALANCED);
    CHECK("42% Ultra Performance", at(42) == xr::ULTRA_PERFORMANCE);
    CHECK("33% Ultra Performance", at(33) == xr::ULTRA_PERFORMANCE);
    CHECK("100% scaled: Ultra Quality Plus", xr::preset_for(3840, 2160, 3840, 2160, false) == xr::ULTRA_QUALITY_PLUS);
    CHECK("native", xr::preset_for(3840, 2160, 3840, 2160, true) == xr::NATIVE_AA &&
                        xr::preset_for(2560, 1440, 3840, 2160, true) == -1);
    CHECK("past 3x", xr::preset_for(1279, 719, 3840, 2160, false) == -1 &&
                         xr::preset_for(1280, 720, 3840, 2160, false) == xr::ULTRA_PERFORMANCE);
    CHECK("larger than the output", xr::preset_for(3841, 2160, 3840, 2160, false) == -1 &&
                                        xr::preset_for(0, 2160, 3840, 2160, false) == -1);
    CHECK("each axis", xr::preset_for(3840, 1000, 3840, 2160, false) == xr::PERFORMANCE);
    // the library's own ranges are taken over the rounding
    xr::Range r[xr::kPresets];
    for (int p = 0; p < xr::kPresets; p++) r[p] = {3000, 2000};
    CHECK("library ranges", xr::preset_for(2999, 2100, 3840, 2160, false, r) == -1 &&
                                xr::preset_for(3000, 2000, 3840, 2160, false, r) == xr::ULTRA_QUALITY_PLUS);
    // the menu's names (upscaler_rows.h, which vk_menu.cpp shows) are the presets' for every share it has
    for (int v = 0; v < 16; v++) {
        const int p = ur::percent(v);
        const char* a = ur::xess_mode_name(v);
        const char* b = xr::share_name(p);
        if (p == 100) continue;   // (100%: no stop of XeSS's slider; Native is its Native AA)
        if (!a || !b ? a != b : std::strcmp(a, b) != 0) {
            std::printf("FAIL name for %d%%: menu %s, presets %s\n", p, a ? a : "none", b ? b : "none");
            failed++;
        }
    }
    for (int s : ur::kSlider) CHECK("every slider stop has a name", ur::xess_mode_name(s) != nullptr);
    CHECK("Auto has none", !xr::share_name(0) && !ur::xess_mode_name(0));
    // where libxess.dll is looked for
    auto d = xr::library_dirs("C:\\xess", "C:\\ls\\bin", "C:\\game");
    CHECK("dirs with the env", d.size() == 3 && d[0] == "C:\\xess" && d[1] == "C:\\ls\\bin" && d[2] == "C:\\game");
    d = xr::library_dirs(nullptr, "C:\\ls\\bin", "C:\\game");
    CHECK("dirs without", d.size() == 2 && d[0] == "C:\\ls\\bin" && d[1] == "C:\\game");
    d = xr::library_dirs("", "C:\\g", "C:\\g");
    CHECK("dirs once each", d.size() == 1 && d[0] == "C:\\g");
    d = xr::library_dirs("C:\\g", "C:\\g", "");
    CHECK("env equal to the exe's", d.size() == 1);
    CHECK("env mode", xr::env_mode(nullptr) == -1 && xr::env_mode("") == -1 && xr::env_mode("0") == 0 &&
                          xr::env_mode("1") == 1 && xr::env_mode("2") == 2 && xr::env_mode("-3") == -1);
    if (failed) return 1;
    std::printf("xess rules: ok\n");
    return 0;
}
'''


def check_sources():
    vk = ROOT / "gpu" / "vk"
    xess = (vk / "vk_xess.cpp").read_text(encoding="utf-8")
    header = (vk / "vk_xess.h").read_text(encoding="utf-8")
    menu = (vk / "vk_menu.cpp").read_text(encoding="utf-8")
    rules = (vk / "xess_rules.h").read_text(encoding="utf-8")
    api = (ROOT / "third_party" / "xess" / "inc" / "xess" / "xess.h").read_text(encoding="utf-8")
    build = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
    # Intel's DLL is the player's: loaded at run time with its own folder first in its search, never linked or shipped
    if "LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS" not in xess:
        raise SystemExit("vk_xess.cpp does not load libxess.dll with LoadLibraryExA's own-folder search")
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", xess, flags=re.S)   # (the code, not what its comments say)
    if re.search(r"#\s*define\s+XESS_SHARED_LIB", code) or re.search(r"libxess\.lib|-lxess|-llibxess", build + code):
        raise SystemExit("libxess is linked: it must be loaded at run time only (the DLL is Intel's, never ours)")
    for path in ROOT.rglob("*"):
        if path.is_file() and path.name.lower() in ("libxess.dll", "libxess.lib") and ".git" not in path.parts:
            raise SystemExit("%s: Intel's library must never be in the repo" % path.relative_to(ROOT))
    # every reason XeSS is not offered has its line in the menu, and vk_xess.cpp gives each
    m = re.search(r"enum XessWhy \{([^}]*)\}", header)
    whys = [w.strip() for w in m.group(1).split(",") if w.strip()] if m else []
    if not whys or whys[-1] != "XESS_WHY_COUNT":
        raise SystemExit("vk_xess.h: XessWhy does not end with XESS_WHY_COUNT")
    m = re.search(r"static const char\* const xess_no\[XESS_WHY_COUNT\] = \{(.*?)\};", menu, re.S)
    if not m:
        raise SystemExit("vk_menu.cpp: no xess_no table")
    lines = re.findall(r'nullptr|"(?:[^"\\]|\\.)*"', m.group(1))
    if len(lines) != len(whys) - 1:
        raise SystemExit("vk_menu.cpp xess_no has %d lines for %d reasons" % (len(lines), len(whys) - 1))
    for why in whys[1:-1]:
        if why not in xess:
            raise SystemExit("vk_xess.cpp never says %s" % why)
    # the presets are xess.h's
    names = ("ULTRA_QUALITY_PLUS", "ULTRA_QUALITY", "QUALITY", "BALANCED", "PERFORMANCE", "ULTRA_PERFORMANCE", "AA")
    want = []
    for n in names:
        q = re.search(r"XESS_QUALITY_SETTING_%s = (\d+)," % n, api)
        if not q:
            raise SystemExit("xess.h has no XESS_QUALITY_SETTING_%s" % n)
        want.append(q.group(1))
    m = re.search(r"constexpr int kQuality\[kPresets\] = \{([^}]*)\}", rules)
    if not m or [v.strip() for v in m.group(1).split(",")] != want:
        raise SystemExit("xess_rules.h kQuality is not xess.h's presets in its order: %s" % want)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_sources()
    with tempfile.TemporaryDirectory(prefix="xess-rules-") as tmp:
        src = Path(tmp) / "xess_rules_test.cpp"
        src.write_text(PROGRAM, encoding="utf-8")
        exe = Path(tmp) / "xess-rules"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(src), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
