"""Below 60 fps, Havok cloth (Link's cap, romfs Phive/Cloth) keeps the game's clock (host/oot_high_fps.h oot_cloth_seconds,
host/oot_high_fps.c hos_oot_cloth_seconds, nx2/oot_patches.py patch_cloth_time).

The simulate operator's per-frame setup, f_81b3aa48, takes its time (+8) and a count (+24) from its step context and stores, in
its frame data, the count (+0), count x subSteps x the operator's own count (+24), the time over the instance's scale (+44) and
that over the product: one substep's time (+48). The context's time is a 60th of a second whatever the frame (16.67 ms measured
at 18 fps, as at 60), so at 18 fps (a frame step of 3.3) the cloth runs at 0.3 of the clock while Link moves at the game's: his
cap swings far out and takes about a second to settle. With the hook the time is multiplied by the game's frame step (the
float f_83b6ea90 writes at 0x84d61fc8) while that step is over 1; at 60 fps and above, and for a step that is 0, below 0, not a
number, infinite or over 8, the game's time stays. HOS_FPS_CLOTH=0 (or off, false, no) keeps the game's.

The setup is lifted as the game has it (the lines of f_81b3aa48 that make the frame data, and a stand-in for the operator's own
count), run through patch_file, compiled with stand-ins for guest memory, the repository's switch rule (gpu/vk/compat/
longshot_env.h) and the host's hos_oot_cloth_seconds (cut from host/oot_high_fps.c), and run with the context's 60th at frame
steps from 0.06 (1000 fps) to 4.0 (15 fps, the longest the host gives) and the bad ones, with instance scales of 1 and 2, each
setup twice from the same context, for HOS_FPS_CLOTH unset, 1, yes, 0 and off. Each frame data must cover the frame's time over
1 (else the game's 60th), over the instance's scale, its substeps adding up to it, with the game's counts (no more solves), the
context left as it was and the second setup the same as the first. The patch hooks the context's time once, declares the hook,
and leaves a file patched before, or whose code differs, as it is.

python -I -B tests/test_oot_cloth_time.py
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

# (f_81b3aa48's lines that make the frame data, as the lift writes them: x1 the instance, x4 the step context, x5 the frame
# data; f_81b44f80 hands back the config's subSteps. The game's x9, the operator's own count, is a min and max of three of
# its fields, here one load)
LIFTED_CLOTH = """#include "a64.h"
void f_81b3aa48(Ctx *__restrict A64_NOESC c) {
    { uint64_t _r = ((uint64_t)0 | ((c->x[0]) << 0)); c->x[20] = _r; }
    { uint64_t _r = ((uint64_t)0 | ((c->x[5]) << 0)); c->x[19] = _r; }
    { uint64_t _r = ((uint64_t)0 | ((c->x[4]) << 0)); c->x[22] = _r; }
    { uint64_t _r = ((uint64_t)0 | ((c->x[1]) << 0)); c->x[21] = _r; }
c->x[30] = 0x81b3aab4ULL; f_81b44f80(c);
    recomp_store32_sp(c,c->x[19] + 8,c->x[0]);
    c->x[8]=recomp_load32(c,c->x[22] + 24);
    recomp_store32_sp(c,c->x[19] + 0,c->x[8]);
    { uint64_t _r = (uint64_t)0 + (c->x[8] * c->x[0]); _r &= 0xFFFFFFFFULL; c->x[8] = _r; }
    c->x[9]=recomp_load32(c,c->x[20] + 36);
    { uint64_t _r = (uint64_t)0 + (c->x[8] * c->x[9]); _r &= 0xFFFFFFFFULL; c->x[8] = _r; }
    recomp_store32_sp(c,c->x[19] + 4,c->x[9]);
    recomp_store32_sp(c,c->x[19] + 24,c->x[8]);
    { { uint64_t _v=recomp_load64(c,(c->x[22]+8ULL)); a64_vset64(c->vreg[0],_v); } }
    { { uint64_t _v=recomp_load32(c,(c->x[21]+380ULL)); a64_vset64(c->vreg[1],_v); } }
    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[0],4);memcpy(&_b,c->vreg[1],4);_z=(_a^_b)&0x80000000ULL;
    (void)_z;
    _v=a64_fpx_div32_div32(c,_a,_b);
    a64_vset64(c->vreg[0],_v);}
    { uint64_t _r=recomp_fixed_to_fp(c->x[8],32,32,0,0,c->fpcr,&c->fpsr); a64_vset64(c->vreg[1],0); c->vreg[1][0]=_r; }
    {uint64_t _a=0,_b=0,_z,_v;memcpy(&_a,c->vreg[0],4);memcpy(&_b,c->vreg[1],4);_z=(_a^_b)&0x80000000ULL;
    (void)_z;
    _v=a64_fpx_div32_div32(c,_a,_b);
    a64_vset64(c->vreg[1],_v);}
    { uint64_t _b=c->x[19]; int64_t _o=44; { uint64_t _p0=0,_p1=0; memcpy(&_p0,&c->vreg[0][0],4); memcpy(&_p1,&c->vreg[1][0],4); recomp_stp32(c,(_b+_o),_p0,_p1); }}
