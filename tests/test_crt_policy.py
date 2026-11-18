"""Compile the production CRT raster policy without a game or GPU; inspect output-stage wiring.

python -I -B tests/test_crt_policy.py [--cxx clang++] [--source checkout]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    vk = args.source / "gpu/vk"
    fixture = r'''
#include "crt_policy.h"
#include <cstdio>
using namespace mkwvk::crt_policy;
static_assert(!enabled(0, false) && !enabled(-1, false) && !enabled(5, false));
static_assert(enabled(1, false) && enabled(2, false) && enabled(3, false) && enabled(4, false));
static_assert(!enabled(1, true) && !enabled(2, true) && !enabled(3, true) && !enabled(4, true));
static_assert(raster(1920, 1080, 0).h == 240 && raster(1920, 1080, 0).w == 427);
static_assert(raster(3840, 2160, 0).h == 240 && raster(3840, 2160, 0).w == 427);
static_assert(raster(3840, 2160, 1).h == 480 && raster(3840, 2160, 1).w == 853);
static_assert(raster(3840, 2160, 2).h == 720 && raster(3840, 2160, 2).w == 1280);
static_assert(raster(1280, 720, 2).h == 360 && raster(1280, 720, 2).w == 640);
static_assert(raster(3440, 1440, 0).h == 240 && raster(3440, 1440, 0).w == 573);
static_assert(raster(5120, 1440, 1).w == 1707);
static_assert(raster(1, 1, 2).w == 1 && raster(1, 1, 2).h == 1);
static_assert(raster(0, 1080, 0).w == 0 && raster(1920, 0, 0).h == 0);
static_assert(raster(3840, 2160, -1).h == 240 && raster(3840, 2160, 99).h == 720);
int main() { std::puts("PASS: CRT mode/PQ bypass, virtual lines, small-output cap and wide aspect"); }
'''
    with tempfile.TemporaryDirectory(prefix="crt-policy-") as tmp:
        src, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-I" + str(vk), str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    replay = (vk / "vk_replay.cpp").read_text(encoding="utf-8")
    scale = (vk / "vk_framegen.cpp").read_text(encoding="utf-8")
    present = replay[replay.index("void present_image("):replay.index("static bool present_out(", replay.index("void present_image(") + 1)]
    assert present.index("framegen_scale(") < present.index("framegen_hdr(") < present.index("menu_record("), "CRT before HDR encode and Hookshot overlays"
    assert scale.count("present_image(j.set->frame[k].image, fg.w, fg.h, nullptr, j.set->frame[k].view);") == 2, "both generated-frame schedules use the output stage"
    assert "headless_fx = framegen_scale(" in replay and "headless_fx ? headless_fx : src" in replay, "headless frames and bridge shots carry output effects"
    assert "crt_policy::enabled(opts.crt_filter, pq)" in scale, "Native PQ never enters SDR CRT"
    print("PASS: CRT output-stage ordering and headless capture wiring (source checks, not GPU pixels)")


if __name__ == "__main__":
    main()
