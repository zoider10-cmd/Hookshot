"""Link's driven body's target above 60 fps (nx2/oot_patches.py patch_drive_target, host/oot_high_fps.h oot_drive_carry).

While Link pulls himself up a ledge his animation drives his body: each update f_804f5030 (a rigid body's update before the
physics step, on its path for a body driven to a target) reads the controller's target (+0x3c), which the game set to the
body's position plus this frame's move, and asks the physics for (target - position) / dt. At 60 fps the body lands on the
target. Above 60 Havok's solve delivers only part of the move (measured in the game: 1.00 at 60, 0.94 at 90, 0.86 at 120,
0.82 at 144, 0.78 at 170 fps, close to 1 - 0.126 (1/step - 1)), and the next target starts from where the body ended up:
the pull-up fell 0.3 m short and Link slid back on the lip (issue 1494). The patch has the host add last update's shortfall
to the target before it is read.

An authored f_804f5030 (the game's gate to the path, the controller's flags +0x100 bit 0x80, then both copies of the path's
load of the body and reads of the target as the lift writes them) goes through patch_file and is compiled with the host's
part cut from host/oot_high_fps.c (Link's body and his update count from his components, the target's carry); guest memory,
the time object and the switches are stand-ins. Each update calls hos_oot_note_link (Link's update, host/hos_main.c), then
the body update; a stand-in physics moves the body by the measured share of the target read. The pull-up's lift (1.92 m up,
0.08 m in, over 0.4 s) is played update by update:
- at a cap of 60 the body follows the lift (both ways); with the body held back, nothing is carried, at a step of 1 or with
  time slowed (a step of 0.5);
- above 60 (120, 144, 170 and 240 fps), through either copy of the path, it ends within 0.5% of the lift up and within 1 mm
  in (short by 14% at 120 before the fix);
- not Link's body, a controller on the path but not handing a velocity (flags 0x80 without 0x100), a frame slower than 60
  fps (with the body held back), a NaN or infinite target and an infinite body position are left as the game has them;
- a climb after updates where the path was not reached (as between two climbs in the game; one such update is enough)
  starts from the game's own target, and so does Link's body changing (an area change);
- a target the game did not renew is read as it is (the carry is not added again), a second call in the same update,
  mid-climb, reads the same target as the first, and body updates with no update of Link's before them still follow
  the game's renewed targets (none held back);
- a body the physics holds back is given at most three frames' moves more than the game's target (it is not flung);
- host/hos_main.c's Link update calls hos_oot_note_link on every update, before the cheats' lock and under no condition
  (the wiring the game needs; the fixture calls it itself);
- the unpatched update compiled the same way fails the 120 fps check (the bug, shown without the fix);
- the patch is scoped to f_804f5030, at its two places, a second run changes nothing, and a changed anchor is left alone
  with a warning.
No game files or lifted function body are used.

python -I -B tests/test_drive_target.py [--cc gcc]
"""
import argparse
import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402
sys.path.insert(0, str(ROOT / "tests"))   # (python -I leaves the check's own folder off the path)
from srccut import between, block  # noqa: E402

# (the body update as the lift writes it: the game's gate to the path, then both copies of the body's load and the target's
# reads; the stand-in keeps the target it read in c->read)
READ = ("    c->x[%d]=recomp_load64(c,c->x[20] + 240);\n"
        "    { uint64_t _b=c->x[20]; int64_t _o=60; { uint64_t _p0,_p1; recomp_ldp32(c,(_b+_o),&_p0,&_p1); "
        "a64_vset64(c->vreg[2],_p0); a64_vset64(c->vreg[1],_p1); }}\n"
        "    { { uint64_t _v=recomp_load32(c,(c->x[20]+68ULL)); a64_vset64(c->vreg[0],_v); } }\n")
