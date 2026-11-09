"""What the game's item actors are made of: a report of the parameter files in their actor packs.

For each named actor, reads <romfs>/Pack/Actor/<name>.pack.zs on this PC and writes every parameter file in it as
text to one report, rando_actors.txt. For comparing items that behave differently when they come from another chest
(the Slingshot is lost by a chest's autosave, the Lens of Truth is not). Names and values only, no game files.
Nothing is changed.

    python -I tools/rando/rando_actors.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_actors.py <romfs> [--out report.txt] [name ...]

Without names: the thirteen gating items as chests hold them, and the names the inventory knows them by.
Needs the zstandard package.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rando_locations as loc   # (the BYML reader)

DEFAULT = ["Item_Range_SlingShot", "Weapon_Range_SlingShot", "Item_Sword_Kokiri", "Weapon_Sword_Kokiri", "Item_GlassTruth",
           "Item_HoverBoot", "Armor_Adult_HoverBoot", "Item_BombBag_Small", "Item_Boomerang", "Item_Range_Bow", "Weapon_Range_Bow",
           "Item_Hammer", "Item_HeavyBoot", "Armor_Adult_HeavyBoot", "Item_Longshot", "Item_Hookshot", "Item_Gauntlet_Silver",
           "Item_Gauntlet_Gold", "Item_Shield_Mirror", "Weapon_Shield_Mirror", "TBox_Rupee_Purple", "Obj_Heart_Piece", "Obj_TBox_A_01"]


def sarc(data):
    """(name, bytes) of a SARC's files"""
    if data[:4] != b"SARC":
        return
    start = struct.unpack_from("<I", data, 0x0c)[0]
    count = struct.unpack_from("<H", data, 0x1a)[0]
    names = 0x20 + count * 16 + 8
    for k in range(count):
        _, attr, st, end = struct.unpack_from("<IIII", data, 0x20 + k * 16)
        name = "#%d" % k
        if attr >> 24:
            at = names + (attr & 0xffffff) * 4
            name = data[at:data.index(b"\0", at)].decode("utf-8", "replace")
        yield name, data[start + st:start + end]


def lines(v, indent, out, limit=400):
    """a value as indented text, long lists cut"""
    pad = "  " * indent
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, (dict, list)) and x:
                out.append("%s%s:" % (pad, k))
                lines(x, indent + 1, out, limit)
            else:
                out.append("%s%s: %s" % (pad, k, loc.short(x, 200)))
    elif isinstance(v, list):
        for i, x in enumerate(v[:40]):
            if isinstance(x, (dict, list)) and x:
                out.append("%s- [%d]" % (pad, i))
                lines(x, indent + 1, out, limit)
            else:
                out.append("%s- %s" % (pad, loc.short(x, 200)))
        if len(v) > 40:
            out.append("%s- ... %d more" % (pad, len(v) - 40))
    else:
        out.append(pad + loc.short(v, 200))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("names", nargs="*")
    p.add_argument("--out", default="rando_actors.txt")
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    folder = os.path.join(romfs, "Pack", "Actor")
    if not os.path.isdir(folder):
        sys.exit("no Pack/Actor folder in %s" % romfs)
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = loc.dictionaries(romfs, zs)
    out, found = [], 0
    for name in a.names or DEFAULT:
        path = os.path.join(folder, name + ".pack.zs")
        out.append("=" * 100)
        if not os.path.isfile(path):
            out.append("%s: no actor pack of that name" % name)
            continue
        found += 1
        try:
            pack = loc.unpack(open(path, "rb").read(), zs, dicts)
        except Exception as e:
            out.append("%s: %s" % (name, e))
            continue
        files = list(sarc(pack))
        out.append("%s: %d files in its pack" % (name, len(files)))
        for inner, raw in files:
            out.append("  " + inner + "  (%d bytes)" % len(raw))
        for inner, raw in files:
            if raw[:2] != b"YB":
                continue
            out.append("")
            out.append("-- %s ! %s" % (name, inner))
            try:
                lines(loc.Byml(raw).root, 1, out)
            except Exception as e:
                out.append("  could not be read: %s" % e)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("wrote %s (%d lines, %.0f KB): %d actor packs found" % (os.path.abspath(a.out), len(out), os.path.getsize(a.out) / 1024, found))


if __name__ == "__main__":
    main()
