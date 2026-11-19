"""A shield's pick-up has a model file of its own (bug 78, tools/rando/rando_seed.py own_model_pack): no game data.

The owner's run 2026-11-18: after the Deku Shield was bought, Link's shield lost the cosmetics' look until a restart. The
seed's pick-up pack of TBox_Shield_Deku (a Skulltula may drop it) carried the game's own copy of
Component/ModelInfo/Weapon_Shield_Deku, opened at the session's start, and the game keeps the first copy of a file it
loads. Checked on a small pack made here:
- a pick-up whose actor names a shield's model file (SHELF_OWN_MODEL): the file renamed the actor's own, the actor names
  it, the shared name gone from the pack, the other files as they were;
- a pick-up naming another model, or none, is the pack as it was;
- the seed makes every pick-up's pack through it.

    python -I -B tests/test_rando_shield_model.py
"""
import collections
import importlib.util
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


def pack(item, model):
    comps = collections.OrderedDict()
    if model:
        comps["ModelInfoRef"] = ("string", "?" + seed.MODEL_INFO_FILE % model)
    actor = ("dict", collections.OrderedDict((("$parent", ("string", seed.ACTOR_REF % seed.PICKUP_BASE)),
                                               ("Components", ("dict", comps)))))
    files = {seed.ACTOR_FILE % item: seed.byml_build(actor, 7), "Other/file.bin": b"other"}
    if model:
        files[seed.MODEL_INFO_FILE % model] = b"the model's info"
    return seed.sarc_write(files)


def model_of(data, item):
    tree, _ = seed.byml_parse(seed.sarc_read(data)[seed.ACTOR_FILE % item])
    ref = tree[1]["Components"][1].get("ModelInfoRef")
    return ref[1] if ref else None


def main():
    S = seed
    was = pack("TBox_Shield_Deku", "Weapon_Shield_Deku")
    now = S.own_model_pack("TBox_Shield_Deku", was)
    files = S.sarc_read(now)
    own = S.MODEL_INFO_FILE % "TBox_Shield_Deku"
    check(own in files and S.MODEL_INFO_FILE % "Weapon_Shield_Deku" not in files and files[own] == b"the model's info",
          "the shield's model file is not renamed the pick-up's own")
    check(model_of(now, "TBox_Shield_Deku") == "?" + own, "the pick-up's actor does not name its own model file")
    check(files["Other/file.bin"] == b"other", "another file of the pack changed")
    for item, model in (("TBox_Shield_Hylian", "Obj_Shield_Hylian"), ("Item_Boomerang", "Item_Boomerang"), ("Item_Bottle", None)):
        p = pack(item, model)
        check(S.own_model_pack(item, p) == p, "%s's pack changed: it names no shield's model file" % item)
    check(S.own_model_pack("TBox_Shield_Deku", pack("Item_Boomerang", "Item_Boomerang")) is not None, "a pack without the actor stops the seed")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("new = own_model_pack(item, pickup_pack(item, old, base, each_time=item not in PROGRESSION))" in script,
          "the seed's pick-ups are not made through own_model_pack")
    print("PASS: a shield's pick-up has a model file of its own")


if __name__ == "__main__":
    main()