return;
}
"""

# (stand-ins for the lift's runtime: guest memory a small array, the operator at 0x100, the instance at 0x400 (+380 its scale),
# the step context at 0x800, the frame data at 0xc00; the game's frame step at 0x84d61fc8)
RUNTIME = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "../gpu/vk/compat/longshot_env.h"
#include "oot_high_fps.h"
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; uint64_t fpcr, fpsr; } Ctx;
typedef long long LONG64;
#define A64_NOESC
static const uint64_t g_module_base = 0;
static uint8_t mem[0x1000];
static uint32_t substeps, game_step;
static int fps_log(void) { return 0; }
static void hos_log(const char *f, ...) { (void)f; }
static LONG64 InterlockedIncrement64(volatile LONG64 *p) { return ++*p; }
static uint64_t recomp_load32(Ctx *c, uint64_t a) {
    uint32_t v;
    (void)c;
    if (a == 0x84d61fc8ULL) return game_step;
    memcpy(&v, mem + a, 4);
    return v;
}
static uint64_t recomp_load64(Ctx *c, uint64_t a) { uint64_t v; (void)c; memcpy(&v, mem + a, 8); return v; }
static void recomp_store32_sp(Ctx *c, uint64_t a, uint64_t v) { uint32_t w = (uint32_t)v; (void)c; memcpy(mem + a, &w, 4); }
static void recomp_stp32(Ctx *c, uint64_t a, uint64_t p0, uint64_t p1) { recomp_store32_sp(c, a, p0); recomp_store32_sp(c, a + 4, p1); }
static void a64_vset64(uint64_t *v, uint64_t value) { v[0] = value; v[1] = 0; }
static uint64_t a64_fpx_div32_div32(Ctx *c, uint64_t a, uint64_t b) {
    (void)c;
    return oot_float_bits(oot_bits_float((uint32_t)a) / oot_bits_float((uint32_t)b));
}
static uint64_t recomp_fixed_to_fp(uint64_t x, int to, int from, int fbits, int round, uint64_t fpcr, uint64_t *fpsr) {
    (void)to, (void)from, (void)fbits, (void)round, (void)fpcr, (void)fpsr;
    return oot_float_bits((float)(uint32_t)x);
}
static void f_81b44f80(Ctx *c) { c->x[0] = substeps; }
"""

FRAMES = r"""
static uint32_t get32(uint64_t a) { uint32_t v; memcpy(&v, mem + a, 4); return v; }
/* one setup at a frame step (the game's, in 60ths of a second) with the context's 60th, its count, subSteps, the operator's
   count and the instance's scale, twice; prints what the first stored, whether the second stored the same, and whether the
   context is as it was */
static void frame(int i, float step, uint32_t count, uint32_t sub, uint32_t own, float scale_f) {
    Ctx c;
    memset(mem, 0, sizeof mem);
    const uint32_t scale = oot_float_bits(scale_f), seconds = oot_float_bits(1.0f / 60.0f), more = oot_float_bits(1.0f);
    memcpy(mem + 0x400 + 380, &scale, 4);
    memcpy(mem + 0x800 + 8, &seconds, 4);
    memcpy(mem + 0x800 + 16, &more, 4);
    memcpy(mem + 0x800 + 24, &count, 4);
    memcpy(mem + 0x100 + 36, &own, 4);
    uint8_t context[32], first[64];
    memcpy(context, mem + 0x800, 32);
    substeps = sub, game_step = oot_float_bits(step);
    for (int k = 0; k < 2; k++) {
        memset(&c, 0, sizeof c);
        c.x[0] = 0x100, c.x[1] = 0x400, c.x[4] = 0x800, c.x[5] = 0xc00;
        f_81b3aa48(&c);
        if (!k) memcpy(first, mem + 0xc00, 64), memset(mem + 0xc00, 0, 64);
    }
    printf("%d %u %u %u %g %u %u %u %.9g %.9g %d %d\n", i, count, sub, own, scale_f, get32(0xc00), get32(0xc00 + 4),
           get32(0xc00 + 24), oot_bits_float(get32(0xc00 + 44)), oot_bits_float(get32(0xc00 + 48)),
           !memcmp(first, mem + 0xc00, 64), !memcmp(context, mem + 0x800, 32));
}
int main(void) {
    const float steps[] = {STEPS_C};
    const uint32_t counts[][3] = {{1, 1, 1}, {1, 2, 3}, {2, 4, 1}};
    const float scales[] = {1.0f, 2.0f};
    for (int i = 0; i < (int)(sizeof steps / sizeof *steps); i++)
        for (unsigned k = 0; k < 3; k++)
            for (unsigned s = 0; s < 2; s++) frame(i, steps[i], counts[k][0], counts[k][1], counts[k][2], scales[s]);
    return 0;
}
"""
# (the frame steps: (C expression, value); NaN, infinity, 0, below 0 and over 8 keep the game's time)
STEPS = [("0.06f", 0.06), ("0.12f", 0.12), ("0.25f", 0.25), ("0.5f", 0.5), ("1.0f", 1.0), ("1.05f", 1.05), ("1.2f", 1.2),
         ("1.8f", 1.8), ("2.0f", 2.0), ("3.0f", 3.0), ("3.3f", 3.3), ("3.5f", 3.5), ("4.0f", 4.0), ("8.0f", 8.0), ("8.5f", 8.5),
         ("0.0f", 0.0), ("-1.0f", -1.0), ("NAN", float("nan")), ("INFINITY", float("inf"))]
