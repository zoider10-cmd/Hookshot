"""A new game's changes (tools/rando/rando_seed.py) on made-up files: no game data, no zstandard.

Open Deku Tree and Open forest exit make two flags of the game's list of flags start put out: the list is a big-endian
BYML, and only those flags' starting values change. Skip opening passes over the two cutscenes of the opening's event
flow: two numbers of the file change, and a flow that is not the one it was written for is refused.

    python -I -B tests/test_rando_newgame.py
"""
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
    check('(" open %d%d flags" % (a.open_deku, a.open_forest) if flags else "") + (" intro skipped" if a.skip_intro else "")' in script,
          "the mod's stamp does not say which of them it holds: the launcher's run at Play would leave an old one")


def main():
    flags()
    opening_event()
    sources()
    # ---- Hyrule Field's clock: the step that holds its sky and time is passed over, and a save that has the flag set
    #      has it put out by the game's side ----
    # (seen in play: no day turned to night before the owl's cutscene, and the Sun's Song's night was day again at once)
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check('FIELD_FLOW = "Event/EventFlow/Goto_HyruleCastle.bfevfl.zs"' in script and 'FIELD_FLAG = "HyruleField_ChangeENV"' in script and
          "flag_files[FIELD_FLOW] = field_clock(" in script and
          'if (step(7) != (0, 182) or "Dm_Kokiri_0155" not in strings(7) or step(182) != (0, 21) or FIELD_FLAG not in strings(182)):' in script and
          'struct.pack_into("<H", out, event(7) + 0x0a, 21)' in script,
          "a seed does not pass over the step that holds Hyrule Field's sky and time, or does so without checking the steps")
    check(seed.FIXES_VERSION >= 4, "a seed made before the field's clock ran is not made again")
    try:
        seed.field_clock(b"BFEVFL" + bytes(200))
        check(False, "a file that is not the flow is changed all the same")
    except (ValueError, struct.error):
        pass
    check("if (oot_gamedata_bool(c, 0x316c53a3u, &held) && held) {" in host and "oot_gamedata_set_bool(c, 0x316c53a3u, 0);" in host and
          host.index("if (!hos_rando_on()) return;", host.index("static void oot_tracker_refresh(")) < host.index("oot_gamedata_bool(c, 0x316c53a3u, &held)"),
          "the game's side does not put the flag out for a save that has it set, or does so outside the randomizer")
    print("PASS: a new game's open ways and its opening")


if __name__ == "__main__":
    main()
