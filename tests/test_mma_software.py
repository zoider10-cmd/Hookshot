"""The software matrix multiplies' forms (mma_software.h) and the self-test that chooses between them (vk_coopmat.cpp).

On a GPU without cooperative matrices (the Steam Deck, AMD before RDNA 3, GTX 10 and 16, Intel's integrated GPUs), the game's
upscale networks run HMMA.16816.F16 as a shader function. Its loop form (Lichii's) is what shipped; the unrolled forms take A
through quad broadcasts and round with the GPU's own f16 conversion, and are used only where the device's self-test finds the
loop's words in theirs. Without a GPU this checks what can be checked:

- every form, with quad broadcasts and without, assembles to SPIR-V that spirv-val accepts, from the self-test's own shader
  (software_test_shader cut from vk_coopmat.cpp), and has the shape its form promises (one loop the driver is asked not to
  unroll: the 8 steps, or the written-out body run once; shuffles for A or quad broadcasts; the shuffle with lane xor 0 before
  each f16 conversion);
- the self-test's inputs catch a driver that folds the f16 conversion into the FMA before it: on the CPU, the loop's
  arithmetic (each FMA rounded to f32, the sum to f16 after every 8 columns of K) and the folded one (the last FMA of a group
  rounded to f16 once) give other words on the warps built for it, so such a driver's unrolled form is refused;
- the switch (RX_VK_MMA_UNROLL, RADV by default), the emitter's use of the chosen form, and the program cache's stamp.
"""
import argparse
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block, between

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{spirv_headers}", "--spirv-val", "{spirv_val}"]
# (spirv-val: SPIRV-Tools comes with the Linux runner's packages, not on Windows)
RUN_ALL_SKIP = {"windows": "needs spirv-val: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu/vk"
SPIRV_DIR = VK / "eden/shader_recompiler/backend/spirv"
DRIVER_IDS = {"VK_DRIVER_ID_AMD_PROPRIETARY": 1, "VK_DRIVER_ID_MESA_RADV": 3, "VK_DRIVER_ID_NVIDIA_PROPRIETARY": 4,
              "VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA": 6}   # (as the Vulkan headers number them)


def compile_and_run(cxx, source, extra, folder, name, *args):
    cpp = folder / f"{name}.cpp"
    cpp.write_text(source, encoding="utf-8")
    exe = folder / f"{name}.exe"
    subprocess.run([cxx, "-std=c++20", "-O1", str(cpp), *extra, "-o", str(exe)], check=True)
    run = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=120)
    if run.returncode:
        raise SystemExit(f"{name}: {run.stdout.strip()} {run.stderr.strip()}".strip())
    return run.stdout


