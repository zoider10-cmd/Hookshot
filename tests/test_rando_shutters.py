"""The shutter report (tools/rando/rando_shutters.py) on made-up actors: no game data, no zstandard.

A chest near a shutter that turns saving and the warp songs off is marked when a switch beside the shutter takes an
item the chest's rule does not ask for, and only then.

    python -I -B tests/test_rando_shutters.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "rando"))
import rando_shutters as sh
import rando_seed as seed


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def actor(gyaml, h, at, **dyn):
    return {"Gyaml": gyaml, "Hash": h, "Translate": list(at), "Dynamic": dyn}


def main():
    shutter = actor("Obj_ForestTemple_SwitchShutter_A_03", 1, (0.0, 0.0, 0.0), IsDisableSaveAndWarp=True, DefaultDungeonRoomIndex=16)
    eye = actor("Obj_EyeSwitch_A_02", 2, (5.0, 0.0, 0.0))
    bow = actor("Obj_TBox_A_02_NoBake", 3, (0.0, 0.0, 17.0), Drop__DropActor="Item_Range_Bow", GetEventName="ForestTemple_GetBow")
    plain = actor("Obj_TBox_A_01", 4, (0.0, 0.0, 10.0), Drop__DropActor="TBox_Rupee_Red")
    far = actor("Obj_TBox_A_01", 5, (0.0, 0.0, 99.0), Drop__DropActor="TBox_Rupee_Red", GetEventName="ForestTemple_GetBow")
    open_shutter = actor("Obj_ForestTemple_SwitchShutter_A_03", 6, (1.0, 0.0, 0.0))

    # the Stalfos room: the Bow chest's rule (ADULT) does not ask for the Bow its eye switch takes
    out, shutters, marks = sh.report({"ForestTemple": [shutter, eye, bow, plain, far, open_shutter]}, 30.0, fixed={1})
    text = "\n".join(out)
    check(shutters == 1, "one shutter turns the warp songs off (%d)" % shutters)
    check(marks == 1, "the Bow's chest is marked, the plain chest (its rule asks for the Bow) and the far one are not (%d)" % marks)
    check(text.count("LOOK") == 1 and "Item_Range_Bow  [event: ForestTemple_GetBow]   <-- LOOK" in text, "the mark is on the Bow's chest:\n" + text)
    check("the seed's mod turns this one off" in text, "a shutter of FIXES says so")
    check("99.0" not in text, "a chest past the radius is not listed")

    # a step switch takes nothing: no mark
    step = actor("Obj_StepSwitch_A_01", 7, (5.0, 0.0, 0.0))
    _, _, marks = sh.report({"ForestTemple": [shutter, step, bow]}, 30.0)
    check(marks == 0, "a switch anything presses marks nothing")

    # a hammer switch beside a chest whose rule has the Hammer: no mark; beside the Hammer's own chest: a mark
    fire = actor("Obj_FireTemple_SwitchShutter_A_01", 8, (0.0, 0.0, 0.0), IsDisableSaveAndWarp=True)
    rusted = actor("Obj_HammerSwitch_A_01", 9, (6.0, 0.0, 0.0))
    key = actor("Obj_TBox_A_03", 10, (0.0, 0.0, 13.0), Drop__DropActor="Item_Dungeon_BossKey")
    ham = actor("Obj_TBox_A_02", 11, (0.0, 0.0, 14.0), Drop__DropActor="Item_Hammer", GetEventName="FireTemple_GetHammer")
    _, _, marks = sh.report({"FireTemple": [fire, rusted, key]}, 30.0)
    check(marks == 0, "the Fire Temple's chests ask for the Hammer")
    _, _, marks = sh.report({"FireTemple": [fire, rusted, key, ham]}, 30.0)
    check(marks == 1, "the Hammer's own chest does not")
    check(sh.takes("Obj_SolarSwitch_A_02") == (seed.MS,) and sh.takes("Obj_SwitchHit_A_02") == (), "what a switch takes, by its name")
    print("ok: the shutter report")


if __name__ == "__main__":
    main()
