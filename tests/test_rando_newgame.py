"""A new game's changes (tools/rando/rando_seed.py) on made-up files: no game data, no zstandard.

Open Deku Tree and Open forest exit make two flags of the game's list of flags start put out: the list is a big-endian
BYML, and only those flags' starting values change. Skip opening passes over the two cutscenes of the opening's event
flow: two numbers of the file change, and a flow that is not the one it was written for is refused.

    python -I -B tests/test_rando_newgame.py
"""
import collections
import importlib.util
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def flag_list(root):
    """a big-endian BYML document of dictionaries, lists, truth values and numbers (the game's list of flags is one)"""
    keys = set()

    def walk(v):
        if isinstance(v, dict):
            keys.update(v)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(root)
    keys = sorted(keys)
    out = bytearray(16)

    def emit(v):
        """(type, the 4 bytes of its value)"""
        if isinstance(v, bool):
            return 0xD0, struct.pack(">I", int(v))
        if isinstance(v, int):
            return (0xD3, struct.pack(">I", v)) if v >= 0x80000000 else (0xD1, struct.pack(">i", v))
        if isinstance(v, dict):
            parts = [(keys.index(k), emit(x)) for k, x in sorted(v.items())]
            at = len(out)
            out.extend(bytes([0xC1]) + len(parts).to_bytes(3, "big"))
            for key, (kind, value) in parts:
                out.extend(key.to_bytes(3, "big") + bytes([kind]) + value)
            return 0xC1, struct.pack(">I", at)
        parts = [emit(x) for x in v]
        at = len(out)
        out.extend(bytes([0xC0]) + len(parts).to_bytes(3, "big") + bytes(k for k, _ in parts))
        out.extend(b"\0" * (-len(out) % 4))
        for _, value in parts:
            out.extend(value)
        return 0xC0, struct.pack(">I", at)

    _, where = emit(root)
    key_at = len(out)
    head = 4 + 4 * (len(keys) + 1)
    offsets, blob = [], bytearray()
    for k in keys:
        offsets.append(head + len(blob))
        blob += k.encode() + b"\0"
    offsets.append(head + len(blob))
    out.extend(bytes([0xC2]) + len(keys).to_bytes(3, "big") + b"".join(struct.pack(">I", o) for o in offsets) + blob)
    out.extend(b"\0" * (-len(out) % 4))
    out[0:16] = b"BY" + struct.pack(">HII", 7, key_at, 0) + where
    return bytes(out)