KEEP = "    c->read[0] = (uint32_t)c->vreg[2][0]; c->read[1] = (uint32_t)c->vreg[1][0]; c->read[2] = (uint32_t)c->vreg[0][0];\n"
UPDATE = ("void f_804f5030(Ctx *__restrict A64_NOESC c) {\n"
          "    c->x[8]=recomp_load64(c,c->x[20] + 256);\n"
          "if (!((c->x[8] >> 7) & 1)) { goto L_804f5d10; }\n"
          "if (c->second) { goto L_804f5e9c; }\n" + READ % 23 + KEEP +
          "{ goto L_804f5d10; }\n"
          "L_804f5e9c:;\n" + READ % 24 + KEEP +
          "L_804f5d10:;\n"
          "}\n")
UNRELATED = UPDATE.replace("void f_804f5030(", "void f_904f5030(")
LIFTED = '#include "a64.h"\n' + UPDATE + UNRELATED

FIXTURE = r'''#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "oot_high_fps.h"
#define A64_NOESC
#define HOS_HEAP_BASE 0x1000ULL
typedef struct { uint64_t x[32]; uint64_t vreg[32][2]; uint8_t n, z, c, v; uint32_t read[3]; int second; } Ctx;
static const uint64_t g_module_base = 0;
static void a64_vset64(uint64_t *v, uint64_t bits) { v[0] = bits; v[1] = 0; }
/* (guest memory: the game's time object behind [0x84c9e890] (its step at +0x10, at 0x2810), the controller at 0x1000 (its target
   at +0x3c, its body at +0xf0, its flags at +0x100), Link's body at 0x2000 or 0x2400 (its position at +0x8c, +0x9c, +0xac),
   his components at 0x3000 (+0x50 -> +0x20 -> +0x10 -> +8 -> +0x20: the body)) */
static uint8_t mem[0x4000];
static uint8_t *guest(uint64_t a) {
    if (a == 0x84c9e890ULL) return mem + 0x100;
    return a < sizeof mem ? mem + a : mem;
}
#define GP(a) ((void *)guest(a))
static void *hos_guest_range(uint64_t a, uint64_t n) { return a + n <= sizeof mem ? mem + a : NULL; }
#define G64(a) (*(uint64_t *)GP(a))
static uint64_t recomp_load64(Ctx *c, uint64_t a) { uint64_t v; (void)c; memcpy(&v, guest(a), 8); return v; }
static uint64_t recomp_load32(Ctx *c, uint64_t a) { uint32_t v; (void)c; memcpy(&v, guest(a), 4); return v; }
static void recomp_ldp32(Ctx *c, uint64_t a, uint64_t *p0, uint64_t *p1) { *p0 = recomp_load32(c, a); *p1 = recomp_load32(c, a + 4); }
typedef long long LONG64;
#define InterlockedIncrement64(p) (++*(p))
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
static void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; }
static void hos_log(const char *f, ...) { (void)f; }
static int is_timed;
static int timed(void) { return is_timed; }
static int fps_log(void) { return 1; }
@HOST@
@UPDATE@
static int failures, checks;
static void check(int ok, const char *what) {
    checks++;
    if (!ok) { printf("FAIL: %s\n", what); failures++; }
}
static float getf(uint64_t a) { float f; memcpy(&f, guest(a), 4); return f; }
static void setf(uint64_t a, float f) { memcpy(guest(a), &f, 4); }
/* (the pull-up's lift: 1.92 m up and 0.08 m in over 0.4 s, eased in and out) */
static float lift(float t, float total) { if (t > 0.4f) t = 0.4f; return total * (1.0f - cosf(3.14159265f * t / 0.4f)) * 0.5f; }
/* (the physics' share of a driven body's move, as measured in the game: all at 60 fps and slower) */
static float share(float step) { return step >= 1.0f ? 1.0f : 1.0f - 0.126f * (1.0f / step - 1.0f); }
static uint64_t body = 0x2000;              /* (the controller's body) */
static int is_link = 1;                     /* (Link's components point at it) */
static uint64_t flags = 0x200180;
static int second;                          /* (the copy of the path the update takes) */
static int held_from = -1, held_to = -1;    /* (updates the physics holds the body back) */
static int stale_from = -1, stale_to = -1;  /* (updates the game does not renew the target) */
static float worst_extra;                   /* (the most the target read went past the game's, over the frame's move) */
static int changed, stale_grew;             /* (updates read differing from the game's; stale updates read differing from memory) */
static int twice_at = -1, twice_same;      /* (an update the body update runs twice; whether both read the same target) */
static int flat_from = -1, flat_to = -1;   /* (updates Link's own update does not run before the body update) */
static int standing = 5;                   /* (updates the path is not reached before a climb) */
static void place(float x, float y, float z) { setf(body + 0x8c, x); setf(body + 0x9c, y); setf(body + 0xac, z); }
static void setup(float step, int timed_now) {
    is_timed = timed_now;
    const uint32_t s = oot_float_bits(step);
    G64(0x84c9e890ULL) = 0x2800;
    G64(0x2800) = 0x2800;
    memcpy(mem + 0x2810, &s, 4);
    G64(0x1000 + 0xf0) = body;
    G64(0x3000 + 0x50) = 0x3100; G64(0x3100 + 0x20) = 0x3200; G64(0x3200 + 0x10) = 0x3300; G64(0x3300 + 8) = 0x3400;
    G64(0x3400 + 0x20) = is_link ? body : 0x2c00;
}
/* one update: Link's (hos_oot_note_link), then the body update with flags f; the target it read in t (the target in memory when
   the path was not reached) */
static int link_runs = 1;   /* (0: Link's update does not run before this body update) */
static void update(uint64_t f, float t[3]) {
    if (link_runs) hos_oot_note_link(0x3000);
    G64(0x1000 + 0x100) = f;
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[20] = 0x1000;
    c.second = second;
    for (int i = 0; i < 3; i++) memcpy(&c.read[i], GP(0x1000 + 0x3c + 4 * i), 4);
    f_804f5030(&c);
    for (int i = 0; i < 3; i++) memcpy(&t[i], &c.read[i], 4);
}
static void game_target(float x, float y, float z) { setf(0x1000 + 0x3c, x); setf(0x1000 + 0x40, y); setf(0x1000 + 0x44, z); }
/* one climb from where the body is, after 5 updates the path is not reached (Link standing): the frame's step and whether the
   cap is above 60; returns how far the body rose (the lift is 1.92 m) and, in *in, how far it moved in (the lift's 0.08) */
static float climb(float step, int timed_now, float *in) {
    setup(step, timed_now);
    float t[3];
    for (int i = 0; i < standing; i++) update(0x200000, t);
    const float x0 = getf(body + 0x8c), y0 = getf(body + 0x9c);
    const float dt = step / 60.0f;
    float tm = 0.0f;
    worst_extra = 0.0f;
    changed = stale_grew = 0;
    for (int n = 0; tm < 0.6f; n++, tm += dt) {
        const float bx = getf(body + 0x8c), by = getf(body + 0x9c), bz = getf(body + 0xac);
        const float mx = -(lift(tm + dt, 0.08f) - lift(tm, 0.08f)), my = lift(tm + dt, 1.92f) - lift(tm, 1.92f);
        const int stale = n >= stale_from && n <= stale_to;
        if (!stale) game_target(bx + mx, by + my, bz);
        const float gx = getf(0x1000 + 0x3c), gy = getf(0x1000 + 0x40), gz = getf(0x1000 + 0x44);
        link_runs = !(n >= flat_from && n <= flat_to);
        update(flags, t);
        link_runs = 1;
        if (n == twice_at) {   /* (again in this update: the game sets the same target, no update of Link's between) */
            game_target(gx, gy, gz);
            Ctx c;
            memset(&c, 0, sizeof c);
            c.x[20] = 0x1000;
            c.second = second;
            f_804f5030(&c);
            float a[3];
            for (int i = 0; i < 3; i++) memcpy(&a[i], &c.read[i], 4);
            twice_same = a[0] == t[0] && a[1] == t[1] && a[2] == t[2] && (t[0] != gx || t[1] != gy);   /* (a carry was held) */
        }
        if (stale && (t[0] != gx || t[1] != gy || t[2] != gz)) stale_grew++;
        if (t[0] != gx || t[1] != gy || t[2] != gz) changed++;
        const float move = sqrtf(mx * mx + my * my);
        const float extra = sqrtf((t[0] - bx - mx) * (t[0] - bx - mx) + (t[1] - by - my) * (t[1] - by - my) + (t[2] - bz) * (t[2] - bz));
        if (!stale && move > 1e-6f && extra / move > worst_extra) worst_extra = extra / move;
        const float k = n >= held_from && n <= held_to ? 0.0f : share(step);   /* (the physics: a share of the move) */
        place(bx + k * (t[0] - bx), by + k * (t[1] - by), bz + k * (t[2] - bz));
    }
    if (in) *in = x0 - getf(body + 0x8c);
    return getf(body + 0x9c) - y0;
}
int main(void) {
    char what[200];
    float in, t[3];
    place(-10.5f, 100.0f, 3.8f);
    check(fabsf(climb(1.0f, 0, NULL) - 1.92f) < 0.002f, "a cap of 60: the body follows the lift");
    place(-10.5f, 100.0f, 3.8f);
    held_from = 5, held_to = 9;
    climb(1.0f, 0, NULL);
    check(changed == 0, "a cap of 60, the body held back: the game's targets (nothing carried)");
    place(-10.5f, 100.0f, 3.8f);
    climb(0.5f, 0, NULL);
    check(changed == 0, "a cap of 60 with time slowed (a step of 0.5), the body held back: the game's targets");
    held_from = held_to = -1;
    const float steps[] = {0.5f, 60.0f / 144.0f, 60.0f / 170.0f, 0.25f};
    for (second = 0; second < 2; second++)
        for (int i = 0; i < 4; i++) {
            place(-10.5f, 100.0f, 3.8f);
            const float risen = climb(steps[i], 1, &in);
            snprintf(what, sizeof what, "%.0f fps%s: the body rose %.3f m of the lift's 1.920 and moved in %.4f m of 0.0800",
                     60.0f / steps[i], second ? " (the path's second copy)" : "", risen, in);
            check(fabsf(risen - 1.92f) < 0.0096f && fabsf(in - 0.08f) < 0.001f, what);
        }
    second = 0;
    /* (left as the game has them) */
    const float game120 = 1.92f * share(0.5f);   /* (each target the game's: the body rises the share of the lift) */
    place(-10.5f, 100.0f, 3.8f);
    is_link = 0;
    check(fabsf(climb(0.5f, 1, NULL) - game120) < 0.002f, "not Link's body at 120 fps: the game's targets");
    is_link = 1;
    place(-10.5f, 100.0f, 3.8f);
    flags = 0x200080;
    check(fabsf(climb(0.5f, 1, NULL) - game120) < 0.002f, "on the path but not handing a velocity (flags 0x80) at 120 fps: the game's targets");
    flags = 0x200180;
    place(-10.5f, 100.0f, 3.8f);
    check(fabsf(climb(1.25f, 1, NULL) - 1.92f) < 0.002f, "a frame slower than 60 fps: the body follows");
    place(-10.5f, 100.0f, 3.8f);
    held_from = 5, held_to = 9;
    climb(1.25f, 1, NULL);
    check(changed == 0, "a frame slower than 60 fps, the body held back: the game's targets (nothing carried)");
    held_from = held_to = -1;
    /* (non-finite values: read as the game wrote them, and nothing carried after them) */
    place(-10.5f, 100.0f, 3.8f);
    climb(0.5f, 1, NULL);   /* (a carry held for this body) */
    game_target(NAN, 101.0f, 3.8f);
    update(flags, t);
    check(t[0] != t[0] && t[1] == 101.0f, "a NaN target: read as the game wrote it");
    game_target(INFINITY, 101.0f, 3.8f);
    update(flags, t);
    place(-3.0f, 50.0f, 1.0f);
    game_target(-3.0f, 50.03f, 1.0f);
    update(flags, t);
    check(t[0] == -3.0f && t[1] == 50.03f, "after a NaN and an infinite target: the next target is the game's (nothing carried)");
    place(-10.5f, 100.0f, 3.8f);
    climb(0.5f, 1, NULL);
    setf(body + 0x9c, INFINITY);
    game_target(-10.5f, 101.9f, 3.8f);
    update(flags, t);
    check(t[0] == -10.5f && t[1] == 101.9f && t[2] == 3.8f, "an infinite body position: the game's target");
    /* (between two climbs the path is not reached: the next climb, elsewhere, starts from the game's own target) */
    place(-10.5f, 100.0f, 3.8f);
    climb(0.5f, 1, NULL);
    for (int i = 0; i < 5; i++) update(0x200000, t);
    place(20.0f, 10.0f, -4.0f);
    game_target(20.0f, 10.02f, -4.0f);
    update(flags, t);
    check(t[0] == 20.0f && t[1] == 10.02f && t[2] == -4.0f, "a climb after updates the path was not reached: the game's own target");
    /* (Link's body changes (an area change) between two updates: the new body starts from the game's own target) */
    place(-10.5f, 100.0f, 3.8f);
    climb(0.5f, 1, NULL);
    body = 0x2400;
    setup(0.5f, 1);
    place(5.0f, 30.0f, 2.0f);
    game_target(5.0f, 30.02f, 2.0f);
    update(flags, t);
    check(t[0] == 5.0f && t[1] == 30.02f && t[2] == 2.0f, "Link's body changed: the new body starts from the game's own target");
    body = 0x2000;
    setup(0.5f, 1);
    /* (a target the game does not renew for 6 updates: read as it is, the carry not added again) */
    place(-10.5f, 100.0f, 3.8f);
    stale_from = 20, stale_to = 25;
    climb(0.25f, 1, NULL);
    stale_from = stale_to = -1;
    snprintf(what, sizeof what, "a target not renewed for 6 updates: read as it is (%d of 6 read otherwise)", stale_grew);
    check(stale_grew == 0, what);
    /* (two calls in one update mid-climb, the game renewing the target for both: the second reads what the first did) */
    place(-10.5f, 100.0f, 3.8f);
    twice_at = 30;
    climb(0.5f, 1, NULL);
    twice_at = -1;
    check(twice_same == 1, "a second call in the same update, mid-climb: the same target as the first");
    /* (Link's own update not run before 10 body updates mid-climb: the targets the game renews are still followed, none held back) */
    place(-10.5f, 100.0f, 3.8f);
    flat_from = 20, flat_to = 29;
    {
        const float risen = climb(0.5f, 1, NULL);
        snprintf(what, sizeof what, "Link's update not run before 10 body updates: the body rose %.3f m of the lift's 1.920", risen);
        check(fabsf(risen - 1.92f) < 0.0096f, what);
    }
    flat_from = flat_to = -1;
    /* (one update the path is not reached, then a climb elsewhere: the game's own target) */
    place(-10.5f, 100.0f, 3.8f);
    climb(0.5f, 1, NULL);
    update(0x200000, t);
    place(-30.0f, 60.0f, 9.0f);
    game_target(-30.0f, 60.02f, 9.0f);
    update(flags, t);
    check(t[0] == -30.0f && t[1] == 60.02f && t[2] == 9.0f, "after one update the path was not reached: the game's own target");
    /* (a body the physics holds back for 12 updates: the target read is at most three frames' moves past the game's) */
    place(-10.5f, 100.0f, 3.8f);
    held_from = 20, held_to = 31;
    climb(0.5f, 1, NULL);
    held_from = held_to = -1;
    snprintf(what, sizeof what, "a body held back: the target went %.2f frame moves past the game's (at most 3)", worst_extra);
    check(worst_extra <= 3.001f && worst_extra > 1.5f, what);
    if (!failures) printf("PASS: Link's driven body's target (%d checks)\n", checks);
    return failures != 0;
}
'''


