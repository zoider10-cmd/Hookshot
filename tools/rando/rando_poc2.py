"""Second proof of concept for the randomizer: one chest gives ANY item, by adding to its map file.

The first test swapped a number in place, which only allows item names the map file already uses and changes every
chest that shares the same stored parameters. This one adds to the end of the map file:
  - a parameter block of its own for the chest (a copy of the shared one, with the new item), so its twins keep theirs;
  - when the map file does not have the item's name yet, a new copy of its string table with the name added at the end.
The file's existing contents stay where they are; the file gets larger. The game does not load a file larger than
its entry in its size table (about 290 bytes of room), so an updated copy of that table goes into the mod as well.

Writes <game folder>\\mods\\rando-zz-test2\\romfs\\Banc\\... (the name sorts after rando-seed, so it wins over a seed's
copy of the same map file). The game's own files are not touched: delete that folder to undo it.

    python -I tools/rando/rando_poc2.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_poc2.py <romfs> [--hash 0x3f38f9b9a399e19a] [--to Obj_Heart_Piece] [--game <folder>] [--pad N]

The default: one of the three blue-Rupee chests of Mido's house in Kokiri Forest gives a Piece of Heart; the other
two must still give blue Rupees. Needs the zstandard package.
"""
import argparse
import os
import struct
import sys

ZSTD = b"\x28\xb5\x2f\xfd"
MOD = "rando-zz-test2"


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
    """Every actor with a Dynamic.Drop__DropActor: (hash, type, where the actor points at its Dynamic block, the block,
    the item's name). And the key and string tables."""
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
            ident, gyaml, dyn = None, "", None
            for k, t, v, where in entries(d, actor, keys):
                if k == "Hash" and t == 0xD5:
                    ident = struct.unpack_from("<Q", d, v)[0]
                elif k == "Hash" and t == 0xD3:
                    ident = v
                elif k == "Gyaml" and t == 0xA0:
                    gyaml = strings[v]
                elif k == "Dynamic" and t == 0xC1:
                    dyn = (where, v)
            if dyn:
                for dk, dt, dv, _ in entries(d, dyn[1], keys):
                    if dk == "Drop__DropActor" and dt == 0xA0:
                        found.append((ident, gyaml, dyn[0], dyn[1], strings[dv] if dv < len(strings) else "<%d>" % dv))
    return found, keys, strings


def string_table(strings):
    """a BYML string table: 0xC2, the count, an offset for each string and one for the end, the strings"""
    blob = b"".join(s.encode("utf-8") + b"\0" for s in strings)
    head = 4 + 4 * (len(strings) + 1)
    offsets, at = [], head
    for s in strings:
        offsets.append(at)
        at += len(s.encode("utf-8")) + 1
    offsets.append(at)
    out = bytes([0xC2]) + len(strings).to_bytes(3, "little") + b"".join(struct.pack("<I", o) for o in offsets) + blob
    return out + b"\0" * (-len(out) % 4)


def give(data, target, item):
    """data (a BYML map file) with the chest `target` holding `item`: (new bytes, what it held, notes), or None when
    the chest is not in it"""
    found, keys, strings = chests(data)
    mine = [f for f in found if f[0] == target]
    if not mine:
        return None
    _, gyaml, dyn_where, dyn_at, old = mine[0]
    out = bytearray(data)
    out += b"\0" * (-len(out) % 4)
    notes = []
    if item in strings:
        index = strings.index(item)
    else:   # a new string table at the end, the name added last: every index the file already uses stays right
        index = len(strings)
        at = len(out)
        out += string_table(strings + [item])
        struct.pack_into("<I", out, 8, at)
        notes.append("the name was new to this file: string table copied to the end with it (%d strings)" % (index + 1))
    # the chest's own Dynamic block at the end: the shared one, with the item's index changed
    n = int.from_bytes(data[dyn_at + 1:dyn_at + 4], "little")
    block = bytearray(data[dyn_at:dyn_at + 4 + 8 * n])
    for k, (dk, dt, dv, where) in enumerate(entries(data, dyn_at, keys)):
        if dk == "Drop__DropActor":
            struct.pack_into("<I", block, 4 + 8 * k + 4, index)
    at = len(out)
    out += block
    struct.pack_into("<I", out, dyn_where, at)
    sharing = sum(1 for f in found if f[3] == dyn_at) - 1
    if sharing:
        notes.append("%d other actor(s) shared its parameters and keep the old ones" % sharing)
    # read back: this chest holds the item, every other one what it held
    again, _, _ = chests(bytes(out))
    if len(again) != len(found):
        raise ValueError("the file did not read back with the same actors")
    for was, now in zip(found, again):
        expect = item if was[0] == target and was[2] == dyn_where else was[4]
        if now[4] != expect or now[0] != was[0]:
            raise ValueError("did not read back as written (%r: %s, expected %s)" % (now[0], now[4], expect))
    return bytes(out), old, gyaml, notes


def size_entry(size):
    """what the game's size table holds for a map file of `size` bytes unpacked: the size rounded up to 32, and 264
    (every map file looked at had exactly that: Kokiri Forest's three and the Fire Temple's)"""
    return (size + 31 & ~31) + 264