def spirv(cxx, headers, spirv_val, folder):
    """The self-test's shader in every form, through spirv-val, and each form's shape"""
    coopmat = (VK / "vk_coopmat.cpp").read_text(encoding="utf-8")
    shaders = between(coopmat, "constexpr uint32_t kSoftwareTestLanes", "/// The fragments the forms are compared on")
    fixture = """#include <array>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include <sirit/sirit.h>
#include "shader_recompiler/backend/spirv/mma_software.h"
""" + shaders + """
int main(int argc, char** argv) {
    using Shader::Backend::SPIRV::SoftwareMmaForm;
    if (argc != 2) return 2;
    for (const SoftwareMmaForm form : {SoftwareMmaForm::Loop, SoftwareMmaForm::Unrolled, SoftwareMmaForm::UnrolledF16})
        for (const bool quad : {false, true}) {
            const auto code = software_test_shader(form, quad);
            const std::string name = std::string(argv[1]) + "/form" + std::to_string((unsigned)form) + (quad ? "q" : "") + ".spv";
            FILE* f = std::fopen(name.c_str(), "wb");
            if (!f || std::fwrite(code.data(), 4, code.size(), f) != code.size()) return 3;
            std::fclose(f);
        }
    return 0;
}
"""
    sirit = VK / "sirit"
    extra = ["-I" + str(sirit / "include"), "-I" + str(sirit / "src"), "-I" + str(VK / "eden"), "-I" + str(headers),
             *map(str, sorted((sirit / "src").rglob("*.cpp")))]
    compile_and_run(cxx, fixture, extra, folder, "forms", folder)
    for form in (0, 1, 2):
        for quad in ("", "q"):
            path = folder / f"form{form}{quad}.spv"
            subprocess.run([spirv_val, "--target-env", "vulkan1.3", str(path)], check=True)
            ops = ops_of(path.read_bytes())
            loops = ops.count(246)          # (OpLoopMerge)
            shuffles = ops.count(345)       # (OpGroupNonUniformShuffle)
            quads = ops.count(365)          # (OpGroupNonUniformQuadBroadcast)
            xors = ops.count(346)           # (OpGroupNonUniformShuffleXor)
            converts = ops.count(115)       # (OpFConvert)
            where = f"form {form}{' with quad broadcasts' if quad else ''}"
            if loops != 1:
                raise SystemExit(f"{where}: {loops} loops, not one (the steps' loop, or the written-out body's loop that runs once)")
            if form == 0 and (shuffles != 4 or quads or xors or converts):
                raise SystemExit(f"{where}: not the 8 steps' loop on 4 shuffles with integer rounding ({shuffles} shuffles, {quads} "
                                 f"quad, {xors} xor, {converts} conversions)")
            if form and (quads, shuffles) != ((16, 16) if quad else (0, 32)):
                raise SystemExit(f"{where}: {quads} quad broadcasts and {shuffles} shuffles, not "
                                 f"{(16, 16) if quad else (0, 32)} (B's 16, and A's 16 one way or the other)")
            if form == 1 and (xors or converts):
                raise SystemExit(f"{where}: the integer rounding has {xors} xor shuffles and {converts} conversions")
            if form == 2 and (xors != 8 or converts != 16):
                raise SystemExit(f"{where}: {xors} xor shuffles and {converts} conversions, not 8 and 16 (each rounding: the "
                                 "same lane, then f32 -> f16 -> f32)")
            print(f"PASS: {where}: spirv-val, {loops} loop, {shuffles} shuffles, {quads} quad broadcasts, {xors} xor shuffles, "
                  f"{converts} conversions")


def ops_of(code):
    """each instruction's opcode, in order"""
    words = struct.unpack(f"<{len(code) // 4}I", code)
    ops, at = [], 5
    while at < len(words):
        n = words[at] >> 16
        ops.append(words[at] & 0xffff)
        at += max(n, 1)
    return ops


