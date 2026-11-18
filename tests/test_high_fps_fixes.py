"""Above a 60 fps cap the sound job runs at 60 Hz and the physics solver keeps whole-frame steps (host/oot_high_fps.h,
nx2/oot_patches.py patch_sound_job and patch_solver_steps).

Sound: under a Frame rate cap above 60 the frame step is the frame's own time (0.5 at 120 fps). The sound manager's job (f_80435300)
fed steps under 1 left sounds unreleased at area changes until the game's voice budget was full and sounds, then the music,
stopped. The gate runs phase 0 once a whole step has built up (120 frames of 0.5: 60 runs; 144 of 60/144: 60), the other phases
follow phase 0's choice, the engine is handed a whole step then, and a step of 1 or more, 0 or below, NaN, or no frame time at
all (a cap of 60) runs every frame with the game's own step. A step of 1 or more keeps the remainder, so around 60 fps (0.98 and
1.02 alternating, 0.9 and 1.1, or mean 1 with jitter) the sound clock keeps the real one; a cap of 60 runs every phase, before
the first phase 0 too and after a phase 0 that held the job.

Solver: the game cuts frame step * n + 0.001 to its solver steps (n a 60 fps frame: 8 at 60 fps, 3 or 4 at 120 as the step
wanders; with n = 4, 0 above 240). With the frames' own time and a step under 1 it is rounded up (10% leeway for the frame time's
jitter) and at least 1, never under the game's; a step of 1 or more, or no frame time (a cap of 60), keeps the game's count.

Music manager: its update (f_83373400, game::Bgm) runs inside the gated job but reads the step (+16) and the seconds (+24) from the
game's time object itself. Lifted as the game has it, run through patch_file, and called on the frames the gate runs it, its clock
keeps the real one: at 120 and 240 fps a whole step and that step's seconds each run (handed the frame's own, it ran at 0.5 and
0.25 of real time); at 60 fps, on a slow frame, and at a cap of 60 it reads the game's own values.

Music manager's change flags: the battle manager sets a byte of them ([[0x84c9dda0]]+0x4898: the battle music's name changed,
its distance volume, ...) for one game frame, and the music manager syncs a property for each bit it finds set. Held to 60 Hz it
saw a frame's flags only on the frames it ran: at 120 fps half the changes were lost (the battle music kept playing after the
fight, or stayed at a lower volume). The whole host file is compiled with stand-ins for guest memory and its lock, the update's
four flag reads (lifted as the game has them) go through patch_file, and frames run through the gate: a bit set for one frame is
handled once, whether the gate ran the job on that frame or held it, at 120 and 240 fps and at a cap of 60.

The patches put the gate at the job's head and the step through the host, hook both solver places and the music manager's two
loads and four flag reads, declare the hooks, and leave a file patched before, or whose code differs, as it is.

python -I -B tests/test_high_fps_fixes.py
"""
import re
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

