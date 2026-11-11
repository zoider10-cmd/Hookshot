"""The Kokiri Sword's chest with another item in it (tools/rando/rando_seed.py: sword_chest_plain), on a made-up flow.

The chest's event opens it (Dm_SY_Treasurebox), then plays Link putting the sword on his back (Dm_Kokiri_0063). A flow
is built here with the steps the script relies on, then checked: one number changes, the first cutscene's next step,
which becomes what followed the second; the file keeps its size; and a flow that is not the one this was written
for is not changed. The script uses it only where the chest holds another item, and its seeds are made again for it.

    python -I -B tests/test_rando_swordchest.py
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


def flow(start=48, plays=("Dm_SY_Treasurebox", "Dm_Kokiri_0063"), events_n=227, after=211):
    """a BFEVFL file of one flowchart: 27 entry points, the eighth starting at `start`; 48 -> 47 -> 88 -> `after`"""
    out = bytearray(b"BFEVFL" + bytes(0x2a))   # (the header: the flowcharts' table's place is at 0x28)
    struct.pack_into("<H", out, 0x20, 1)
    table = len(out)
    out += bytes(8)
    chart = len(out)
    struct.pack_into("<Q", out, 0x28, table)
    struct.pack_into("<Q", out, table, chart)
    out += b"EVFL" + bytes(0x44)
    struct.pack_into("<HH", out, chart + 0x16, events_n, 27)
    events = len(out)
    out += bytes(events_n * 0x30)
    entries = len(out)
    out += bytes(27 * 0x20)
    struct.pack_into("<Q", out, chart + 0x30, events)
    struct.pack_into("<Q", out, chart + 0x40, entries)
    struct.pack_into("<H", out, entries + 0x20 * 7 + 0x1c, start)
    nexts = {48: 47, 47: 88, 88: after}
    for i in range(events_n):
        out[events + 0x30 * i + 8] = 1 if i == 211 else 0
        struct.pack_into("<H", out, events + 0x30 * i + 0x0a, nexts.get(i, 0xFFFF))
    for i, name in ((47, plays[0]), (88, plays[1])):
        text = len(out)
        out += struct.pack("<H", len(name)) + name.encode() + b"\0"
        out += bytes(-len(out) % 8)
        item = len(out)
        out += bytes([5, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", text)
        params = len(out)
        out += bytes([1, 0]) + struct.pack("<H", 1) + bytes(12) + struct.pack("<Q", item)
        struct.pack_into("<Q", out, events + 0x30 * i + 0x10, params)
    return bytes(out), events


def main():
    data, events = flow()
    new = seed.sword_chest_plain(data)
    check(len(new) == len(data), "the flow keeps its size")
    diff = sorted(i for i in range(len(data)) if data[i] != new[i])
    check(diff and all(events + 0x30 * 47 + 0x0a <= i < events + 0x30 * 47 + 0x0c for i in diff),
          "one number changes: the chest's opening's next step (%r)" % diff)
    check(struct.unpack_from("<H", new, events + 0x30 * 47 + 0x0a)[0] == 211, "the chest's opening goes on to what followed the sword's cutscene")
    for bad, why in ((new, "a flow already changed"), (flow(start=5)[0], "a flow whose event starts elsewhere"),
                     (flow(plays=("Dm_SY_Treasurebox", "Dm_Other_0001"))[0], "a flow that plays another cutscene"),
                     (flow(plays=("Dm_Other_0001", "Dm_Kokiri_0063"))[0], "a flow that opens the chest another way"),
                     (flow(events_n=228)[0], "a flow of another length"), (flow(after=200)[0], "a flow that goes on elsewhere"),
                     (b"BFEVFL" + bytes(100), "an empty file")):
        try:
            seed.sword_chest_plain(bad)
            check(False, "%s is changed" % why)
        except (ValueError, struct.error, IndexError):
            pass
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("if any(spots[h][6] == SWORD_EVENT and item != S for h, item in gives.items()):" in script and
          "flag_files[SWORD_FLOW] = sword_chest_plain(" in script, "the script does not leave the cutscene out where the chest holds another item, and only there")
    check(seed.SWORD_EVENT == "Get_StoneOfForest_GetSword" and seed.SWORD_FLOW == "Event/EventFlow/Get_StoneOfForest.bfevfl.zs",
          "the event or its flow is no longer the Kokiri Sword's chest's")
    check(seed.FIXES_VERSION >= 3 and 'stamp = "placement %d%sfixes %d\\n" % (placement, rest, FIXES_VERSION)' in script,
          "a seed made before the cutscene was left out is not made again")
    print("PASS: the Kokiri Sword's chest with another item")


if __name__ == "__main__":
    main()