FRAMES = FRAMES.replace("STEPS_C", ", ".join(c for c, _ in STEPS))

SWITCH = ("unset", "1", "yes", "0", "off")


def hos_cloth(source):
    """host/oot_high_fps.c's hos_oot_cloth_seconds, when there (the patched setup calls it)"""
    if "uint32_t hos_oot_cloth_seconds(" not in source:
        return ""
    return block(source, "uint32_t hos_oot_cloth_seconds(") + "\n"


def compiler():
    return shutil.which("gcc") or shutil.which("clang")


class ClothTimeTests(unittest.TestCase):
    def frames(self, switch):
        """[(step, the game's count, subSteps, own count, count, own, total, time, substep)] at HOS_FPS_CLOTH=switch"""
        patched = oot_patches.patch_file(LIFTED_CLOTH, "code_cloth.c", False)[0]
        host = (ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8")
        program = RUNTIME + hos_cloth(host) + patched.replace('#include "a64.h"\n', "") + FRAMES
        with tempfile.TemporaryDirectory(prefix="longshot-cloth-") as tmp:
            tmp = Path(tmp)
            (tmp / "cloth.c").write_text(program, encoding="utf-8")
            binary = tmp / "cloth.exe"
            build = subprocess.run([compiler(), "-std=gnu11", "-Wall", "-Wno-unused-function", "-O1", "-I",
                                    str(ROOT / "host"), str(tmp / "cloth.c"), "-o", str(binary), "-lm"],
                                   text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            env = dict(os.environ)
            env.pop("HOS_FPS_CLOTH", None)
            if switch != "unset":
                env["HOS_FPS_CLOTH"] = switch
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        rows = []
        for line in run.stdout.split("\n"):
            if line:
                f = line.split()
                rows.append((STEPS[int(f[0])][1],) + tuple(int(v) for v in f[1:4]) + (float(f[4]),) +
                            tuple(int(v) for v in f[5:8]) + (float(f[8]), float(f[9]), f[10] == "1", f[11] == "1"))
        self.assertEqual(len(rows), len(STEPS) * 3 * 2, run.stdout)
        return rows

    def test_cloth_time(self):
        if not compiler():
            self.skipTest("no C compiler")
        wrong = []
        for switch in SWITCH:
            on = switch not in ("0", "off")
            for step, game, sub, own, scale, count, own_out, total, seconds, substep, same, kept in self.frames(switch):
                at = "step %g, the game's count %d x %d x %d, scale %g, HOS_FPS_CLOTH %s" % (step, game, sub, own, scale, switch)
                if count != game or own_out != own or total != game * sub * own:   # (no more solves)
                    wrong.append("%s: the frame data's counts %d, %d, %d, not the game's" % (at, count, own_out, total))
                if not math.isclose(substep * total, seconds, rel_tol=1e-5):
                    wrong.append("%s: the substeps add up to %.6f s of the %.6f s stored" % (at, substep * total, seconds))
                timed = on and 1.0 < step <= 8.0   # (below 60 fps; else, and for a bad step, the game's 60th)
                frame = (step if timed else 1.0) / 60 / scale
                if not math.isclose(seconds, frame, rel_tol=1e-5):
                    wrong.append("%s: the cloth steps %.2f ms where %.2f ms is right" % (at, seconds * 1000, frame * 1000))
                if not same or not kept:
                    wrong.append("%s: %s" % (at, "a second setup stored something else" if not same else "the context changed"))
        self.assertEqual(wrong, [], "%d frame data wrong:\n%s" % (len(wrong), "\n".join(wrong)))

    def test_patch(self):
        out, n = oot_patches.patch_cloth_time(LIFTED_CLOTH)
        self.assertEqual(n, 1)
        self.assertEqual(out.count(oot_patches.CLOTH_NEW), 1)
        self.assertNotIn(oot_patches.CLOTH_OLD, out)
        self.assertIn(oot_patches.CLOTH_DECL, out)
        self.assertLess(out.index("hos_oot_cloth_seconds("), out.index("recomp_stp32(c,(_b+_o)"))   # (before the time is stored)
        self.assertEqual(oot_patches.patch_cloth_time(out), (out, 1))   # (patched before: as it is)
        other = LIFTED_CLOTH.replace("(c->x[22]+8ULL)", "(c->x[22]+12ULL)")   # (another game version's code)
        self.assertEqual(oot_patches.patch_cloth_time(other), (other, 0))
        none = LIFTED_CLOTH.replace("void f_81b3aa48", "void f_91b3aa48")
        self.assertEqual(oot_patches.patch_cloth_time(none), (none, 0))
        self.assertEqual(oot_patches.patch_file(LIFTED_CLOTH, "code_cloth.c", False)[1]["cloth time"], 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