FIXTURE = r"""
#include "oot_high_fps.h"
#include <stdio.h>
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); fails++; } } while (0)
static uint32_t bits(float f) { return oot_float_bits(f); }
static int runs(float step, int frames, int timed) {
    OotSoundGate g = OOT_SOUND_GATE_INIT;
    int n = 0;
    for (int i = 0; i < frames; i++) {
        const int run = oot_sound_gate(&g, 0, step, timed);
        CHECK(oot_sound_gate(&g, 1, step, timed) == run);   /* (phase 1 follows phase 0) */
        n += run;
    }
    return n;
}
/* (the sound engine's time over these frames' steps against the real time: what it is handed each frame the job runs) */
static double sound_clock(const float *steps, int n) {
    OotSoundGate g = OOT_SOUND_GATE_INIT;
    double real = 0, sound = 0;
    for (int i = 0; i < n; i++) {
        real += steps[i];
        if (oot_sound_gate(&g, 0, steps[i], 1)) sound += oot_bits_float(oot_sound_step(oot_float_bits(steps[i]), 1));
    }
    return sound / real;
}
int main(void) {
    CHECK(runs(0.5f, 120, 1) == 60);
    const int n144 = runs(60.0f / 144.0f, 144, 1);
    CHECK(n144 == 60 || n144 == 59);
    CHECK(runs(60.0f / 1000.0f, 1000, 1) >= 59 && runs(60.0f / 1000.0f, 1000, 1) <= 60);
    CHECK(runs(0.5f, 120, 0) == 120);   /* (a cap of 60: every frame) */
    CHECK(runs(1.0f, 60, 1) == 60 && runs(1.5f, 60, 1) == 60);
    CHECK(runs(0.0f, 60, 1) == 60 && runs(-1.0f, 60, 1) == 60 && runs(NAN, 60, 1) == 60);
    {   /* (a whole step after partial ones runs with the game's step and keeps the remainder) */
        OotSoundGate g = OOT_SOUND_GATE_INIT;
        CHECK(oot_sound_gate(&g, 0, 0.75f, 1) == 0 && oot_sound_gate(&g, 2, 0.75f, 1) == 0);
        CHECK(oot_sound_gate(&g, 0, 1.0f, 1) == 1 && g.part == 0.75f && oot_sound_gate(&g, 1, 1.0f, 1) == 1);
        CHECK(oot_sound_gate(&g, 0, 0.75f, 1) == 1 && g.part == 0.5f);
        CHECK(oot_sound_gate(&g, 0, 0.0f, 1) == 1 && g.part == 0.0f);   /* (a step of 0: as the game has it, the remainder cleared) */
    }
    {   /* (around 60 fps the sound clock keeps the real one: dropping the remainder at each whole step made it 0.51 of it) */
        static float steps[20000];
        for (int i = 0; i < 20000; i++) steps[i] = i & 1 ? 1.02f : 0.98f;
        double r = sound_clock(steps, 20000);
        CHECK(r > 0.999 && r < 1.001);
        for (int i = 0; i < 20000; i++) steps[i] = i & 1 ? 1.1f : 0.9f;
        r = sound_clock(steps, 20000);
        CHECK(r > 0.999 && r < 1.001);
        uint32_t x = 12345;   /* (mean 1, about 0.03 apart: a sum of uniforms) */
        for (int i = 0; i < 20000; i++) {
            float u = 0;
            for (int k = 0; k < 12; k++) x = x * 1664525u + 1013904223u, u += (float)(x >> 8) / 16777216.0f;
            steps[i] = 1.0f + (u - 6.0f) * 0.03f;
        }
        r = sound_clock(steps, 20000);
        CHECK(r > 0.999 && r < 1.001);
        for (int i = 0; i < 20000; i++) steps[i] = 0.5f;
        r = sound_clock(steps, 20000);
        CHECK(r > 0.999 && r < 1.001);
    }
    {   /* (a cap of 60 runs every phase: before any phase 0, and after a phase 0 that held the job at a cap above 60) */
        OotSoundGate g = OOT_SOUND_GATE_INIT;
        CHECK(oot_sound_gate(&g, 1, 1.0f, 0) == 1 && oot_sound_gate(&g, 2, 1.0f, 0) == 1);
        OotSoundGate h = OOT_SOUND_GATE_INIT;
        CHECK(oot_sound_gate(&h, 1, 1.0f, 1) == 1);   /* (above 60, before the first phase 0: it runs) */
        CHECK(oot_sound_gate(&h, 0, 0.5f, 1) == 0 && oot_sound_gate(&h, 1, 0.5f, 0) == 1 && h.part == 0.0f);   /* (the cap changed) */
        CHECK(oot_sound_gate(&h, 2, 0.5f, 0) == 1 && oot_sound_gate(&h, 0, 0.5f, 0) == 1);
    }
    CHECK(oot_sound_step(bits(0.5f), 1) == bits(1.0f));
    CHECK(oot_sound_step(bits(0.5f), 0) == bits(0.5f));
    CHECK(oot_sound_step(bits(1.25f), 1) == bits(1.25f) && oot_sound_step(bits(0.0f), 1) == bits(0.0f));
    /* (the game's: (int)(step * n + 0.001), n the steps of a 60 fps frame) */
    #define GAME(step, n) ((int32_t)((step) * (n) + 0.001f))
    #define OURS(step, n, timed) oot_solver_steps(GAME(step, n), bits((step) * (n) + 0.001f), bits(n), timed)
    CHECK(OURS(1.0f, 4.0f, 1) == 4 && OURS(1.0f, 8.0f, 1) == 8 && OURS(1.0f, 8.0f, 0) == 8);
    CHECK(OURS(0.5f, 4.0f, 1) == 2 && OURS(0.49f, 4.0f, 1) == 2 && OURS(0.52f, 4.0f, 1) == 2 && GAME(0.49f, 4.0f) == 1);
    CHECK(OURS(0.49f, 8.0f, 1) == 4 && OURS(0.5f, 8.0f, 1) == 4 && GAME(0.49f, 8.0f) == 3);
    CHECK(OURS(0.25f, 4.0f, 1) == 1 && OURS(0.24f, 4.0f, 1) == 1 && OURS(0.06f, 4.0f, 1) == 1 && GAME(0.24f, 4.0f) == 0);
    CHECK(OURS(60.0f / 144.0f, 4.0f, 1) == 2 && OURS(60.0f / 90.0f, 4.0f, 1) == 3);
    CHECK(OURS(0.49f, 4.0f, 0) == 1 && OURS(0.06f, 4.0f, 0) == 0);   /* (a cap of 60: the game's count) */
    CHECK(OURS(1.6f, 4.0f, 1) == 6 && OURS(1.708f, 8.0f, 1) == 13);   /* (a slow frame: the game's count) */
    CHECK(oot_solver_steps(3, bits(NAN), bits(4.0f), 1) == 3 && oot_solver_steps(0, bits(-1.0f), bits(4.0f), 1) == 0);
    CHECK(oot_solver_steps(1, bits(2.0f), bits(0.0f), 1) == 1);   /* (no steps a frame: the game's) */
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""

LIFTED_SOUND = ('#include "a64.h"\n' + oot_patches.SOUND_HEAD + "    /* nop/hint */\nif ((uint32_t)c->x[2] != 0) { goto L_1; }\n"
                + oot_patches.SOUND_OLD + "L_1:;\n    return;\n}\nvoid f_80435360(Ctx *__restrict A64_NOESC c) {\n"
                + oot_patches.SOUND_OLD + "}\n")
# (the music manager's update as the lift writes its head: the time object's pointer, its step into s8 and its seconds into s9)
LIFTED_BGM = """#include "a64.h"
void f_83373400(Ctx *__restrict A64_NOESC c) {
    c->x[8]=g_module_base + 0x83373000ULL + (int64_t)26390528;
    { uint64_t _r = ((uint64_t)0 | ((c->x[0]) << 0)); c->x[19] = _r; }
    c->x[8]=recomp_load64(c,c->x[8] + 2192);
    c->x[8]=recomp_load64(c,c->x[8] + 0);
    { { uint64_t _v=recomp_load32(c,(c->x[8]+16ULL)); a64_vset64(c->vreg[8],_v); } }
    { { uint64_t _v=recomp_load32(c,(c->x[8]+24ULL)); a64_vset64(c->vreg[9],_v); } }
    return;
}
"""

# (stand-ins for the lift's runtime: the time object at 0x2000 behind the pointer at 0x84c9e890; then the host's hos_oot_sound_*
# functions cut from host/oot_high_fps.c, the patched update, and the frames: the clock the update counts against the real one)
BGM_RUNTIME = r"""
#include <stdint.h>
#include <stdio.h>
#include "oot_high_fps.h"
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; } Ctx;
#define A64_NOESC
static const uint64_t g_module_base = 0;
static uint32_t step_bits, seconds_bits;
static int is_timed;
static int timed(void) { return is_timed; }
static uint64_t recomp_load64(Ctx *c, uint64_t a) { (void)c; return a == 0x84c9e890ULL ? 0x1000 : a == 0x1000 ? 0x2000 : 0; }
static uint64_t recomp_load32(Ctx *c, uint64_t a) { (void)c; return a == 0x2010 ? step_bits : a == 0x2018 ? seconds_bits : 0; }
static void a64_vset64(uint64_t *v, uint64_t value) { v[0] = value; v[1] = 0; }
"""

BGM_FRAMES = r"""
/* fps frames of the game's step (60 / fps) and seconds (1 / fps): the update's steps and seconds over the real ones */
static void clock(float step, int frames, int timed_now, double *steps, double *seconds) {
    OotSoundGate g = OOT_SOUND_GATE_INIT;
    Ctx c = {0};
    double s = 0, t = 0;
    is_timed = timed_now;
    step_bits = oot_float_bits(step), seconds_bits = oot_float_bits(step / 60.0f);
    for (int i = 0; i < frames; i++)
        if (oot_sound_gate(&g, 0, step, timed_now)) {
            f_83373400(&c);
            s += oot_bits_float((uint32_t)c.vreg[8][0]), t += oot_bits_float((uint32_t)c.vreg[9][0]);
        }
    *steps = s / (step * frames), *seconds = t / (step / 60.0f * frames);
}
int main(void) {
    const float steps[] = {0.5f, 0.25f, 1.0f, 1.5f, 0.5f};
    const int timed_now[] = {1, 1, 1, 1, 0};
    for (int i = 0; i < 5; i++) {
        double s, t;
        clock(steps[i], 2400, timed_now[i], &s, &t);
        printf("%g %d %.4f %.4f\n", steps[i], timed_now[i], s, t);
    }
    return 0;
}
"""


# (the update's four reads of the change flags, as the lift writes them, each followed by a call where the bit's handler starts:
# the stand-in f_837ab1d0 counts the bit by the call's return address)
LIFTED_BGM_FLAGS = """#include "a64.h"
void f_83373400(Ctx *__restrict A64_NOESC c) {
    c->x[25]=g_module_base + 0x83373000ULL + (int64_t)26386432;
    c->x[25]=recomp_load64(c,c->x[25] + 3488);
    c->x[22]=recomp_load64(c,c->x[25] + 0);
    { uint64_t _a=c->x[22], _b=16384ULL; uint64_t _r=_a+_b; c->x[26]=_r; }
    c->x[8]=recomp_load8(c,c->x[26] + 2200);
if (!((c->x[8] >> 5) & 1)) { goto L_83373770; }
c->x[30] = 0x833736b8ULL; f_837ab1d0(c);
L_83373770:;
    c->x[8]=recomp_load8(c,c->x[26] + 2200);
if (!((c->x[8] >> 1) & 1)) { goto L_8337388c; }
c->x[30] = 0x833737f0ULL; f_837ab1d0(c);
L_8337388c:;
    c->x[8]=recomp_load8(c,c->x[26] + 2200);
if (!((c->x[8] >> 2) & 1)) { goto L_83373a4c; }
c->x[30] = 0x83373978ULL; f_837ab1d0(c);
L_83373a4c:;
    c->x[8]=recomp_load8(c,c->x[26] + 2200);
if (!((c->x[8] >> 6) & 1)) { goto L_83373ad4; }
c->x[30] = 0x83373a80ULL; f_837ab1d0(c);
L_83373ad4:;
    return;
}
"""

# (stand-ins for the host file's and the lift's world: guest memory as one array with the time object's and the battle manager's
# slots, a lock that is none, no log)
FLAGS_RUNTIME = r"""
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "oot_high_fps.h"
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; } Ctx;
#define A64_NOESC
static const uint64_t g_module_base = 0;
static uint8_t mem[0x20000];
static uint8_t *guest(uint64_t a) {
    if (a == 0x84c9e890ULL) return mem + 0x100;   /* (the time object's slot) */
    if (a == 0x84c9dda0ULL) return mem + 0x108;   /* (the battle manager's) */
    return a < sizeof mem ? mem + a : mem;
}
#define GP(a) ((void *)guest(a))
#define G64(a) (*(uint64_t *)GP(a))
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
static void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; }
typedef long long LONG64;
static LONG64 InterlockedIncrement64(volatile LONG64 *p) { return ++*p; }
static void hos_log(const char *f, ...) { (void)f; }
static int env_on(const char *name) { (void)name; return 0; }
volatile uint32_t hos_frame_seconds_bits;
static uint64_t recomp_load64(Ctx *c, uint64_t a) { (void)c; return G64(a); }
static uint64_t recomp_load32(Ctx *c, uint64_t a) { uint32_t v; (void)c; memcpy(&v, guest(a), 4); return v; }
static uint64_t recomp_load8(Ctx *c, uint64_t a) { (void)c; return *guest(a); }
static void a64_vset64(uint64_t *v, uint64_t value) { v[0] = value; v[1] = 0; }
static int handled[8];
static void f_837ab1d0(Ctx *c) {
    switch (c->x[30]) {
    case 0x833736b8ULL: handled[5]++; break;
    case 0x833737f0ULL: handled[1]++; break;
    case 0x83373978ULL: handled[2]++; break;
    case 0x83373a80ULL: handled[6]++; break;
    }
}
"""

FLAGS_FRAMES = r"""
#define FLAGS_AT (0x10000 + 16384 + 2200)
static Ctx ctx;
/* one game frame of step (60 / fps; no frame time given at a cap of 60) with the flag byte at flags: the job's phases as the game
   calls them, the update on phase 1 when the gate runs it */
