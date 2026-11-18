"""The mouse as the right stick (host/nn_hid.c's mouse_stick) swaps left and right with the menu's Invert mouse horizontal
(option 61, or HOS_MOUSE_INVERT_X=1), as it swaps up and down with its Invert mouse vertical (option 8).

mouse_stick and what it calls (the panning's move and tick, the set-up) are cut out of the source and compiled with
stand-ins for the mouse, the clock and the menu's options. A movement to the right pushes the stick right (x > 0) and one
toward the player pushes it down (y < 0: the stick's y points up). Each row turns its own direction around and leaves the
other, while the mouse pans the camera and while it points (L held: the ability wheel), where the vertical row already
applied. It is the path the mouse takes with Mouse camera As the stick, and with Native whenever the game takes the right
stick for its own use (a lock-on, the bow's aim, a menu).
python -I -B tests/test_mouse_stick.py [--cc clang]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import between, block  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# (env_on, the switches' rule, before the code cut out of the source: gpu/vk/compat/hookshot_env.h)
ENV_ON_H = str(ROOT / "gpu" / "vk" / "compat" / "hookshot_env.h")

BEFORE = r"""
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
double hos_mouse_sens;
const char *hos_user_dir = "no-such-folder";   /* (no mouse_sens.txt there: the sensitivity stays 1) */
static int sens_from_file;
static int64_t clock_ns = 1000000000LL;
static int64_t hos_now_ns(void) { return clock_ns; }
static int32_t move_x, move_y;
static int captured = 1, menu_invert, menu_invert_x;
static int rx_option(int id, int otherwise) { return id == 8 ? menu_invert : id == 61 ? menu_invert_x : otherwise; }
static int hos_mouse_take(int32_t *dx, int32_t *dy) { *dx = move_x, *dy = move_y; move_x = move_y = 0; return captured; }
static void mouse_sens_keys(void) {}
"""

AFTER = r"""
static int fails;
static int32_t rx, ry;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s (stick %d %d)\n", __LINE__, #c, (int)rx, (int)ry); fails++; } } while (0)
/* one movement of the captured mouse, read 10 ms after the last read; the deflection held from the read before is let go
   first (a read while the mouse is not captured centres the stick) */
static void moved(int32_t dx, int32_t dy, int pointing) {
    captured = 0;
    clock_ns += MOUSE_TICK_NS;
    mouse_stick(&rx, &ry, pointing);
    captured = 1;
    move_x = dx, move_y = dy;
    clock_ns += MOUSE_TICK_NS;
    rx = ry = 0;
    if (!mouse_stick(&rx, &ry, pointing)) printf("FAIL: the captured mouse gave no stick\n"), fails++;
}
int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "env")) {   /* HOS_MOUSE_INVERT_X=1, the menu's row off */
        moved(100, 0, 0);
        CHECK(rx < 0 && ry == 0);
        moved(0, 100, 0);
        CHECK(rx == 0 && ry < 0);
        if (!fails) printf("PASS\n");
        return fails != 0;
    }
    for (int pointing = 0; pointing <= 1; pointing++) {
        menu_invert = menu_invert_x = 0;
        moved(100, 0, pointing);
        CHECK(rx > 0 && ry == 0);   /* right: the stick goes right */
        moved(0, 100, pointing);
        CHECK(rx == 0 && ry < 0);   /* toward the player: the stick goes down */
        menu_invert = 1;   /* the menu's Invert mouse vertical: up and down only */
        moved(100, 0, pointing);
        CHECK(rx > 0 && ry == 0);
        moved(0, 100, pointing);
        CHECK(rx == 0 && ry > 0);
        menu_invert = 0, menu_invert_x = 1;   /* the menu's Invert mouse horizontal: left and right only */
        moved(100, 0, pointing);
        CHECK(rx < 0 && ry == 0);
        moved(-100, 0, pointing);
        CHECK(rx > 0 && ry == 0);
        moved(0, 100, pointing);
        CHECK(rx == 0 && ry < 0);
        menu_invert = 1;   /* both rows */
        moved(100, 100, pointing);
        CHECK(rx < 0 && ry > 0);
    }
    if (!fails) printf("PASS\n");
    return fails != 0;
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    cut = "\n".join((
        between(hid, "enum { MOUSE_TICK_NS", "/* (host/oot_menu.c) A drag"),   # the panning: its move and its tick
        between(hid, "static int invert = -1;", "static void mouse_setup(void)"),
        block(hid, "static void mouse_setup(void)"),
        block(hid, "static int mouse_stick("),
    ))
    with tempfile.TemporaryDirectory(prefix="hookshot-mouse-stick-") as tmp:
        tmp = Path(tmp)
        (tmp / "t.c").write_text(BEFORE + cut + AFTER, encoding="utf-8")
        binary = tmp / "t.exe"
        build = subprocess.run([args.cc, "-std=gnu11", "-include", ENV_ON_H, "-Wall", "-O1", "-g", str(tmp / "t.c"),
                                "-o", str(binary), "-lm"], text=True, capture_output=True)
        if build.returncode:
            raise SystemExit("the cut of host/nn_hid.c does not compile:\n" + build.stderr)
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_MOUSE_")}
        # (the switch is read once a run: its own process)
        for name, argv, run_env in (("the menu's rows", [], env), ("HOS_MOUSE_INVERT_X=1", ["env"], dict(env, HOS_MOUSE_INVERT_X="1"))):
            run = subprocess.run([str(binary)] + argv, text=True, capture_output=True, timeout=30, env=run_env)
            if run.returncode:
                raise SystemExit("%s: %s" % (name, (run.stdout + run.stderr).strip()))
    print("PASS: each mouse inversion turns its own direction of the stick around")


if __name__ == "__main__":
    main()