def size_table_update(table, sizes):
    """The size table (System/Resource/ResourceSizeTable...rsizetable, "RESTBL": a header of 22 bytes, then an entry of
    a path's CRC32 and a size for each file, sorted by the CRC32) with the entries of `sizes` ({path without .zs: bytes
    unpacked}) raised to fit. Returns (new table, [(path, old entry, new entry)]). A file larger than its entry is not
    loaded: Kokiri Forest lost its houses and bridges to a map file that had grown past it."""
    import zlib
    if table[:6] != b"RESTBL":
        raise ValueError("not a size table (%r)" % table[:6])
    version, _, count, _ = struct.unpack_from("<IIII", table, 6)
    if 22 + count * 8 > len(table):
        raise ValueError("the size table's entry count does not fit the file")
    out, notes = bytearray(table), []
    for path, size in sorted(sizes.items()):
        crc = zlib.crc32(path.replace("\\", "/").encode()) & 0xffffffff
        lo, hi = 0, count
        while lo < hi:   # (the entries are sorted by checksum)
            mid = (lo + hi) // 2
            if struct.unpack_from("<I", table, 22 + mid * 8)[0] < crc:
                lo = mid + 1
            else:
                hi = mid
        at = 22 + lo * 8
        if lo >= count or struct.unpack_from("<I", table, at)[0] != crc:
            raise ValueError("%s is not in the size table" % path)
        old = struct.unpack_from("<I", table, at + 4)[0]
        new = max(old, size_entry(size))
        struct.pack_into("<I", out, at + 4, new)
        notes.append((path, old, new))
    return bytes(out), notes


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
    p.add_argument("--hash", default="0x3f38f9b9a399e19a", help="the chest's hash, from rando_locations.txt")
    p.add_argument("--to", default="Obj_Heart_Piece", help="the item it gives: any name a chest of the game holds")
    p.add_argument("--game", help="the game folder (default: the folder the romfs is in)")
    p.add_argument("--no-size-table", action="store_true", help="leave the game's size table as it is (the earlier tests)")
    p.add_argument("--pad", type=int, default=0, help="also add this many unused bytes to the end (a test of the file's size alone)")
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    game = os.path.abspath(a.game) if a.game else os.path.dirname(romfs)
    target = int(a.hash, 16)
    try:
        import zstandard as zs
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    dicts = dictionaries(romfs, zs)
    done, sizes = 0, {}
    for top, dirs, names in os.walk(os.path.join(romfs, "Banc")):
        dirs.sort()
        for name in sorted(names):
            if ".bcett.byml" not in name.lower():
                continue
            path = os.path.join(top, name)
            rel = os.path.relpath(path, romfs)
            try:
                data = unpack(open(path, "rb").read(), zs, dicts)
                result = give(data, target, a.to)
            except Exception as e:
                print("skipped %s: %s" % (rel, e))
                continue
            if not result:
                continue
            new, old, gyaml, notes = result
            if a.pad > 0:
                new += b"\0" * (a.pad + 3 & ~3)
                notes.append("%d unused bytes added to the end" % (a.pad + 3 & ~3))
            out = os.path.join(game, "mods", MOD, "romfs", rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(zs.ZstdCompressor(level=9).compress(new) if path.lower().endswith(".zs") else new)
            print("%s: %s %#x held %s, now %s" % (rel, gyaml, target, old, a.to))
            print("  the file grew from %d to %d bytes" % (len(data), len(new)))
            for note in notes:
                print("  " + note)
            print("  wrote " + out)
            sizes[rel.replace("\\", "/")[:-3] if rel.lower().endswith(".zs") else rel.replace("\\", "/")] = len(new)
            done += 1
    if not done:
        sys.exit("no map file has a chest with that hash: check it against rando_locations.txt")
    # the game's size table, with room for the map files as they are now, in the mod too
    folder = os.path.join(romfs, "System", "Resource")
    tables = [n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if "rsizetable" in n.lower()]
    table_out = os.path.join(game, "mods", MOD, "romfs", "System", "Resource")
    if a.no_size_table:
        for n in tables:
            if os.path.isfile(os.path.join(table_out, n)):
                os.remove(os.path.join(table_out, n))
        print("the size table was left as the game's (--no-size-table)")
    elif not tables:
        print("NOTE: no size table found in %s: the grown map files may not load" % folder)
    for n in ([] if a.no_size_table else tables):
        try:
            new_table, notes = size_table_update(unpack(open(os.path.join(folder, n), "rb").read(), zs, dicts), sizes)
        except Exception as e:
            sys.exit("the size table %s could not be updated (%s): the map files above will not load as they are.\n"
                     "Delete %s" % (n, e, os.path.join(game, "mods", MOD)))
        os.makedirs(table_out, exist_ok=True)
        with open(os.path.join(table_out, n), "wb") as f:
            f.write(zs.ZstdCompressor(level=9).compress(new_table) if n.lower().endswith(".zs") else new_table)
        for path, old, new in notes:
            print("size table: %s %d -> %d" % (path, old, new))
        print("  wrote " + os.path.join(table_out, n))
    print("%d map file(s) written. To undo: delete %s" % (done, os.path.join(game, "mods", MOD)))


if __name__ == "__main__":
    main()
