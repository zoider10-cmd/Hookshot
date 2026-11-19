"""How some items stand on shop shelves (bugs 53 and 63, tools/rando/rando_seed.py): no game data.

- bug 53: the empty bottle lay on its side, its mouth to the viewer; a quarter turn about X the other way stands it up,
  cork up (seen without a window on the Kokiri shop's eight shelves, 2026-11-18);
- bug 63: Kakariko's Potion Shop's shelves face otherwise than the other shops': there the Fairy Slingshot and the Deku
  Stick bundle have turns of their own (SHELF_TURN_SHOP), and the stick its own size and height (SHELF_FIT_SHOP), while
  every other shop keeps SHELF_TURN's and shelf_fit's;
- shelf_shop reads the shop from a shelf actor's name, a tier's too (Shop_Rando_<shop>_<place>_<tier>);
- the shop's numbers are used where the turns and fits are chosen; FIXES_VERSION moved on.

    python -I -B tests/test_rando_shelf_poses.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, why):
    if not ok:
        print("FAIL: %s" % why)
        sys.exit(1)


def main():
    sys.path.insert(0, str(ROOT / "tools" / "rando"))
    import rando_seed as R   # noqa: E402
    check(R.SHELF_TURN["Item_Bottle"] == (-1.57, 0.0, 0.0), "the bottle is not stood up (bug 53)")
    check(R.shelf_shop("Shop_Rando_kmedicine_3") == "kmedicine" and R.shelf_shop("Shop_Rando_kmedicine_3_1") == "kmedicine"
          and R.shelf_shop("Shop_Rando_kokiri_0") == "kokiri" and R.shelf_shop("Npc_Hylia_020_Shop") == "",
          "a shelf actor's shop is not read from its name")
    check(R.shelf_turn("Shop_Rando_kmedicine_2", "Item_Range_SlingShot") == (0.0, 3.14, 1.57),
          "the slingshot has not its own turn in Kakariko's Potion Shop")
    check(R.shelf_turn("Shop_Rando_kmedicine_0", "Item_DekuStickBundle_Small") == (1.57, 0.0, 0.0),
          "the stick bundle does not stand in Kakariko's Potion Shop")
    check(R.shelf_turn("Shop_Rando_kokiri_0", "Item_Range_SlingShot") == R.SHELF_TURN["Item_Range_SlingShot"] and
          R.shelf_turn("Shop_Rando_general_1", "Item_DekuStickBundle_Small") is None,
          "another shop's turns changed with the Potion Shop's")
    check(R.shelf_turn("Shop_Rando_kmedicine_1", "Item_Bottle") == R.SHELF_TURN["Item_Bottle"],
          "an item the Potion Shop has no turn for does not keep SHELF_TURN's there")
    lift, size = R.SHELF_FIT_SHOP["kmedicine"]["Item_DekuStickBundle_Small"]
    check(0 < size < 0.6 and 0 < lift < 0.5, "the stick bundle's size or height in the Potion Shop is not set")
    src = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("SHELF_FIT_SHOP.get(shelf_shop(actor), {}).get(item) or shelf_fit(item, model_box(table, SHELF_MODEL_AS.get(item, item)))" in src and
          "turns = {actor: shelf_turn(actor, item) for actor, (item, _) in on_sale.items() if shelf_turn(actor, item)}" in src,
          "the shop's own turns and fits are not used where the shelves are made")
    check(R.FIXES_VERSION >= 45, "FIXES_VERSION did not move on: a seed made before keeps the old poses")
    # (bug 72: a boss's Heart Container on a shelf is made a Piece of Heart's size)
    check(R.SHELF_SCALE.get(R.CONTAINER) == 0.55 and R.FIXES_VERSION >= 46, "a Heart Container on a shelf is not made smaller")
    # (bugs 54, 56: the item held up in "You got" is shown by the Item_ spelling, the Armor_ one being a worn piece)
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    fn = host[host.index("void hos_oot_get_name(Ctx *c, uint64_t node, int kind) {"):]
    fn = fn[:fn.index("\n}\n")]
    check("if (kind == 1) {" in fn and "if (!strcmp(shown, oot_show_as[i][1])) {" in fn and
          "give = oot_show_as[i][0];" in fn, "a held-up gauntlet is still shown by its worn piece's spelling")
    # (bug 55: the Silver and Golden Gauntlets show the bracelet's model on a shelf, their own name)
    check("SHELF_MODEL_AS = {\"Item_Gauntlet_Silver\": \"Item_Gauntlet_Goron\", \"Item_Gauntlet_Gold\": \"Item_Gauntlet_Goron\"," in src and
          '"TBox_Shield_Deku": "Shop_Weapon_Shield_Deku", "TBox_Shield_Hylian": "Shop_Weapon_Shield_Hylian"}' in src and
          'SHELF_POSE_AS = frozenset(("TBox_Shield_Deku", "TBox_Shield_Hylian"))' in src and
          "    if item in SHELF_POSE_AS:   # (the game's own shelf's model and pose: no turn of ours, bug 77)" in src and
          'SHELF_MODEL_FIELDS = ("FmdbName", "ModelProjectName", "ModelAabbMin", "ModelAabbMax", "AnimationResources")' in src and
          "row[1].update((k, v) for k, v in by[SHELF_MODEL_AS[item]][1].items() if k in SHELF_MODEL_FIELDS)" in src and
          "pack(SHELF_MODEL_AS[item]) if item in SHELF_MODEL_AS else None)" in src,
          "the gauntlets' shelves do not show the bracelet's model with their own name (bug 55)")
    print("PASS: the bottle and Kakariko's Potion Shop's shelves")


if __name__ == "__main__":
    main()
