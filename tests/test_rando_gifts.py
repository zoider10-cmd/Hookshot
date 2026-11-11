"""A character's gift made another item (tools/rando/rando_seed.py: gift_item), on a made-up flow.

A scene's flow hands Link an item by calling a sub-flow with the item's name as a parameter. A flow is built here
with such calls, then checked: only the pointers of the parameters that are the old item's name change, and the
file's size in its header; the new name is at the file's end, as the game's strings are (a length, the bytes, a
zero); the old name's bytes stay where they were, for whatever else uses them; a name passed on from the caller, a
step that is no sub-flow call, and a parameter of another value are left; a flow without the item gives None.

    python -I -B tests/test_rando_gifts.py
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


def flow(steps):
    """A BFEVFL file of one flowchart. steps: [(kind, [(parameter's type, its string)])]: 4 is a sub-flow call, 0 an
    action; a parameter of type 5 is a string of its own, 0 a name passed on. Returns (the bytes, where each
    parameter's pointer is, by (step, parameter))."""
    out = bytearray(b"BFEVFL" + bytes(0x2a))
    struct.pack_into("<H", out, 0x20, 1)
    table = len(out)
    out += bytes(8)
    chart = len(out)
    struct.pack_into("<Q", out, 0x28, table)
    struct.pack_into("<Q", out, table, chart)
    out += b"EVFL" + bytes(0x44)
    struct.pack_into("<H", out, chart + 0x16, len(steps))
    events = len(out)
    out += bytes(len(steps) * 0x30)
    struct.pack_into("<Q", out, chart + 0x30, events)
    pool, pointers = {}, {}
    for i, (kind, params) in enumerate(steps):
        out[events + 0x30 * i + 8] = kind
        items = []
        for k, (ptype, value) in enumerate(params):
            if value not in pool:   # (a string is in the file once, whoever names it)
                pool[value] = len(out)
                out += struct.pack("<H", len(value)) + value.encode() + b"\0"
                out += bytes(-len(out) % 8)
            item = len(out)
            out += bytes([ptype, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", pool[value])
            items.append(item)
            pointers[(i, k)] = item + 0x10
        container = len(out)
        out += bytes([1, 0]) + struct.pack("<H", len(items)) + bytes(12) + b"".join(struct.pack("<Q", it) for it in items)
        struct.pack_into("<Q", out, events + 0x30 * i + 0x10, container)
    struct.pack_into("<I", out, 0x1c, len(out))
    return bytes(out), pointers


def main():
    steps = [(4, [(5, "Item_Gauntlet_Goron"), (5, "Other")]),      # (the gift: a sub-flow call that names the item)
             (0, [(5, "Item_Gauntlet_Goron")]),                    # (an action that names it: the scene's own actor)
             (4, [(0, "Item_Gauntlet_Goron")]),                    # (a call that passes on a parameter of that name)
             (4, [(5, "Item_ZeldaLetter"), (5, "Item_Gauntlet_Goron")]),   # (a second call that gives it)
             (4, [])]
    data, pointers = flow(steps)
    new = seed.gift_item(data, "Item_Gauntlet_Goron", "Obj_Heart_Piece")
    name = b"Obj_Heart_Piece"
    at = (len(data) + 7) & ~7
    check(new[at:at + 2 + len(name) + 1] == struct.pack("<H", len(name)) + name + b"\0" and len(new) % 8 == 0 and len(new) > len(data),
          "the new name is not at the file's end as a string of the game's")
    check(struct.unpack_from("<I", new, 0x1c)[0] == len(new), "the file's size in its header is not the new size")
    changed = sorted(i for i in range(len(data)) if data[i] != new[i])
    want = {pointers[(0, 0)], pointers[(3, 1)]}
    check(changed and all(any(p <= i < p + 8 for p in want) or 0x1c <= i < 0x20 for i in changed),
          "more than the gifts' pointers and the file's size changed: %r" % changed)
    for key, pointer in pointers.items():
        now = struct.unpack_from("<Q", new, pointer)[0]
        check((now == at) == (pointer in want) and (pointer in want or now == struct.unpack_from("<Q", data, pointer)[0]),
              "the parameter %r points at the wrong string" % (key,))
    check(data.count(b"Item_Gauntlet_Goron") == new.count(b"Item_Gauntlet_Goron") == 1, "the old name's bytes were changed, or are there twice")
    check(seed.gift_item(data, "Item_NoSuch", "Obj_Heart_Piece") is None, "a flow without the item was changed")
    check(seed.gift_item(new, "Item_Gauntlet_Goron", "Item_Bow") is None, "a flow whose gift was changed still gives the old item")
    again = seed.gift_item(new, "Obj_Heart_Piece", "Item_Bow")
    check(again is not None and struct.unpack_from("<I", again, 0x1c)[0] == len(again) and again[:len(data)].count(b"Item_Gauntlet_Goron") == 1,
          "a gift changed once cannot be changed again")
    for bad, why in ((b"BFEVFL" + bytes(100), "an empty file"), (data[:-8], "a file shorter than its header says"), (b"YB" + data[2:], "a file that is no flow")):
        try:
            seed.gift_item(bad, "Item_Gauntlet_Goron", "Obj_Heart_Piece")
            check(False, "%s is taken" % why)
        except (ValueError, struct.error, IndexError):
            pass
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("gift_sizes, FLOW_EXTRA)" in script and "list(gift_files.items())" in script, "a changed flow is not written with the seed, or its size table entry is not raised")
    print("PASS: a character's gift made another item")


if __name__ == "__main__":
    main()
