"""The staging arenas a load used a moment ago are kept, so frames that stage in a row do not make one each time.

A staging arena is free for reuse once the GPU finished the submission that read it, which is after the next frame
staged. So frames that stage in a row need two arenas taking turns. A card of 6.5 GB or less keeps 64 MB of idle
arenas between loads (texture_frame), one arena: the idle one of the two went at every second present, and the next
frame made a 64 MB arena again (9 to 41 ms of the replay thread on a Steam Deck, where it is system memory the driver
clears). Arenas staged into in the last 2 s now stay, up to 256 MB of them, unless VRAM is near what the driver allows
(pool_pressed). RX_VK_STAGING_BURST_S=0: as before.

Cuts staging() and texture_frame's give-back loop out of gpu/vk/vk_texture.cpp into tests/staging_burst_test.cpp and
runs frames against them on a clock of the fixture's.

python -I -B tests/test_staging_burst.py --headers <Vulkan-Headers/include> [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    arena = "constexpr uint64_t kArena = 64ull << 20;"
    if tex.count(arena) != 1:
        raise SystemExit("vk_texture.cpp's arenas are no longer 64 MB: update this test")
    frame = block(tex, "void texture_frame(")
    loop = block(frame, "for (auto it = arenas.begin(); it != arenas.end();) {")
    for needle in ("const bool idle = it->value <= completed && it->value != rec_value;", "destroy_buffer(it->buffer, it->allocation);",
                   "kept += it->size;", "const bool recent = burst_s && !pool_pressed && "):
        if needle not in loop:
            raise SystemExit("texture_frame's give-back loop no longer has: " + needle)
    if "st_arena_makes.load()" not in frame:
        raise SystemExit("texture_frame's memory line no longer says how many staging arenas were made")
    if frame.index("completed_value = completed;") > frame.index(loop):
        raise SystemExit("texture_frame gives arenas back before it notes what the GPU completed: update this test's frame()")
    actual = block(tex, "struct Arena {") + ";\nstd::vector<Arena> arenas;\n" + arena + "\n"
    actual += block(tex, "struct Staging {") + ";\n" + block(tex, "Staging staging(")
    actual += "\nuint64_t give_back(uint64_t completed, uint64_t keep) {\n    uint64_t kept = 0;\n    " + loop + "\n    return kept;\n}\n"
    actual = actual.replace("std::chrono::steady_clock", "Clock")
    fixture = (ROOT / "tests/staging_burst_test.cpp").read_text(encoding="utf-8").replace("/* ACTUAL */", actual)
    with tempfile.TemporaryDirectory(prefix="staging-burst-") as temp:
        cpp, exe = Path(temp) / "fixture.cpp", Path(temp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
                        "-I" + str(a.headers), str(cpp), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("RX_VK_STAGING_")}
        for case in ("consecutive", "settles", "cap", "big", "keep256", "pressure", "short"):
            subprocess.run([str(exe), case], check=True, timeout=15, env=env)
        for case in ("consecutive", "cap", "big"):   # (the switch back)
            subprocess.run([str(exe), case], check=True, timeout=15, env={**env, "RX_VK_STAGING_BURST_S": "0"})
    print("staging arenas kept through a load's burst: ok")


if __name__ == "__main__":
    main()