static void frame(float step, int timed_now, uint8_t flags) {
    const float seconds = step / 60.0f;
    uint32_t b;
    memcpy(&b, &seconds, 4);
    hos_frame_seconds_bits = timed_now ? b : 0;
    memcpy(mem + 0x2010, &step, 4);
    mem[FLAGS_AT] = flags;
    for (uint32_t phase = 0; phase < 3; phase++)
        if (hos_oot_sound_gate(&ctx, phase, 0x84c9e890ULL) && phase == 1) f_83373400(&ctx);
    mem[FLAGS_AT] = 0;   /* (the battle manager clears them by the next frame) */
}
int main(void) {
    const uint64_t time_at = 0x1000, battle = 0x10000;
    memcpy(mem + 0x100, &time_at, 8);
    const uint64_t time_obj = 0x2000;
    memcpy(mem + 0x1000, &time_obj, 8);
    const uint64_t battle_at = 0x3000;
    memcpy(mem + 0x108, &battle_at, 8);
    memcpy(mem + 0x3000, &battle, 8);
    const float steps[] = {0.5f, 0.25f, 1.0f};
    const int timed_now[] = {1, 1, 0};
    const int bits[] = {5, 1, 6};
    for (int i = 0; i < 3; i++)
        for (int w = 0; w < 8; w++)
            for (int k = 0; k < 3; k++) {
                for (int f = 0; f < 4; f++) frame(steps[i], timed_now[i], 0);   /* (settle: what an earlier window left is handled) */
                memset(handled, 0, sizeof handled);
                for (int f = 0; f < w; f++) frame(steps[i], timed_now[i], 0);
                frame(steps[i], timed_now[i], (uint8_t)(1u << bits[k]));
                for (int f = 0; f < 8; f++) frame(steps[i], timed_now[i], 0);
                printf("%g %d %d %d %d\n", steps[i], timed_now[i], w, bits[k], handled[bits[k]]);
            }
    return 0;
}
"""


def host_file_for_test(source):
    """host/oot_high_fps.c without its includes but the logic's header, for FLAGS_RUNTIME's stand-ins"""
    keep = ('#include "oot_high_fps.h"',)
    return "\n".join(line for line in source.split("\n") if not line.startswith("#include") or line in keep)


def hos_sound_functions(source):
    """host/oot_high_fps.c's hos_oot_sound_* functions that return the float's bits (the step, and the seconds when there)"""
    names = sorted(set(m.group(1) for m in re.finditer(r"^uint32_t (hos_oot_sound_\w+)\(", source, re.M)))
    return "\n".join(block(source, "uint32_t %s(" % name) for name in names)


LIFTED_SOLVER = '#include "a64.h"\n' + "".join(head + "    c->x[8]=1;\n" + oot_patches.SOLVER_OLD + "}\n"
                                               for head in oot_patches.SOLVER_HEADS)


class HighFpsTests(unittest.TestCase):
    def test_gate_and_steps(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory(prefix="hookshot-high-fps-") as tmp:
            tmp = Path(tmp)
            (tmp / "t.c").write_text(FIXTURE, encoding="utf-8")
            binary = tmp / "t.exe"
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-O1", "-I", str(ROOT / "host"), str(tmp / "t.c"),
                                    "-o", str(binary), "-lm"], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_sound_patch(self):
        out, n = oot_patches.patch_sound_job(LIFTED_SOUND)
        self.assertEqual(n, 1)
        head = out.index(oot_patches.SOUND_HEAD) + len(oot_patches.SOUND_HEAD)
        self.assertTrue(out[head:].startswith(oot_patches.SOUND_GATE))   # (before the job's own first instruction)
        self.assertEqual(out.count("hos_oot_sound_gate(c,"), 1)
        self.assertEqual(out.count(oot_patches.SOUND_NEW), 1)   # (the job's own load only, not the next function's)
        self.assertEqual(out.count(oot_patches.SOUND_OLD), 1)
        self.assertIn(oot_patches.SOUND_DECL, out)
        self.assertEqual(oot_patches.patch_sound_job(out), (out, 1))   # (patched before: as it is)
        other = LIFTED_SOUND.replace("+ 2192)", "+ 2200)")   # (another game version's code)
        self.assertEqual(oot_patches.patch_sound_job(other), (other, 0))
        none = LIFTED_SOUND.replace("void f_80435300", "void f_90435300")
        self.assertEqual(oot_patches.patch_sound_job(none), (none, 0))

    def test_music_manager_clock(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        patched = oot_patches.patch_file(LIFTED_BGM, "code_bgm.c", False)[0]
        host = (ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8")
        program = (BGM_RUNTIME + hos_sound_functions(host) + "\n" + patched.replace('#include "a64.h"\n', "")
                   + BGM_FRAMES)
        with tempfile.TemporaryDirectory(prefix="hookshot-high-fps-") as tmp:
            tmp = Path(tmp)
            (tmp / "bgm.c").write_text(program, encoding="utf-8")
            binary = tmp / "bgm.exe"
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-O1", "-I", str(ROOT / "host"), str(tmp / "bgm.c"),
                                    "-o", str(binary), "-lm"], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        lines = [line for line in run.stdout.split("\n") if line]
        self.assertEqual(len(lines), 5, run.stdout)
        for line in lines:
            step, timed, steps, seconds = line.split()
            what = "music manager clock at a step of %s%s" % (step, "" if timed == "1" else ", a cap of 60")
            # (each ratio: what the update counted over the real time; a step of 0.5 at a cap of 60 runs every frame with it)
            self.assertAlmostEqual(float(steps), 1.0, delta=0.01, msg="%s: %s of the real steps" % (what, steps))
            self.assertAlmostEqual(float(seconds), 1.0, delta=0.01, msg="%s: %s of the real seconds" % (what, seconds))

    def test_music_manager_flags(self):
        compiler = shutil.which("gcc") or shutil.which("clang")
        if not compiler:
            self.skipTest("no C compiler")
        patched = oot_patches.patch_file(LIFTED_BGM_FLAGS, "code_bgm.c", False)[0]
        host = (ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8")
        program = (FLAGS_RUNTIME + host_file_for_test(host) + "\n" + patched.replace('#include "a64.h"\n', "")
                   + FLAGS_FRAMES)
        with tempfile.TemporaryDirectory(prefix="hookshot-high-fps-") as tmp:
            tmp = Path(tmp)
            (tmp / "flags.c").write_text(program, encoding="utf-8")
            binary = tmp / "flags.exe"
            build = subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wno-unused-function", "-O1", "-I", str(ROOT / "host"),
                                    str(tmp / "flags.c"), "-o", str(binary), "-lm"], text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        lines = [line for line in run.stdout.split("\n") if line]
        self.assertEqual(len(lines), 72, run.stdout)
        lost = []
        for line in lines:
            step, timed, frame, bit, handled = line.split()
            if handled != "1":   # (0: the change was lost; 2: handled twice, a count in the game run down twice)
                lost.append("bit %s set on frame %s at a step of %s%s: handled %s times" % (
                    bit, frame, step, "" if timed == "1" else " (a cap of 60)", handled))
        self.assertEqual(lost, [], "%d of %d one-frame flags not handled once:\n%s" % (len(lost), len(lines), "\n".join(lost)))

    def test_solver_patch(self):
        out, n = oot_patches.patch_solver_steps(LIFTED_SOLVER)
        self.assertEqual(n, 2)
        self.assertEqual(out.count(oot_patches.SOLVER_NEW), 2)
        self.assertIn(oot_patches.SOLVER_DECL, out)
        hook = out.index("hos_oot_solver_steps((uint32_t)c->x[1]")
        self.assertLess(out.index("recomp_fp_to_int"), hook)
        self.assertLess(hook, out.index("recomp_store32(c,c->x[0] + 712"))
        self.assertEqual(oot_patches.patch_solver_steps(out), (out, 2))
        other = LIFTED_SOLVER.replace("+ 712", "+ 716")
        self.assertEqual(oot_patches.patch_solver_steps(other), (other, 0))


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