MODEL = r"""
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
// (the loop's arithmetic and the folded one, lane by lane: PTX mma.m16n8k16's fragments, lane t, g = t/4, i = t%4)
float h2f(uint32_t h) {
    const uint32_t sign = (h & 0x8000) << 16, exp = (h >> 10) & 0x1f, man = h & 0x3ff;
    if (!exp) { const float f = std::ldexp((float)man, -24); return sign ? -f : f; }
    uint32_t x = exp == 31 ? sign | 0x7f800000 | man << 13 : sign | (exp - 15 + 127) << 23 | man << 13;
    float f; std::memcpy(&f, &x, 4); return f;
}
uint32_t f2h(double v) {   // (round to nearest even, f16 subnormals kept, overflow to infinity)
    if (std::isnan(v)) return 0x7e00;
    const uint32_t sign = std::signbit(v) ? 0x8000 : 0;
    double a = std::fabs(v);
    if (a >= 65520.0) return sign | 0x7c00;
    if (a < 0x1p-14) return sign | (uint32_t)std::nearbyint(a * 0x1p24);
    int e; std::frexp(a, &e);   // (a = m * 2^e, m in [0.5, 1))
    const double q = std::nearbyint(std::ldexp(a, 11 - e));   // (11 significant bits)
    if (q >= 2048.0) { e++; }
    const uint32_t bits = (uint32_t)(e - 1 + 15) << 10 | ((uint32_t)(q >= 2048.0 ? q / 2 : q) & 0x3ff);
    return sign | bits;
}
// one lane's D: folded = the last FMA of each group of 8 K rounded to f16 once (a driver folding the conversion into it)
void lane_d(const uint32_t* warp, int t, bool folded, uint32_t out[2]) {
    const int i = t % 4;
    float acc[4];
    for (int row = 0; row < 2; row++)
        for (int col = 0; col < 2; col++) acc[row * 2 + col] = h2f(warp[t * 8 + 6 + row] >> 16 * col & 0xffff);
    for (int upper = 0; upper < 2; upper++) {
        double last[4];
        for (int component = 0; component < 4; component++)
            for (int row = 0; row < 2; row++)
                for (int col = 0; col < 2; col++) {
                    const uint32_t a = warp[((t & ~3) + component) * 8 + upper * 2 + row];
                    const uint32_t b = warp[(i * 8 + component + col * 4) * 8 + 4 + upper];
                    for (int half = 0; half < 2; half++) {
                        const float x = h2f(a >> 16 * half & 0xffff), y = h2f(b >> 16 * half & 0xffff);
                        float& s = acc[row * 2 + col];
                        if (component == 3 && half == 1) last[row * 2 + col] = (double)x * y + s;   // (exact for these inputs)
                        s = std::fma(x, y, s);
                    }
                }
        for (int k = 0; k < 4; k++) acc[k] = h2f(f2h(folded ? last[k] : (double)acc[k]));
    }
    for (int row = 0; row < 2; row++) out[row] = f2h(acc[row * 2]) | f2h(acc[row * 2 + 1]) << 16;
}
"""


def inputs(cxx, folder):
    """The self-test's inputs tell the loop's words from a folding driver's"""
    coopmat = (VK / "vk_coopmat.cpp").read_text(encoding="utf-8")
    lanes = re.search(r"constexpr uint32_t kSoftwareTestLanes = [^;]+;", coopmat).group(0)
    make = block(coopmat, "std::vector<uint32_t> software_test_input()")
    fixture = MODEL + lanes + "\n" + make + r"""
int main() {
    const std::vector<uint32_t> data = software_test_input();
    // (the warps built for it: every eighth, kinds 3*683 + 2^-16, 3*683 - 2^-16, 48*1365 + 2^-16, 48*1365 - 2^-16)
    const uint32_t want_loop[4] = {0x6800, 0x6800, 0x7c00, 0x7c00}, want_folded[4] = {0x6801, 0x6800, 0x7c00, 0x7bff};
    int folded_differ = 0;
    for (uint32_t warp = 0; warp < kSoftwareTestLanes / 32; warp += 8) {
        const uint32_t kind = warp / 8 % 4;
        for (int t = 0; t < 32; t++) {
            uint32_t loop[2], folded[2];
            lane_d(&data[warp * 32 * 8], t, false, loop);
            lane_d(&data[warp * 32 * 8], t, true, folded);
            // (every lane's D: rows g, g + 8 of columns 2i, 2i + 1, each the same sum)
            for (int w = 0; w < 2; w++) {
                const uint32_t lw = want_loop[kind] | want_loop[kind] << 16, fw = want_folded[kind] | want_folded[kind] << 16;
                if (loop[w] != lw || folded[w] != fw) {
                    std::printf("warp %u lane %d word %d: loop %08x (want %08x), folded %08x (want %08x)\n", warp, t, w, loop[w], lw,
                                folded[w], fw);
                    return 1;
                }
                folded_differ += loop[w] != folded[w];
            }
        }
    }
    std::printf("%d\n", folded_differ);
    return folded_differ ? 0 : 1;
}
"""
    out = compile_and_run(cxx, fixture, [], folder, "inputs")
    count = int(out.split()[-1])
    if count < 512:
        raise SystemExit(f"only {count} of the built warps' words tell a folding driver from the loop")
    print(f"PASS: the self-test's inputs: {count} words of the built warps differ where the conversion is folded "
          "(2049 + 2^-16: 2048 looped, 2050 folded; 65520 - 2^-16: infinity looped, 65504 folded)")


