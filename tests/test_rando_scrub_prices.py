"""Deku Scrubs, On, 10 rupees each (tools/rando/rando_seed.py SCRUB_CHEAP, scrub_prices; rando_scrubs 2, asked for
2026-11-17): no game data.

- the Price of each one-time sale's call (by its entry point and its item, both sizes of an upgrade) is made 10, in
  place: the file keeps its size, a sale of another entry point and a call with no Price are left as they were;
- the choice is read apart from On, moves no item (the stamp's second line), and is the setting's third in the game's
  table and the launcher's.

    python -I -B tests/test_rando_scrub_prices.py
"""
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


def flow(calls, entries):
    """A BFEVFL file of one flowchart of sub-flow calls, each ending the flow. calls: [{name: str or int}], each a call
    with those named parameters (a string or a number). entries: [(name, its first event)]. Returns (the bytes,
    {(event, name): where that parameter's value is})."""
    out = bytearray(b"BFEVFL" + bytes(0x2a))
    struct.pack_into("<H", out, 0x20, 1)
    table = len(out)
    out += bytes(8)
    chart = len(out)
    struct.pack_into("<Q", out, 0x28, table)
    struct.pack_into("<Q", out, table, chart)
    out += b"EVFL" + bytes(0x44)
    struct.pack_into("<H", out, chart + 0x16, len(calls))
    struct.pack_into("<H", out, chart + 0x18, len(entries))
    at_events = len(out)
    out += bytes(len(calls) * 0x30)
    struct.pack_into("<Q", out, chart + 0x30, at_events)

    def string(value):
        at = len(out)
        out.extend(struct.pack("<H", len(value)) + value.encode() + b"\0")
        out.extend(bytes(-len(out) % 8))
        return at

    def names_dict(names):   # (a root node, then a node of 16 bytes each, its name's pointer at +8)
        at = len(out)
        out.extend(bytes(8 + 16 * (len(names) + 1)))
        for k, name in enumerate(names):
            struct.pack_into("<Q", out, at + 8 + 16 * (k + 1) + 8, string(name))
        return at

    where = {}
    for i, params in enumerate(calls):
        e = at_events + 0x30 * i
        out[e + 8] = 4
        struct.pack_into("<H", out, e + 0x0a, 0xFFFF)
        items = []
        for name, value in params.items():
            item = len(out)
            if isinstance(value, str):
                text = string(value)
                item = len(out)
                out.extend(bytes([5, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", text))
            else:
                out.extend(bytes([2, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<i", value) + bytes(4))
            where[(i, name)] = item + 0x10
            items.append(item)
        keys = names_dict(list(params))
        container = len(out)
        out.extend(bytes([1, 0]) + struct.pack("<H", len(items)) + bytes(4) + struct.pack("<Q", keys))
        for item in items:
            out.extend(struct.pack("<Q", item))
        struct.pack_into("<Q", out, e + 0x10, container)
    names = names_dict([n for n, _ in entries])
    table2 = len(out)
    for _, first in entries:
        out.extend(bytes(0x1c) + struct.pack("<H", first) + bytes(2))
    struct.pack_into("<Q", out, chart + 0x38, names)
    struct.pack_into("<Q", out, chart + 0x40, table2)
    struct.pack_into("<I", out, 0x1c, len(out))
    return bytes(out), where


def main():
    S = seed
    calls = [
        {"ActorName": "Obj_Heart_Piece", "Price": 100, "SellerMessageId": "a"},   # 0: "Pouch"'s Piece of Heart
        {"ActorName": "Item_StickBag_Medium", "Price": 40},                       # 1: "Pouch"'s stick upgrade
        {"ActorName": "Obj_Heart_Piece", "Price": 100},                           # 2: "Secret"'s Piece of Heart
        {"ActorName": "Item_DekuSeed", "Price": 20},                              # 3: "Pouch"'s seeds, sold again and again
        {"ActorName": "Obj_Heart_Piece"},                                         # 4: no price
    ]
    data, where = flow(calls, [("Pouch", 0), ("Pouch1", 1), ("Secret", 2), ("Pouch3", 3), ("Pouch4", 4)])
    price = lambda b, i: struct.unpack_from("<i", b, where[(i, "Price")])[0]
    check([price(data, i) for i in range(4)] == [100, 40, 100, 20], "the test's flow is not made as meant")
    new, found = S.scrub_prices(data, {("Pouch", "Obj_Heart_Piece"), ("Pouch1", "Item_StickBag_Medium")})
    check(len(new) == len(data) and [price(new, i) for i in range(4)] == [S.SCRUB_CHEAP, S.SCRUB_CHEAP, 100, 20],
          "the sales' prices are not the ones changed: %r" % [price(new, i) for i in range(4)])
    check(found == {("Pouch", "Obj_Heart_Piece"), ("Pouch1", "Item_StickBag_Medium")}, "the sales found are not the ones changed: %r" % (found,))
    check(S.flow_reach(new, "Secret") == {2}, "the changed flow is not whole")
    _, found = S.scrub_prices(data, {("Pouch4", "Obj_Heart_Piece")})
    check(found == set(), "a call with no price is said to be a sale")
    check(S.SCRUB_CHEAP == 10 and " scrubs cheap" in S.QOL_STAMP, "the price is not 10, or the choice moves items")
    check(S.stamp_settings(" scrubs 1 words 2 scrubs cheap shops 1") == " scrubs 1 words 2 shops 1", "the stamp's first line keeps the choice")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('a.scrubs_cheap = a.scrubs and ini["rando_scrubs"] == 2' in script and '(" scrubs cheap" if a.scrubs_cheap else "")' in script and
          "now, found = scrub_prices(unpack(" in script and "gift_items(gift_files[rel] if rel in gift_files else unpack(" in script,
          "the script does not read the choice, or its items' swap does not start from the priced flow")
    header = (ROOT / "gpu" / "vk" / "oot_rando.h").read_text(encoding="utf-8")
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    check('"Off", "On", "On, 10 rupees each")' in header and
          'new object[] { "rando_scrubs", "Deku Scrubs", new[] { "Off", "On", "On, 10 rupees each" }, new[] { 0, 1, 2 },' in launcher,
          "the choice is not the setting's third in the game's table and the launcher's")
    print("PASS: Deku Scrubs at 10 rupees each")


if __name__ == "__main__":
    main()
