"""The R item wheel opens with one item (bug 57, nx2/oot_patches.py patch_wheel_fewest, host/hos_main.c
hos_oot_wheel_fewest): no game data.

The game's SeqQueryIsOpenableShortCut (f_8331efa0) opens the wheel only when its manager counts more than 1 item; a
shuffle can leave a child one. The patch makes the 1 the host's answer: 0 with the randomizer on, 1 otherwise or with
HOS_OOT_WHEEL_TWO=1.
- the patch on a copy of the function's text: the comparison changed once, the host's function declared, a second run
  changes nothing, and a file without the function or with another comparison is left alone (None);
- the patch is applied by patch_file and counted, so a build where the function moved warns;
- the host's answer, by its text.

    python -I -B tests/test_rando_item_wheel.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


SOURCE = ('#include "a64.h"\n'
          "void f_8331efa0(Ctx *__restrict A64_NOESC c) {\n"
          "    c->x[8]=recomp_load64(c,c->x[21] + 0);\n"
          "    c->x[8]=recomp_load32(c,c->x[8] + 1176);\n"
          "    { uint64_t _a=c->x[8], _b=1ULL; uint64_t _r=_a-_b; _r&=0xFFFFFFFFULL; }\n"
          "}\n"
          "void f_8331f050(Ctx *__restrict A64_NOESC c) {\n"
          "    c->x[8]=recomp_load32(c,c->x[8] + 1176);\n"
          "    { uint64_t _a=c->x[8], _b=1ULL; uint64_t _r=_a-_b; _r&=0xFFFFFFFFULL; }\n"
          "}\n")


def main():
    sys.path.insert(0, str(ROOT / "nx2"))
    import oot_patches as P   # noqa: E402
    out = P.patch_wheel_fewest(SOURCE)
    check(out is not None, "the wheel's function was not found")
    head = out[:out.index("void f_8331f050")]
    check("_b=(uint64_t)hos_oot_wheel_fewest();" in head and "_b=1ULL" not in head, "the wheel's count is not the host's")
    check(out[out.index("void f_8331f050"):].count("_b=1ULL") == 1, "another function's comparison was changed")
    check("extern int hos_oot_wheel_fewest(void);\n" in out, "the host's function is not declared")
    check(P.patch_wheel_fewest(out) == out, "a second run changed the file again")
    check(P.patch_wheel_fewest(SOURCE.replace("void f_8331efa0", "void f_8331efa4")) is None, "a file without the function was patched")
    check(P.patch_wheel_fewest(SOURCE.replace("+ 1176);\n    { uint64_t _a=c->x[8], _b=1ULL", "+ 1180);\n    { uint64_t _a=c->x[8], _b=1ULL", 1)) is None,
          "a function whose comparison is not the item count was patched")
    src = (ROOT / "nx2" / "oot_patches.py").read_text(encoding="utf-8")
    check('wheel = patch_wheel_fewest(out) if protect_hearts else None' in src and 'counts["item wheel count"] += 1' in src and
          'done["item wheel count"] = 0' in src, "the patch is not applied, counted and warned of")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    fn = host[host.index("int hos_oot_wheel_fewest(void) {"):]
    fn = fn[:fn.index("\n}\n")]
    check('getenv("HOS_OOT_WHEEL_TWO")' in fn and "return keep || !hos_rando_on() ? 1 : 0;" in fn,
          "the host does not answer 0 with the randomizer on and 1 otherwise")
    print("PASS: the R item wheel opens with one item")


if __name__ == "__main__":
    main()