def build_and_run(cc, update, host, directory):
    source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture.exe"
    stubs = "" if host else "static void hos_oot_note_link(uint64_t components) { (void)components; }\n"
    source.write_text(FIXTURE.replace("@HOST@", host + stubs).replace("@UPDATE@", update.replace('#include "a64.h"\n', "")),
                      encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-const-variable",
                    "-Wno-unused-label", "-I", str(ROOT / "host"), str(source), "-o", str(binary), "-lm"], check=True)
    return subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    patched, counts, _ = oot_patches.patch_file(LIFTED, "code_hot_4.c")
    hooked = "hos_oot_drive_target(c->x[20]" in patched
    host = ""
    if hooked:   # (the host's part, as the game links it: cut from the source in the tree)
        text = (ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8")
        host = between(text, "static volatile uint64_t link_body;", "/* The time f_81b3aa48 loads from the cloth's step context")
    with tempfile.TemporaryDirectory(prefix="drive-target-") as directory:
        result = build_and_run(args.cc, patched, host, directory)
        print(result.stdout, end="")
        if result.returncode != 0:
            raise SystemExit("FAIL: Link's driven body's target above 60 fps (the patch %s)" % ("is in" if hooked else "is missing"))
        native = build_and_run(args.cc, LIFTED, "", directory)
        if native.returncode == 0 or "FAIL: 120 fps:" not in native.stdout:
            raise SystemExit("FAIL: the unpatched update did not fail the 120 fps check")
        print("PASS: the unpatched update compiles and fails the 120 fps check (%s)"
              % native.stdout.split("FAIL: 120 fps: ")[1].split("\n")[0])
    # (the game needs Link's update to give his body and count his updates: the fixture calls it itself)
    main_c = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    lift_player = block(main_c, "void hos_oot_lift_player(Ctx *c, uint64_t actor) {")
    call = lift_player.find("\n    hos_oot_note_link(components);\n")   # (a statement of its own, not under a condition)
    if call < 0 or call > lift_player.find("TryAcquireSRWLockExclusive(&cheats_lock)"):
        raise SystemExit("FAIL: host/hos_main.c's hos_oot_lift_player does not call hos_oot_note_link(components) on every update of "
                         "Link's, before the cheats' lock")
    print("PASS: Link's update gives his body and counts his updates, every update (host/hos_main.c)")
    assert counts["driven target"] == 2 and patched.count("hos_oot_drive_target(c->x[20]") == 2
    assert UNRELATED in patched
    again, repeated, _ = oot_patches.patch_file(patched, "code_hot_4.c")
    assert again == patched and repeated["driven target"] == 2
    for altered, found in ((LIFTED.replace("c->x[20] + 240", "c->x[20] + 248", 1), 1),
                           (LIFTED.replace("int64_t _o=60;", "int64_t _o=64;", 1), 1),
                           (LIFTED.replace(READ % 24, (READ % 24) * 2, 1), 1),
                           ('#include "a64.h"\n' + UNRELATED, 0)):
        output, missing, _ = oot_patches.patch_file(altered, "code_hot_4.c")
        assert missing["driven target"] == found, (missing["driven target"], found)
        assert found or output == altered
        warning = io.StringIO()
        with contextlib.redirect_stdout(warning):
            oot_patches.report([Path("code_hot_4.c")], [missing])
        assert "WARNING: the driven body's target was found at %d of 2 places" % found in warning.getvalue()
    print("PASS: scoped, idempotent, and a changed anchor is left alone with a warning")


if __name__ == "__main__":
    main()
