"""The Door of Time by the Song of Time (rando_open_door 2, tools/rando/rando_seed.py DOOR_SONG; host/hos_main.c
oot_time_door and hos_oot_shelf_actor; asked for 2026-11-16): no game data.

- the setting's third choice is read apart from On, and on the stamp's first line;
- the map keeps its door and moves Sheik alone (door_away with door False), and the adult gets the sword's prompt;
- with the songs shuffled the places only an adult has ask for the Song of Time in place of what it takes to be one;
- the game's side opens the door once Link holds the Song of Time and an ocarina (read as the Debug tab reads them),
  by answering the door's name with the temple's own invisible effect marker, and only then does Open Door of Time's
  work (seen without a window 2026-11-19: through the doorway with the song, stopped at the door without it).

    python -I -B tests/test_rando_door_song.py
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


def actor(name, x, y, z, links=()):
    row = collections.OrderedDict([("Gyaml", ("string", name)), ("Hash", (0xD5, struct.pack("<Q", hash(name) & 0xffffffffffff))),
                                   ("Translate", ("array", [(0xD2, struct.pack("<f", v)) for v in (x, y, z)]))])
    if links:
        row["Links"] = ("array", [("dict", collections.OrderedDict([("Dst", (0xD5, struct.pack("<Q", h)))])) for h in links])
    return ("dict", row)


def main():
    S = seed
    tree = ("dict", collections.OrderedDict([("Actors", ("array", [actor(S.DOOR_ACTOR, 118.4, 104.9, -34.0), actor(S.DOOR_SHEIK, 137.0, 104.9, -34.0)]))]))
    data = S.byml_build(tree, 7)
    new, doors, sheiks = S.door_away(data, door=False)
    got, _ = S.byml_parse(new)
    places = {a[1]["Gyaml"][1]: [struct.unpack("<f", v[1])[0] for v in a[1]["Translate"][1]] for a in got[1]["Actors"][1]}
    check(doors == 0 and sheiks == 1 and abs(places[S.DOOR_ACTOR][1] - 104.9) < 0.01 and abs(places[S.DOOR_SHEIK][2] - (-34.0 + S.DOOR_SHEIK_ASIDE)) < 0.01,
          "the door's map does not keep its door and move Sheik alone: %r" % places)
    _, doors, _ = S.door_away(data)
    check(doors == 1, "Open Door of Time no longer takes the door out of the map")
    need = S.ADULT | {S.BOW}
    check(S.door_need(need, True, song=True) == S.door_need(need, True) | {S._TIME} and S._TIME not in S.door_need(need, True),
          "an adult's place does not ask for the Song of Time with the door by the song")
    check(S.door_need(S.CHILD, False, song=True) == S.CHILD, "a child's place asks for the Song of Time")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('a.door_song = not a.open_door and ini["rando_open_door"] == 2' in script and 'a.open_door = a.open_door or ini["rando_open_door"] == 1' in script and
          '(" door song 1" if a.door_song else "")' in script and "door_rules = a.open_door or (a.door_song and _TIME in PROGRESSION)" in script and
          "new, count, aside = door_away(data, door=a.open_door)" in script and "if a.open_door or a.door_song:   # (the adult's \"A\" at the sword" in script,
          "the setting is not read apart from On, not on the stamp, or the rules, the map and the sword's prompt do not follow it")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check('#define OOT_DOOR_STAND_IN "EftLoc_TimeTemple_Fog_HideOutside_00"' in host and
          'oot_item_count(c, "Item_Melody_TimeSong") > 0' in host and 'oot_item_count(c, "Item_Ocarina_Fairy") > 0 || oot_item_count(c, "Item_Ocarina_Time") > 0' in host and
          "__atomic_load_n(&oot_door_song_open, __ATOMIC_ACQUIRE) ? OOT_DOOR_STAND_IN : NULL" in host and
          "if (!__atomic_load_n(&oot_door_song_open, __ATOMIC_RELAXED)) return;" in host and "if (open != __atomic_load_n(&oot_door_song_open, __ATOMIC_RELAXED)) {" in host,
          "the game's side does not open the door by the song, or does Open Door of Time's work before it")
    rando_c = (ROOT / "host" / "oot_rando.c").read_text(encoding="utf-8")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    check("return rando_active ? (test ? test : rando.v[OOT_RANDO_OPEN_DOOR]) : 0;" in rando_c and
          '"Off", "On", "With the Song of Time")' in header, "the setting's third choice is not the game's side's")
    print("PASS: the Door of Time by the Song of Time")


if __name__ == "__main__":
    main()
