"""The water ripples step every frame above 60 fps (issue 1199; nx2/oot_patches.py patch_whole_frames, host/frame_whole.h).

The water renderer (f_800672e0) runs (int)step * substeps simulation substeps a frame, the substeps a water object's +76.
Under a Frame rate cap above 60 the step is the frame's own time (0.56 at 108 fps). With the whole frames carried per water
object, the cut gave 0 frames on some frames and 1 on others: all of a frame's substeps at once, or none, so the rings
stood still for a frame and then jumped (seen at the Great Fairy fountains and in Zora's Domain, fine at a cap of 60).
The substeps are carried instead: at 108 fps with 4 substeps a frame, every frame runs 2 or 3 of them, the 240 a second
the console runs at 60.

The check takes the lifted lines of the site (the substeps' load, the cut, the multiply and its store), patches them with
patch_file as the build does, and compiles them with host/nn_vi.c's own entry points cut out of it, over frames at 108 and
144 fps, a cap of 60 and 30 fps. A lift patched by an earlier build (the whole frames' hook in place) is patched again to
the substeps. Needs a C compiler (gcc or clang).

python -I -B tests/test_water_substeps.py
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import oot_patches  # noqa: E402
from srccut import block  # noqa: E402

HEAD = "void f_800672e0(Ctx *__restrict A64_NOESC c) {\n"
LOAD = "    c->x[8]=recomp_load32(c,c->x[19] + 76);\n"
CUT = "    c->x[9]=recomp_fp_to_int(c->vreg[0][0]&UINT64_C(0xffffffff),32,32,1,3,c->fpcr,&c->fpsr);\n"
EARLIER = ("    c->x[9]=hos_frame_whole(c->x[21], (uint32_t)c->vreg[0][0]);   "
           "/* (the step's whole frames: nx2/oot_patches.py) */\n")   # (the hook main's builds made)
REST = ("    c->x[27]=g_module_base + 0x80067000ULL + (int64_t)79933440;\n"
        "    { uint64_t _r = (uint64_t)0 + (c->x[8] * c->x[9]); _r &= 0xFFFFFFFFULL; c->x[8] = _r; }\n"
        "    recomp_store32_sp(c,c->x[31] + 52,c->x[8]);\n"
        "    return;\n}\n")
LIFTED = '#include "a64.h"\n' + HEAD + LOAD + CUT + REST

A64_H = r"""
#include <stdint.h>
#include <string.h>
#define A64_NOESC
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; uint32_t fpcr, fpsr; } Ctx;
static uint64_t g_module_base;
static uint32_t substeps_of_water;   /* (the water object's +76) */
static uint32_t ran;                 /* (the substeps the frame runs: what the function stores at sp+52) */
static inline uint64_t recomp_load32(Ctx *c, uint64_t a) { return a == c->x[19] + 76 ? substeps_of_water : 0; }
static inline void recomp_store32_sp(Ctx *c, uint64_t a, uint64_t v) { (void)c; (void)a; ran = (uint32_t)v; }
static inline uint64_t recomp_fp_to_int(uint64_t bits, int a, int b, int s, int r, uint32_t fpcr, uint32_t *fpsr) {
    (void)a; (void)b; (void)s; (void)r; (void)fpcr; (void)fpsr;
    float f; uint32_t u = (uint32_t)bits; memcpy(&f, &u, 4);
    return f > 0.0f ? (uint64_t)(uint32_t)f : 0;
}
"""

DRIVER = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
/* (host/nn_vi.c's surroundings of the cut) */
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
#define AcquireSRWLockExclusive(l) ((void)(l))
#define ReleaseSRWLockExclusive(l) ((void)(l))
volatile uint32_t hos_frame_seconds_bits;
#include "frame_whole.h"
static FrameWhole frame_whole_state;
static SRWLOCK frame_whole_lock = SRWLOCK_INIT;
%(host)s
#include "patched.c"
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %%d: %%s\n", __LINE__, #c); fails++; } } while (0)
static uint32_t bits(float f) { uint32_t b; memcpy(&b, &f, 4); return b; }
/* (one water object's frames at fps, its substeps per; the least and most substeps a frame and their sum) */
static void frames(int fps, uint32_t per, int carry, uint32_t *least, uint32_t *most, uint32_t *sum) {
    static uint64_t water = 0x7100000;
    Ctx c; memset(&c, 0, sizeof c);
    c.x[21] = water += 0x400;   /* (a new object each run: its own remainder) */
    c.x[19] = 0x5000;
    substeps_of_water = per;
    const float step = 60.0f / (float)fps;
    hos_frame_seconds_bits = carry ? bits(1.0f / (float)fps) : 0;
    *least = 0xffffffffu, *most = 0, *sum = 0;
    for (int f = 0; f < fps; f++) {
        c.vreg[0][0] = bits(step);
        f_800672e0(&c);
        if (ran < *least) *least = ran;
        if (ran > *most) *most = ran;
        *sum += ran;
    }
}
int main(void) {
    uint32_t lo, hi, n;
    frames(108, 4, 1, &lo, &hi, &n);   /* (the fountain at a 240 cap, about 108 fps) */
    printf("108 fps, 4 substeps: %%u to %%u a frame, %%u a second\n", lo, hi, n);
    CHECK(lo >= 2 && hi <= 3);         /* (every frame steps: no frame stands still, none runs all four at once) */
    CHECK(n >= 239 && n <= 240);       /* (the 240 a second of 60 fps) */
    frames(144, 4, 1, &lo, &hi, &n);
    printf("144 fps, 4 substeps: %%u to %%u a frame, %%u a second\n", lo, hi, n);
    CHECK(lo >= 1 && hi <= 2);
    CHECK(n >= 239 && n <= 240);
    frames(144, 1, 1, &lo, &hi, &n);   /* (one substep a frame: whole substeps, as before, at the game's rate) */
    CHECK(hi <= 1 && n >= 59 && n <= 60);
    frames(60, 4, 0, &lo, &hi, &n);    /* (a cap of 60: the game's own step, cut as it cuts it) */
    CHECK(lo == 4 && hi == 4 && n == 240);
    frames(30, 4, 0, &lo, &hi, &n);    /* (30 fps: the step is 2, two frames' substeps) */
    CHECK(lo == 8 && hi == 8);
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


def host_entry_points():
    """host/nn_vi.c's hooks for patch_whole_frames, cut out of it"""
    text = (ROOT / "host" / "nn_vi.c").read_text(encoding="utf-8")
    cuts = [block(text, "uint32_t hos_frame_whole(uint64_t at, uint32_t amount_bits) {")]
    if "uint32_t hos_frame_whole_times(" in text:
        cuts.append(block(text, "uint32_t hos_frame_whole_times("))
    return "\n".join(cuts)


class WaterSubstepTests(unittest.TestCase):
    def run_frames(self, lifted):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        patched, counts, _ = oot_patches.patch_file(lifted, "code_000.c")
        self.assertEqual(counts["whole sites"], 1, patched)
        self.assertNotIn("recomp_fp_to_int(c->vreg[0][0]", patched)
        with tempfile.TemporaryDirectory(prefix="longshot-water-substeps-") as tmp:
            tmp = Path(tmp)
            (tmp / "a64.h").write_text(A64_H, encoding="utf-8")
            (tmp / "patched.c").write_text(patched, encoding="utf-8")
            (tmp / "t.c").write_text(DRIVER % {"host": host_entry_points()}, encoding="utf-8")
            binary = tmp / "t.exe"
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-O1", "-I", str(tmp), "-I", str(ROOT / "host"),
                                    str(tmp / "t.c"), "-o", str(binary), "-lm"], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_every_frame_steps_above_60(self):
        self.run_frames(LIFTED)

    def test_a_lift_patched_before_takes_the_substeps(self):
        # (a work folder whose lift main's build patched keeps its translation: the next build must still reach the site)
        self.run_frames(LIFTED.replace(CUT, EARLIER))


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