def flags():
    check(seed.murmur3(b"") == 0 and seed.murmur3(b"abc") == 0xB3DD93FA and seed.murmur3(b"Hello, world!") == 0xC0363E43,
          "MurmurHash3 of known texts")
    mido, kokiri = (name for names in seed.OPEN.values() for name in names)
    check(set(seed.OPEN) == {"deku", "forest"} and all(v is False for names in seed.OPEN.values() for v in names.values()),
          "the two ways of the forest, each a flag that starts put out")
    other = "Some_Other_Flag"
    h = lambda name: seed.murmur3(name.encode())
    rows = [{"DefaultValue": True, "Hash": h(mido), "ResetTypeValue": 8, "SaveFileIndex": 0},
            {"DefaultValue": True, "Hash": h(other), "ResetTypeValue": 8, "SaveFileIndex": 0},
            {"DefaultValue": True, "Hash": h(kokiri), "ResetTypeValue": 8, "SaveFileIndex": 0},
            {"DefaultValue": False, "Hash": 7, "ResetTypeValue": 0, "SaveFileIndex": -1}]
    data = flag_list({"Data": {"Bool": rows, "Int": [{"DefaultValue": 5, "Hash": h(mido)}]}, "MetaData": {"FormatVersion": 1}})
    new = seed.flag_defaults(data, {mido: False})
    check(new is not None and len(new) == len(data), "the list keeps its size")
    diff = [i for i in range(len(data)) if data[i] != new[i]]
    check(len(diff) == 1 and data[diff[0]] == 1 and new[diff[0]] == 0, "one flag's starting value changed, and nothing else (%r)" % diff)
    check(seed.flag_defaults(new, {mido: False}) is None, "a list that already starts so is left")
    both = seed.flag_defaults(data, {mido: False, kokiri: False})
    check(sum(a != b for a, b in zip(data, both)) == 2 and seed.flag_defaults(both, {other: True}) is None, "both ways' flags, and the others as they were")
    check(seed.flag_defaults(both, {mido: True, kokiri: True}) == data, "set again, the list is the game's own")
    # ---- starting rupees: a whole number of the list (Data.Int), as the flags are truth values ----
    check(seed.RUPEES == "PlayerStatus.CurrentRupee" and seed.START_RUPEES == 200, "the rupees a new game starts with are not 200 of Link's own")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_start_rupees": 0' in script and 'flag_defaults(new if new is not None else was, {RUPEES: START_RUPEES}, kind="Int")' in script and
          '(" rupees %d" % START_RUPEES if a.start_rupees else "")' in script,
          "the script does not read the setting, give the rupees after the flags in the same file, or name them in the seed's stamp")
    rich = seed.flag_defaults(data, {mido: 200}, kind="Int")   # (the made-up list's one whole number has that name's hash, and starts at 5)
    check(rich is not None and len(rich) == len(data) and sum(x != y for x, y in zip(data, rich)) == 1 and
          seed.flag_defaults(rich, {mido: 200}, kind="Int") is None and seed.flag_defaults(rich, {mido: 5}, kind="Int") == data,
          "a whole number of the list is not set to the number given, alone, in place")
    check(seed.flag_defaults(rich, {mido: False}) is not None and seed.flag_defaults(seed.flag_defaults(rich, {mido: False}), {mido: 200}, kind="Int") is None,
          "the flags set after the rupees undo them")
    for bad in ({seed.RUPEES: -1}, {seed.RUPEES: True}, {seed.RUPEES: 1.5}, {seed.RUPEES: 1 << 31}):
        try:
            seed.flag_defaults(data, bad, kind="Int")
            check(False, "a number the list cannot hold is taken: %r" % bad)
        except ValueError:
            pass
    for bad, why in (({"No_Such_Flag": False}, "a flag the list does not have"), ({mido: False, "No_Such_Flag": False}, "one of two")):
        try:
            seed.flag_defaults(data, bad)
            check(False, "%s is passed over" % why)
        except ValueError as e:
            check("No_Such_Flag" in str(e), "the error names the missing flag")
    try:
        seed.flag_defaults(b"YB" + data[2:], {mido: False})
        check(False, "a little-endian file is taken for the list of flags")
    except ValueError:
        pass


