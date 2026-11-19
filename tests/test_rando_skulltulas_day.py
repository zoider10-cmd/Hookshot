"""The randomizer's Gold Skulltulas by day setting (tools/rando/rando_seed.py NOCTURNAL): no game data.

- a map file: each Gold Skulltula's Enemy_Skulltula_Gold_Nocturnal true is made false in place (the size kept), the
  others' and every other actor's entries are left; a file without night-only ones is not changed;
- the script reads the setting, names it in the seed's stamp and writes the files before the size table; the
  launcher and the game's settings have its row, appended.

    python -I -B tests/test_rando_skulltulas_day.py
"""
import collections
import importlib.util
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def actor(h, gyaml, night=None, other=None):
    a = collections.OrderedDict()
    dyn = collections.OrderedDict()
    if night is not None:
        dyn[seed.NOCTURNAL] = (0xD0, struct.pack("<I", int(night)))
    if other is not None:
        dyn["Other_Flag"] = (0xD0, struct.pack("<I", int(other)))
    if dyn:
        a["Dynamic"] = ("dict", dyn)
    a["Gyaml"] = ("string", gyaml)
    a["Hash"] = (0xD5, struct.pack("<Q", h))
    return ("dict", a)


def nights(data):
    return [w.get(seed.NOCTURNAL) for _, g, _, _, w in seed.marks(data) if g == seed.SKULLTULA]


def main():
    S = seed
    data = S.byml_build(("dict", collections.OrderedDict((("Actors", ("array", [
        actor(1, S.SKULLTULA, night=True, other=True), actor(2, S.SKULLTULA), actor(3, S.SKULLTULA, night=True),
        actor(4, "Obj_TBox_A_01", other=True)])),))), 7)
    new, count = S.skulltulas_by_day(data)
    check(count == 2 and new is not None and len(new) == len(data), "the night-only Skulltulas are not both made day ones in place")
    check(nights(new) == [0, None, 0] and nights(data) == [1, None, 1], "a Skulltula's flag is not made false, or another's is set")
    changed = [i for i in range(len(data)) if data[i] != new[i]]
    check(len(changed) == 2, "more than the two flags changed: %r" % changed)
    plain = S.byml_build(("dict", collections.OrderedDict((("Actors", ("array", [actor(2, S.SKULLTULA)])),))), 7)
    check(S.skulltulas_by_day(plain) == (None, 0), "a file without night-only Skulltulas is changed")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('a.skulltulas_day = a.skulltulas_day or ini["rando_skulltulas_day"] != 0' in script and
          '(" skulltulas by day" if a.skulltulas_day else "")' in script and '"rando_skulltulas_day": 0' in script,
          "the script does not read the setting, or does not name it in the seed's stamp")
    check(script.index("new, count = skulltulas_by_day(data)") < script.index("# ---- the size table ----") and
          script.index("new, count = skulltulas_by_day(data)") < script.index("for rel, held in list(tier_maps.items()):"),
          "the files are changed after the size table or the shelves' tier maps are made from them")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    rows = header[header.index("#define OOT_RANDO_SETTINGS(X)"):header.index("enum {")]
    check(rows.index("X(RUPEE_FILL,") < rows.index("X(SKULLTULAS_DAY,"), "the setting is not appended after the others")
    print("PASS: Gold Skulltulas by day")


if __name__ == "__main__":
    main()
