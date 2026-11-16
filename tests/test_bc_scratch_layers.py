"""The BC3 scratch has the layers a run uses, not more (gpu/vk/vk_texture.cpp; no game or GPU needed).

Decoded ASTC is encoded to BC3 through a 2048 x 2048 scratch image and its output buffer, kept once made. A run is one layer
(RX_VK_BC_LAYERS=<n>: up to 8), but the scratch was made with 8 layers whatever the runs used: 160 MB held, 20 of them ever
written. The scratch, the second one and both users (an upload's runs, a copy into a BC3 texture) now ask bc_layers().

The two loops that fill it are also run, cut out of the source into tests/bc_scratch_batches_test.cpp with a spy in place
of Vulkan: no run is larger than the scratch, each starts at its first layer, and a request larger than the scratch (a
copy of 9 layers, an array's dirty layers with gaps) comes out whole and in order as several runs.

python -I -B tests/test_bc_scratch_layers.py [--cxx g++]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r"""
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
constexpr uint32_t kBcDim = 2048, kBcLayers = 8;
#include "bc_layers.inc"
int main() {
    const uint32_t n = bc_layers();
    const uint64_t image = (uint64_t)kBcDim * kBcDim * 4 * n, out = (uint64_t)(kBcDim / 4) * (kBcDim / 4) * n * 16;
    std::printf("%u %llu\n", n, (unsigned long long)((image + out) >> 20));
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
        raise SystemExit(why)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a_cxx = p.parse_args().cxx
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    for make, image in (("bool bc_scratch_make() {", "bc_scratch"), ("bool bc_scratch2_make() {", "bc_scratch2")):
        body = block(tex, make)
        need("ii.arrayLayers = bc_layers();" in body and "0, 1, 0, bc_layers()};" in body and "kBcLayers" not in body,
             image + " is made with more layers than a run uses")
    need("* bc_layers() * 16;" in block(tex, "bool bc_scratch_make() {"), "the scratch's output buffer is sized for more layers than a run")
    layout = block(tex, "bool bc_scratch_layout(")
    need(layout.count("0, 1, 0, bc_layers()};") == 2 and "kBcLayers" not in layout, "a scratch's first layout names layers it does not have")
    upload = block(tex, "bool upload_astc_gpu(Texture& tex, uint64_t total, const Ranges* dirty) {")
    need("const uint32_t run = bc_layers();" in upload and "k1 - k0 < run" in upload, "an upload's run is not the scratch's layers")
    copy = block(tex, "bool texture_copy_into_bc(")
    need("l0 += bc_layers()" in copy and "std::min(bc_layers(), layers - l0)" in copy and "kBcLayers" not in copy,
         "a copy into a BC3 texture writes scratch layers that are not there")
    with tempfile.TemporaryDirectory(prefix="bc-layers-") as temp:
        (Path(temp) / "bc_layers.inc").write_text(block(tex, "uint32_t bc_layers() {"), encoding="utf-8")
        src = Path(temp) / "bc_layers.cpp"
        exe = Path(temp) / "bc_layers.exe"   # (the name llvm-mingw writes on Windows; any name runs on Linux)
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([a_cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I", temp, str(src), "-o", str(exe)], check=True)
        for value, want in ((None, "1 20"), ("1", "1 20"), ("4", "4 80"), ("8", "8 160"), ("99", "8 160"), ("0", "1 20")):
            env = {k: v for k, v in os.environ.items() if k != "RX_VK_BC_LAYERS"}
            if value is not None:
                env["RX_VK_BC_LAYERS"] = value
            got = subprocess.run([str(exe)], text=True, capture_output=True, timeout=20, env=env, check=True).stdout.strip()
            need(got == want, f"RX_VK_BC_LAYERS={value}: {got} (layers, MB), wanted {want}")
        # (the production loops, run: texture_copy_into_bc whole, and the lines of upload_astc_gpu that form a run)
        a = upload.index("size_t k1 = k0 + 1;")
        b = upload.index("const uint32_t n = (uint32_t)(k1 - k0);", a) + len("const uint32_t n = (uint32_t)(k1 - k0);")
        fixture = (ROOT / "tests/bc_scratch_batches_test.cpp").read_text(encoding="utf-8")
        need(fixture.count("/* COPY */") == 1 and fixture.count("/* RUN */") == 1, "the batches fixture lost a mark")
        fixture = fixture.replace("/* COPY */", copy).replace("/* RUN */", upload[a:b])
        src = Path(temp) / "bc_scratch_batches.cpp"
        exe = Path(temp) / "bc_scratch_batches.exe"
        src.write_text(fixture, encoding="utf-8")
        subprocess.run([a_cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], text=True, capture_output=True, timeout=20)
        print(r.stdout, end="")
        need(r.returncode == 0, "a run into the BC3 scratch is larger than it, or a larger request does not come out whole: " + r.stderr.strip())
    print("PASS: the BC3 scratch has a run's layers (20 MB at one layer, 160 at 8)")


if __name__ == "__main__":
    main()
