"""The Intel shader compiles row's Auto: side by side on the Arc B-series from the driver it was measured on, one at a
time on every other Intel GPU (no game/GPU required).

IntelDriverGate (gpu/vk/vk_internal.h) lets one thread at a time into Intel's Windows compiler. On an Arc B580 with driver
32.0.101.9154 that froze the picture for four to seven minutes at an area's first visit, and side by side did not, with
no fault in ten areas. gpu/vk/intel_compiles.h says where Auto, the row's default, is side by side: compiled alone here
against a table of GPUs and drivers and of the row's three values (0 Auto, 1 Side by side, 2 One at a time). The menu's
half (the row's range and texts, RX_VK_NO_INTEL_SERIAL's two values, what the gate asks) is checked in the source.

    python -I -B tests/test_intel_compiles_auto.py [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"

MEASURED = 101 << 14 | 9154   # (Intel's Windows driverVersion: 32.0.101.9154)
B580, B570, A770, A380, MTL, ARL, LNL, IRIS_XE, UHD770 = 0xE20B, 0xE20C, 0x56A0, 0x56A5, 0x7D55, 0x7D51, 0x64A0, 0x9A49, 0x4680
# (the row's value, the PCI device, the driver's version, 1 side by side or 0 one at a time)
CASES = ([(0, g, MEASURED, 1) for g in (B580, B570)] + [(0, B580, MEASURED + 21, 1), (0, B580, 102 << 14, 1)] +
         [(0, B580, MEASURED - 1, 0), (0, B580, 101 << 14 | 6913, 0), (0, B580, 0, 0)] +
         [(0, g, v, 0) for g in (A770, A380, MTL, ARL, LNL, IRIS_XE, UHD770) for v in (MEASURED, 101 << 14 | 9175)] +
         [(1, g, v, 1) for g in (B580, A770, UHD770) for v in (0, MEASURED)] +
         [(2, g, v, 0) for g in (B580, B570, A770, UHD770) for v in (0, MEASURED, MEASURED + 21)])
FIXTURE = r"""
#include <cstdio>
#include <cstdlib>
#include "intel_compiles.h"
int main(int argc, char** argv) {
    for (int i = 1; i + 3 < argc; i += 4) {
        const int row = atoi(argv[i]);
        const uint32_t device = (uint32_t)strtoul(argv[i + 1], nullptr, 0), version = (uint32_t)strtoul(argv[i + 2], nullptr, 0);
        const bool got = intel_side_by_side_chosen(row, device, version);
        if (got != (atoi(argv[i + 3]) != 0)) {
            printf("FAIL: row %d, device 0x%04x, driver %u.%u: %s\n", row, device, version >> 14, version & 0x3fff,
                   got ? "side by side" : "one at a time");
            return 1;
        }
    }
    return 0;
}
"""


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(cond, why):
    if not cond:
        raise SystemExit("FAIL: " + why)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    args = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp) / "auto.cpp", Path(tmp) / "auto.exe"
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-I", str(VK), str(src), "-o", str(exe)], check=True)
        argv = [str(exe)]
        for row, device, version, want in CASES:
            argv += [str(row), hex(device), str(version), str(want)]
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(r.stdout.strip() or "FAIL: the fixture ended with %d" % r.returncode)

    menu = (VK / "vk_menu.cpp").read_text(encoding="utf-8")
    need('{TAB_DEBUG, "Intel shader compiles", &opts.intel_compiles, 0, 2, 1, tx_intel_compiles,' in menu,
         "the row no longer has three values with Auto, 0, the default")
    need('const char* tx_intel_compiles(int v) { return v == 1 ? "Side by side" : v == 2 ? "One at a time" : "Auto"; }' in menu,
         "the row's texts moved: a saved 1 must stay Side by side, and 0, what every saved file has, is Auto")
    need("return hint_in(t, 3, 0, v, variant);" in block(menu, "const char* hn_intel_compiles(int v, int variant) {"),
         "the row's hints are not one a value")
    need("int intel_compiles = 0;" in (VK / "vk_menu.h").read_text(encoding="utf-8"), "the row's default is not Auto")
    need("env_override(&opts.intel_compiles, env_value_off(e) ? 2 : 1);" in block(menu, "void menu_init() {"),
         "RX_VK_NO_INTEL_SERIAL no longer chooses both ways (1 side by side, 0 one at a time)")
    need("intel_side_by_side_chosen(opts.intel_compiles, dev.props.deviceID, dev.props.driverVersion)"
         in block(menu, "bool intel_compiles_side_by_side() {"), "the gate is not asked with the row, the GPU and its driver")
    print("ok: %d cases: Auto is side by side on the Arc B-series from 101.9154, one at a time on other Intel GPUs; "
          "the row's Side by side and One at a time hold on any" % len(CASES))


if __name__ == "__main__":
    main()
