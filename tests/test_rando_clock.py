"""The world's clock runs day and night with the randomizer (bugs 58 and 81, nx2/oot_patches.py patch_clock_cap): no game data.

f_803edf70 hands the clock a target time unless the scene of Zelda's escape (Dm_HrlField_0020) has played: 15:00 before
it. Bug 58's fix answered "free" by going to L_803ee644, which hands a target of 0: midnight, where the clock then stood
(bug 81, the owner's run 2026-11-18; seen without a window: 86026 s, then 0 for good). The host's answer now goes to
L_803ee2c8, where the game itself goes once the scene has played: the clock plus the step, no target.
- the patch on a copy of the function's text: the line after the flag's test goes to L_803ee2c8; a file patched by the
  first fix loses its old line; a second run changes nothing; a file without the label or the anchor is left alone.

    python -I -B tests/test_rando_clock.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    sys.path.insert(0, str(ROOT / "nx2"))
    import oot_patches as P   # noqa: E402
    body = ('#include "a64.h"\nvoid f_803edf70(Ctx *__restrict A64_NOESC c) {\nL_803ee2c8:;\n    c->x[8]=1;\n' + P.CLOCK_CAP +
            "    c->x[2] = 0xd2f0ULL;\nL_803ee644:;\n}\n")
    out = P.patch_clock_cap(body)
    check(out is not None and "{ goto L_803ee2c8; }" in out and P.CLOCK_CAP + P.CLOCK_FREE in out,
          "the host's answer does not go to the free-running clock (L_803ee2c8) after the flag's test")
    check("hos_oot_field_clock_free()) { goto L_803ee644; }" not in out, "the answer still goes to the midnight target")
    check(P.patch_clock_cap(out) == out, "a second run changed the file")
    old = body.replace(P.CLOCK_CAP, P.CLOCK_CAP + P.CLOCK_FREE_WAS)
    again = P.patch_clock_cap(old)
    check(again is not None and P.CLOCK_FREE_WAS not in again and again.count(P.CLOCK_FREE) == 1,
          "a file patched by the first fix keeps its old line")
    check(P.patch_clock_cap(body.replace("L_803ee2c8:;\n", "")) is None, "a file without the free-running label was patched")
    check(P.patch_clock_cap('#include "a64.h"\n') is None, "a file without the clock was patched")
    print("PASS: the clock runs day and night")


if __name__ == "__main__":
    main()