def switch(cxx, folder):
    """software_unroll_wanted: RADV by default, RX_VK_MMA_UNROLL over it"""
    coopmat = (VK / "vk_coopmat.cpp").read_text(encoding="utf-8")
    fn = block(coopmat, "bool software_unroll_wanted(")
    choose = block(coopmat, "void choose_software_form(")
    if 'software_unroll_wanted(dev.driver_id, env)' not in choose or 'std::getenv("RX_VK_MMA_UNROLL")' not in choose:
        raise SystemExit("choose_software_form does not ask software_unroll_wanted with RX_VK_MMA_UNROLL")
    order = [choose.index(x) for x in ("software_test_input()", "software_forms_agree(", "mma_software_form = (uint32_t)form")]
    if order != sorted(order):
        raise SystemExit("choose_software_form does not run the loop, compare a form and only then use it")
    if "software_multiplies(\"subgroup shuffles, RX_VK_MMA_SOFTWARE\")" not in coopmat:
        raise SystemExit("RX_VK_MMA_SOFTWARE=1 does not go through software_multiplies (and its form)")
    radv, amd, nvidia, intel = "VK_DRIVER_ID_MESA_RADV", "VK_DRIVER_ID_AMD_PROPRIETARY", "VK_DRIVER_ID_NVIDIA_PROPRIETARY", \
        "VK_DRIVER_ID_INTEL_OPEN_SOURCE_MESA"
    cases = [(radv, None, True), (radv, "0", False), (radv, "1", True), (amd, None, False), (amd, "1", True),
             (nvidia, None, False), (intel, None, False), (intel, "true", True), (nvidia, "off", False)]
    checks = "\n".join(
        f'    if (software_unroll_wanted({d}, {"nullptr" if e is None else chr(34) + e + chr(34)}) != {str(w).lower()}) '
        f'{{ std::puts("FAIL: {d} {e}"); return 1; }}' for d, e, w in cases)
    env_h = (VK / "compat/hookshot_env.h").read_text(encoding="utf-8")
    enum = "enum VkDriverId { " + ", ".join(f"{k} = {n}" for k, n in DRIVER_IDS.items()) + " };\n"
    source = env_h + "\n#include <cstdio>\n#include <cstdlib>\n" + enum + fn + "\nint main() {\n" + checks + "\n    return 0;\n}\n"
    compile_and_run(cxx, source, [], folder, "switch")
    print("PASS: RX_VK_MMA_UNROLL: unrolled on RADV by default, looped elsewhere, the switch over both")


def wiring():
    warp = (SPIRV_DIR / "emit_spirv_warp.cpp").read_text(encoding="utf-8")
    define = block(warp, "void DefineSoftwareMatrixFunction(")
    if "DefineSoftwareMma(ctx, " not in define or "mma_software_form" not in define:
        raise SystemExit("the emitter does not define the software function in the chosen form")
    if "GroupNonUniformQuad" not in define:
        raise SystemExit("the emitter does not declare GroupNonUniformQuad for the quad broadcasts")
    shader = (VK / "vk_shader.cpp").read_text(encoding="utf-8")
    stamp = block(shader, "uint64_t translator_stamp()")
    if "mma_software_form << 8" not in stamp or "mma_software_quad" not in stamp:
        raise SystemExit("the program cache's stamp does not hold the software multiplies' form")
    print("PASS: the emitter takes the chosen form, and the program cache's stamp holds it")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--headers", type=Path, required=True)
    parser.add_argument("--spirv-val", default="spirv-val")
    args = parser.parse_args()
    wiring()
    with tempfile.TemporaryDirectory(prefix="mma-software-") as folder:
        folder = Path(folder)
        switch(args.cxx, folder)
        inputs(args.cxx, folder)
        spirv(args.cxx, args.headers, args.spirv_val, folder)


if __name__ == "__main__":
    main()