def opening(first=7, plays=("Dm_Kokiri_0000", "Dm_Kokiri_0030")):
    """an event flow file with the opening's shape: 29 events, 2 entry points, the steps the skip relies on"""
    out = bytearray(0x48)
    out[0:6] = b"BFEVFL"
    struct.pack_into("<H", out, 0x20, 1)
    struct.pack_into("<Q", out, 0x28, 0x48)
    out += struct.pack("<Q", 0x50)
    chart = len(out)
    out += b"EVFL" + bytes(0x44)
    struct.pack_into("<HH", out, chart + 0x16, 29, 2)
    events = len(out)
    out += bytes(29 * 0x30)
    entries = len(out)
    out += bytes(2 * 0x30)
    struct.pack_into("<QQ", out, chart + 0x30, events, 0)
    struct.pack_into("<Q", out, chart + 0x40, entries)
    struct.pack_into("<H", out, entries + 0x1c, first)
    struct.pack_into("<H", out, entries + 0x30 + 0x1c, 5)
    nexts = {7: 14, 23: 0, 0: 17, 19: 10, 5: 1}
    for i in range(29):
        out[events + 0x30 * i + 8] = 1 if i in (9, 14, 17) else 0
        struct.pack_into("<H", out, events + 0x30 * i + 0x0a, nexts.get(i, 0xFFFF))
    for i, name in ((7, plays[0]), (0, plays[1])):
        text = len(out)
        out += struct.pack("<H", len(name)) + name.encode() + b"\0"
        out += bytes(-len(out) % 8)
        item = len(out)
        out += bytes([5, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", text)
        params = len(out)
        out += bytes([1, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", item)
        struct.pack_into("<Q", out, events + 0x30 * i + 0x10, params)
    return bytes(out), events, entries


def opening_event():
    data, events, entries = opening()
    new = seed.opening_skip(data)
    check(len(new) == len(data), "the opening keeps its size")
    diff = sorted(i for i in range(len(data)) if data[i] != new[i])
    check(diff == sorted((entries + 0x1c, events + 0x30 * 23 + 0x0a)), "two numbers change: the first entry point's start and the wait's next step (%r)" % diff)
    check(struct.unpack_from("<H", new, entries + 0x1c)[0] == 14 and struct.unpack_from("<H", new, events + 0x30 * 23 + 0x0a)[0] == 19,
          "the first entry point starts after the narration, and the wait goes on past Navi's cutscene")
    for bad, why in ((new, "a flow already changed"), (opening(first=5)[0], "a flow that starts elsewhere"),
                     (opening(plays=("Dm_Kokiri_0000", "Dm_Other_0001"))[0], "a flow that plays another cutscene"), (b"BFEVFL" + bytes(100), "an empty file")):
        try:
            seed.opening_skip(bad)
            check(False, "%s is changed" % why)
        except (ValueError, struct.error):
            pass


def sources():
    """the settings reach the script, and what it writes for them is listed with the seed's files"""
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    for key in ("rando_open_deku", "rando_open_forest", "rando_skip_intro"):
        check('"%s"' % key in script and '"%s"' % key in header, "%s is not a setting the script reads" % key)
    check('a.open_deku = a.open_deku or ini["rando_open_deku"] != 0' in script and 'a.skip_intro = a.skip_intro or ini["rando_skip_intro"] != 0' in script,
          "the options file's lines do not turn the changes on")
    check("list(changed.items()) + list(new_tables.items()) + list(flag_files.items())" in script,
          "the list of flags and the opening are not written with the seed's files, or not in its list of them")
    check('(" open %d%d flags" % (a.open_deku, a.open_forest) if flags else "") + (" door 7" if a.open_door else "") + (" intro skipped" if a.skip_intro else "")' in script,
          "the mod's stamp does not say which of them it holds: the launcher's run at Play would leave an old one")
    # ---- Open Door of Time: the door's flag starts set, and the game's side is what lets the sword take Link through time ----
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check(seed.OPEN_DOOR == {"Market_Child_TimeTempleDoor_Opened": True, "HavePlayedEvent.Dm_TimeTemple_0065": True} and
          "#define OOT_LEFT_TEMPLE_FLAG 0x%08xu" % seed.murmur3(b"HavePlayedEvent.Dm_TimeTemple_0065") in host and '"rando_open_door": 0' in script and
          'a.open_door = a.open_door or ini["rando_open_door"] != 0' in script and
          "new = flag_defaults(was, dict(flags, **FIELD_CLOCK, **(OPEN_DOOR if a.open_door else {})))" in script and
          'X(OPEN_DOOR, "Open Door of Time", "rando_open_door",' in header,
          "the Door of Time's flag does not start set with the setting, or the setting is not read")
    # (the rules: only what it takes to be an adult is taken off, only from a place that is an adult's alone)
    S = seed
    grown = S.ADULT | {S.BOW, S.SSC, S.BR, S.DS}
    check(S.door_need(grown, True) == grown - {S.BM, S.SSC} and S.door_need(grown, True, True) == frozenset({S.BB, S.BOW, S.BR}) and
          S.door_need(grown, False, True) == grown and S.BB in S.door_need(S.ADULT, True, True),
          "an adult's own place still asks for the Boomerang or the stones' scale, a place a child has too is changed, or bombs are no longer asked for")
    check(S.door_need(S.CHILD | {S.BB}, True, True) == S.CHILD | {S.BB} and
          S.SSC in S.door_need(grown | {"Item_Scale_Gold"}, True) and S.BM not in S.door_need(grown | {"Item_Scale_Gold"}, True),
          "a rule that is not an adult's is changed, or the Silver Scale is taken off a rule that has the Golden one")
    # (the dungeons of an adult's alone, one by one: the scale where King Zora is in the way, no bombs where no room
    #  needs them, and of an adult's four songs the ones each needs)
    songs = frozenset((S.ZL, S.SARIA, S.TIME, S.STORMS))
    deep = grown | songs
    check(S.door_need(deep, True, True, "ForestTemple") == frozenset({S.BOW, S.SARIA, S.TIME}) and
          S.door_need(deep, True, True, "IceCavern") == frozenset({S.BOW, S.SSC, S.ZL}) and
          S.door_need(deep, True, True, "WaterTemple") == frozenset({S.BB, S.BR, S.BOW, S.ZL, S.TIME}) and
          S.door_need(deep, True, True, "FireTemple") == frozenset({S.BB, S.BR, S.BOW, S.TIME}) and
          S.door_need(deep, True, True, "HyruleField") == frozenset({S.BB, S.BR, S.BOW}) | songs and
          S.SSC in S.door_need(deep, True, True, "ZoraFountain") and S.door_need(deep, False, True, "ForestTemple") == deep,
          "a dungeon of an adult's alone asks for bombs or a song it does not need, drops one it does, the way past King Zora "
          "is without the Silver Scale, or an overworld place is changed")
    check(S.DOOR_NO_BOMBS <= S.DOOR_ADULT_AREAS and set(S.DOOR_SONGS) == set(S.DOOR_ADULT_AREAS) and
          all(v <= songs for v in S.DOOR_SONGS.values()) and (S._ZL, S._SARIA, S._TIME, S._STORMS) == (S.ZL, S.SARIA, S.TIME, S.STORMS) and
          "a.open_forest, spots[h][0])" in script and "door_need(need, grown(h, area), a.open_forest, area)" in script,
          "the dungeons' own rules are not for the dungeons of an adult's alone, name songs that are not an adult's four, or are not asked")
    check(not S.DOOR_ADULT_AREAS & {"SpiritTemple", "DesertColossus", "KokiriForest", "InsideJabuJabuBelly", "DodongoCavern", "InsideTheDekuTree", "BottomOfTheWell"} and
          S.DOOR_ADULT_AREAS <= set(S.RULES),
          "a dungeon a child enters is taken for an adult's alone")
    check("needs = {h: door_need(n, shelves[h][0].ages == \"A\" if h in shelves else" in script and
          "skull_asks = lambda h: door(step(" in script and "heart_asks = lambda h: door(step(" in script,
          "the Door of Time's rules are not the chests', the gifts', the Gold Skulltulas' and the Pieces of Heart's")
    # (the flag alone did not open the door: reported from play. The door's actor is put far under the map)
    def door_file(*actors):
        return seed.byml_build(("dict", collections.OrderedDict((("Actors", ("array", [
            ("dict", collections.OrderedDict((("Gyaml", ("string", name)), ("Translate", ("array", [(0xD2, struct.pack("<f", v)) for v in (118.4, 104.9, -34.0)])))))
            for name in actors])),))), 7)
    moved, count, aside = seed.door_away(door_file("Obj_TimeTemple_SpiritStoneBase_A_01", seed.DOOR_ACTOR, seed.DOOR_SHEIK))
    rows = seed.byml_parse(moved)[0][1]["Actors"][1]
    height = lambda row: struct.unpack("<f", row[1]["Translate"][1][1][1])[0]
    check(count == 1 and abs(height(rows[1]) - (104.9 - seed.DOOR_AWAY)) < 0.01 and abs(height(rows[0]) - 104.9) < 0.01 and
          seed.door_away(door_file("Obj_TimeTemple_SpiritStoneBase_A_01")) == (None, 0, 0) and seed.DOOR_ACTOR == "Obj_TimeTemple_Door_A_01",
          "the Door of Time is not put out of the way, another actor is, or a file without it is written anew")
    # (Sheik stood at the sword's stone and his talk took the button: reported from play. He is put to the side)
    side = lambda row: struct.unpack("<f", row[1]["Translate"][1][2][1])[0]
    check(aside == 1 and abs(side(rows[2]) - (-34.0 + seed.DOOR_SHEIK_ASIDE)) < 0.01 and abs(height(rows[2]) - 104.9) < 0.01 and
          abs(side(rows[1]) + 34.0) < 0.01 and seed.DOOR_SHEIK == "Npc_Hylia_Sheik_Adult" and seed.DOOR_SHEIK_ASIDE >= 4 and
          "the Door of Time: the Market's map files have no Sheik by the sword. Nothing written." in script,
          "Sheik is not put to the side of the sword's room, is put under the map, or the door is put aside with him")
    check("new, count, aside = door_away(data)" in script and "the Door of Time: the Market's map files have no such door. Nothing written." in script,
          "the seed does not put the door out of the way with the setting, or says nothing when it finds none")
    check("#define OOT_DOOR_FLAG 0x%08xu" % seed.murmur3(b"Market_Child_TimeTempleDoor_Opened") in host and
          'const char *event = child ? "Market_Child_Field_ChildToAdult" : "Market_Adult_Field_AdultToChild";' in host and
          "if (pressed && !ask_at && !oot_event_playing(c)) ask_at = now + 500000000LL;" in host and
          "if (oot_event_playing(c) || (oot_gamedata_bool(c, 0xef2b60c2u, &loading) && loading)) return;" in host and
          'if (child && oot_pouch_count(c, "Weapon_Sword_Master") == 0)' in host and "oot_time_door(c, now, actor);" in host and
          "int hos_pad_a_held(void) {" in (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8"),
          "the game's side does not ask for the way through time at the Master Sword when the game itself does not answer, "
          "asks over an event of the game's, or does not give the sword")


def main():
    flags()
    opening_event()
    sources()
    # ---- Hyrule Field's clock: a new game starts with the flag that ends the field's held day, and the game's side sets
    #      it for a save that has it put out ----
    # (seen in play: no day turned to night before the owl's cutscene, and the Sun's Song's night was day again at once.
    #  Found with a save made before the owl: with HyruleField_ArriveEntrance set, a night asked for stayed)
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check(seed.FIELD_CLOCK == {"HyruleField_ArriveEntrance": True} and "new = flag_defaults(was, dict(flags, **FIELD_CLOCK, **(OPEN_DOOR if a.open_door else {})))" in script and
          "if True:   # (every seed: Hyrule Field's clock, FIELD_CLOCK" in script,
          "a seed's new game does not start with the flag that ends Hyrule Field's held day, or only with other settings on")
    check(seed.FIXES_VERSION >= 5 and "field_clock(" not in script, "a seed made before the field's clock ran is not made again, or the step tried first is still passed over")
    check("if (oot_gamedata_bool(c, 0x804aec99u, &reached) && !reached) {" in host and "oot_gamedata_set_bool(c, 0x804aec99u, 1);" in host and
          host.index("if (!hos_rando_on()) return;", host.index("static void oot_tracker_refresh(")) < host.index("oot_gamedata_bool(c, 0x804aec99u, &reached)") and
          "0x316c53a3u" not in host,
          "the game's side does not set the flag for a save that has it put out, or does so outside the randomizer")
    print("PASS: a new game's open ways and its opening")


if __name__ == "__main__":
    main()
