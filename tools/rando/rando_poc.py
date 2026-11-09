"""Proof of concept for the randomizer: one chest gives another item, through a mod file.

Finds a chest by its hash in the map placement files (romfs/Banc/**/*.bcett.byml.zs), changes what it holds
(Dynamic.Drop__DropActor) to another item name that the same file already uses, and writes the changed map file into
the game's mods folder: <game folder>\\mods\\<name>\\romfs\\Banc\\..., which Mako loads in place of the game's own file.
The game's own files are not touched: delete the mod's folder (or put a '-' before its name) to undo it.

Only the item's name is swapped (one number in the file), so the file keeps its size and layout.

    python -I tools/rando/rando_poc.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_poc.py <romfs> [--hash 0x9652edaf3158c9b6] [--to TBox_Rupee_Purple] [--name rando-poc] [--game <folder>] [--list]

The default: the first chest of Mido's house in Kokiri Forest (a green Rupee) gives a purple Rupee.
Needs the zstandard package.
"""
import argparse
import os
import re
import struct
import sys

ZSTD = b"\x28\xb5\x2f\xfd"
ITEM = re.compile(r"^(TBox_|Item_|Weapon_|Armor_|Obj_Heart|Obj_Rupee)")


def table(d, at):
    n = int.from_bytes(d[at + 1:at + 4], "little")
    out = []
    for k in range(n):
        s = at + struct.unpack_from("<I", d, at + 4 + 4 * k)[0]
        out.append(d[s:d.index(b"\0", s)].decode("utf-8", "replace"))
    return out


def entries(d, at, keys):
    """a dictionary node's (key, type, value, where its value is)"""
    if d[at] != 0xC1:
        return
    for k in range(int.from_bytes(d[at + 1:at + 4], "little")):
        e = at + 4 + 8 * k
        key = int.from_bytes(d[e:e + 3], "little")
        yield keys[key] if key < len(keys) else "", d[e + 3], struct.unpack_from("<I", d, e + 4)[0], e + 4


def chests(d):
    """(hash, where the Drop__DropActor value is, its string index) of every actor that has one; and the tables"""
    if d[:2] != b"YB":
        raise ValueError("not a little-endian BYML")
    key_at, str_at, root = struct.unpack_from("<III", d, 4)
    keys, strings = table(d, key_at), table(d, str_at)
    found = []
    for name, kind, value, _ in entries(d, root, keys):
        if name != "Actors" or kind != 0xC0:
            continue
        n = int.from_bytes(d[value + 1:value + 4], "little")
        vals = value + 4 + (n + 3 & ~3)
        for i in range(n):
            if d[value + 4 + i] != 0xC1:
                continue
            actor = struct.unpack_from("<I", d, vals + 4 * i)[0]
            ident, gyaml, drop = None, "", None
            for k, t, v, _ in entries(d, actor, keys):
                if k == "Hash" and t == 0xD5:
                    ident = struct.unpack_from("<Q", d, v)[0]
                elif k == "Hash" and t == 0xD3:
                    ident = v
                elif k == "Gyaml" and t == 0xA0:
                    gyaml = strings[v]
                elif k == "Dynamic" and t == 0xC1:
                    for dk, dt, dv, where in entries(d, v, keys):
                        if dk == "Drop__DropActor" and dt == 0xA0:
                            drop = (where, dv)
            if drop and ident is not None:
                found.append((ident, gyaml, drop[0], drop[1]))
    return found, strings


def unpack(data, zs, dicts):
    if data[:4] != ZSTD:
        return data
    try:
        return zs.ZstdDecompressor().decompress(data, max_output_size=1 << 28)
    except Exception:
        pass
    for d in dicts:
        try:
            return zs.ZstdDecompressor(dict_data=d).decompress(data, max_output_size=1 << 28)
        except Exception:
            pass
    raise ValueError("could not be decompressed")


def dictionaries(romfs, zs):
    try:
        raw = zs.ZstdDecompressor().decompress(open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read(), max_output_size=1 << 28)
        start = struct.unpack_from("<I", raw, 0x0c)[0]
        return [zs.ZstdCompressionDict(raw[start + st:start + end], dict_type=zs.DICT_TYPE_FULLDICT)
                for _, _, st, end in (struct.unpack_from("<IIII", raw, 0x20 + k * 16) for k in range(struct.unpack_from("<H", raw, 0x1a)[0]))]
    except Exception:
        return []


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("--hash", default="0x9652edaf3158c9b6", help="the chest's hash, from rando_locations.txt")
    p.add_argument("--to", default="TBox_Rupee_Purple", help="the item it gives: a name the same map file already uses")
    p.add_argument("--name", default="rando-poc", help="the mod's folder name")
    p.add_argument("--game", help="the game folder (default: the folder the romfs is in)")
    p.add_argument("--list", action="store_true", help="only show the chest and the item names its map files offer")
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    game = os.path.abspath(a.game) if a.game else os.path.dirname(romfs)
    target = int(a.hash, 16)
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = dictionaries(romfs, zs)

    done = 0
    for top, dirs, names in os.walk(os.path.join(romfs, "Banc")):
        dirs.sort()
        for name in sorted(names):
            if ".bcett.byml" not in name.lower():
                continue
            path = os.path.join(top, name)
            rel = os.path.relpath(path, romfs)
            try:
                data = bytearray(unpack(open(path, "rb").read(), zs, dicts))
                found, strings = chests(data)
            except Exception as e:
                print("skipped %s: %s" % (rel, e))
                continue
            for ident, gyaml, where, index in found:
                if ident != target:
                    continue
                old = strings[index]
                offers = sorted(s for s in strings if ITEM.match(s))
                print("%s: %s %#x holds %s" % (rel, gyaml, ident, old))
                if a.list or a.to not in strings:
                    if not a.list:
                        print("  %s is not a name this map file uses, so it cannot be swapped in by this script." % a.to)
                    print("  item names this file offers (--to): " + ", ".join(offers))
                    continue
                struct.pack_into("<I", data, where, strings.index(a.to))
                again, _ = chests(data)   # (read back: the chest, and only it, changed)
                changed = [(i, strings[x]) for (i, _, _, x), (_, _, _, y) in zip(again, found) if x != y]
                if changed != [(target, a.to)]:
                    sys.exit("  the change did not read back as expected (%r): nothing written" % (changed,))
                out = os.path.join(game, "mods", a.name, "romfs", rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "wb") as f:
                    f.write(zs.ZstdCompressor(level=9).compress(bytes(data)) if path.lower().endswith(".zs") else bytes(data))
                print("  now %s -> wrote %s" % (a.to, out))
                done += 1
    if a.list:
        return
    if not done:
        sys.exit("no map file was changed: check the hash against rando_locations.txt, or run with --list")
    print("%d map file(s) written. Start the game: hookshot_log.txt should have lines starting with 'mods:'." % done)
    print("To undo: delete %s" % os.path.join(game, "mods", a.name))


if __name__ == "__main__":
    main()
