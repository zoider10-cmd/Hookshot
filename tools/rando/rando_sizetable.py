"""Looks for the game's table of file sizes (if it has one) in an extracted game's romfs.

Games on this engine keep a table that says how large each file is once unpacked; a file that has grown past its
entry is not loaded. Such a table lists each file by the CRC32 of its path, so this script computes that for a few map
files and looks for those numbers in the game's other files. Prints what it finds: names and numbers only, no game
files. Nothing is changed.

    python -I tools/rando/rando_sizetable.py "F:\\Games\\OOT Remake Rando\\romfs"

Needs the zstandard package.
"""
import os
import re
import struct
import sys
import time
import zlib

ZSTD = b"\x28\xb5\x2f\xfd"
HEAVY = re.compile(r"\.(bntx|txtg|bfres|bwav|bars|bfstm|bfwav|mp4|webm|ivf|bfsha|bnsh|bphsh|bphcl|bphnm|bphsc|chunk|extm|bcul|"
                   r"bkprb|bkres)(\.|$)", re.I)
PROBES = ["Banc/KokiriForest/KokiriForest_Child_Dynamic.bcett.byml", "Banc/KokiriForest/KokiriForest_Adult_Dynamic.bcett.byml",
          "Banc/KokiriForest/KokiriForest_Child_Static.bcett.byml", "Banc/FireTemple/FireTemple_Static.bcett.byml"]


def main():
    if len(sys.argv) < 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(__doc__)
    romfs = os.path.abspath(sys.argv[1])
    import zstandard as zs
    dicts = []
    try:
        raw = zs.ZstdDecompressor().decompress(open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read(), max_output_size=1 << 28)
        start = struct.unpack_from("<I", raw, 0x0c)[0]
        for k in range(struct.unpack_from("<H", raw, 0x1a)[0]):
            _, _, st, end = struct.unpack_from("<IIII", raw, 0x20 + k * 16)
            dicts.append(zs.ZstdCompressionDict(raw[start + st:start + end], dict_type=zs.DICT_TYPE_FULLDICT))
    except Exception as e:
        print("no dictionaries (%s)" % e)

    def unpack(data):
        if data[:4] != ZSTD:
            return data
        for d in [None] + dicts:
            try:
                return (zs.ZstdDecompressor(dict_data=d) if d else zs.ZstdDecompressor()).decompress(data, max_output_size=1 << 28)
            except Exception:
                pass
        return None

    # the map files' real sizes, and the numbers a table would list them under (the path with and without .zs)
    probes = []
    for rel in PROBES:
        path = os.path.join(romfs, *rel.split("/")) + ".zs"
        if not os.path.isfile(path):
            continue
        data = unpack(open(path, "rb").read())
        size = len(data) if data else 0
        for name in (rel, rel + ".zs"):
            probes.append((name, struct.pack("<I", zlib.crc32(name.encode()) & 0xffffffff), struct.pack(">I", zlib.crc32(name.encode()) & 0xffffffff), size))
        print("%s: %d bytes unpacked, %d on disk" % (rel, size, os.path.getsize(path)))
    if not probes:
        sys.exit("none of the map files this looks for is there")

    # ---- 1. files that sound like a size table ----
    print("\n== files whose name sounds like a size table ==")
    todo = []
    for top, dirs, names in os.walk(romfs):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(top, name)
            rel = os.path.relpath(path, romfs).replace("\\", "/")
            if re.search(r"size|restbl|rstb|resource", name, re.I):
                print("  %10d  %s" % (os.path.getsize(path), rel))
            if not HEAVY.search(name) and os.path.getsize(path) <= 32 << 20:
                todo.append((0 if rel.startswith(("System/", "RSDB/")) or "/" not in rel else 1, rel, path))
    todo.sort()

    # ---- 2. files that hold the map files' CRC32s ----
    print("\n== files that hold those map files' path checksums (%d files to read) ==" % len(todo))
    t0, found = time.time(), 0
    for n, (_, rel, path) in enumerate(todo):
        if n and n % 10000 == 0:
            print("  ... %d of %d files, %.0f s" % (n, len(todo), time.time() - t0), flush=True)
        try:
            data = unpack(open(path, "rb").read())
        except OSError:
            continue
        if not data:
            continue
        hits = []
        for name, le, be, size in probes:
            for label, needle, fmt in (("LE", le, "<I"), ("BE", be, ">I")):
                at = data.find(needle)
                if at >= 0 and at + 8 <= len(data):
                    after = struct.unpack_from(fmt, data, at + 4)[0]
                    before = struct.unpack_from(fmt, data, at - 4)[0] if at >= 4 else 0
                    hits.append((name, label, at, before, after, size))
        if len({h[0].replace(".zs", "") for h in hits}) >= 2:   # (two different map files' checksums: no coincidence)
            found += 1
            print("  %s  (%d bytes unpacked, starts %r)" % (rel, len(data), bytes(data[:16])))
            for name, label, at, before, after, size in hits:
                print("    %-62s %s at %#x: the number after it %d (before it %d); the file is %d: room %+d" % (
                    name, label, at, after, before, size, after - size))
    print("\n%s (%.0f s)" % ("%d file(s) list the map files by checksum: the size table, most likely" % found if found else
                              "no file lists these map files by checksum: no size table of the usual kind", time.time() - t0))


if __name__ == "__main__":
    main()
