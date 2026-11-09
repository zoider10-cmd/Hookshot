"""Where the game keeps its items: an inventory of an extracted game's romfs for the randomizer work.

It reads the files on this PC and writes one text report, rando_inventory.txt: folder sizes, file names that look
related to items, and which files mention known item names (with a few of the names found beside them). The report
holds names and counts only, no game files. Nothing is changed in the game folder.

    python -I tools/rando/rando_inventory.py "F:\\Games\\OOT Remake Rando\\romfs"
    python -I tools/rando/rando_inventory.py <romfs> [--out report.txt] [--minutes 20] [--max-mb 16] [--jobs N]

Needs the zstandard package (the build's own requirement).
"""
import argparse
import collections
import os
import re
import struct
import sys
import time

ZSTD = b"\x28\xb5\x2f\xfd"
# (item names the project already knows, gpu/vk/oot_cheat_items.h, and words a chest, a Skulltula or a gift may be named with)
NEEDLES = [b"Weapon_Sword_Kokiri", b"Weapon_Shield_Deku", b"Weapon_Range_SlingShot", b"Item_Token_Gold", b"Item_Stone_Forest",
           b"Item_Hookshot", b"Item_Boomerang", b"Item_Bottle", b"Item_BombBag", b"Item_DekuNut", b"Item_Melody_",
           b"Armor_Child_Mask_", b"HeartPiece", b"HeartContainer", b"Rupee", b"SmallKey", b"BossKey",
           b"TreasureBox", b"Treasure", b"TBox", b"Tbox", b"Chest", b"Skulltula", b"GoldSkull", b"Skull",
           b"PouchContent", b"DropTable", b"DropActor", b"Reward", b"Present", b"ShopItem", b"GetItem", b"ItemGet"]
NAME_WORDS = re.compile(r"chest|treasure|tbox|skull|token|shop|reward|heartpiece|present|gift|droptable|pouch|getitem|itemget", re.I)
# (pictures, models, sound, movies, shaders and collision: large, and no item is named in them)
HEAVY = re.compile(r"\.(bntx|txtg|bfres|bwav|bars|bfstm|bfwav|mp4|webm|ivf|bfsha|bnsh|bphsh|bphcl|bphnm|bphsc|chunk|ta|bfotf|bffnt|"
                   r"bfarc|hght|water|mate|grass|quad|tex)(\.|$)", re.I)
PRINTABLE = re.compile(rb"[\x20-\x7e]{4,80}")
_dicts, _zs, _max_bytes = [], None, 0


def kind(name):
    """a file's extensions together: Tarin.bfevfl.zs -> .bfevfl.zs"""
    base = os.path.basename(name)
    dot = base.find(".")
    return base[dot:].lower() if dot > 0 else "(none)"


def unpack(data):
    if data[:4] != ZSTD:
        return data
    try:
        return _zs.ZstdDecompressor().decompress(data, max_output_size=1 << 28)
    except Exception:
        pass
    for d in _dicts:
        try:
            return _zs.ZstdDecompressor(dict_data=d).decompress(data, max_output_size=1 << 28)
        except Exception:
            pass
    return None


def sarc_entries(data):
    """(name, bytes) of a SARC's files; the names from its SFNT table when it has them"""
    try:
        if data[6:8] != b"\xff\xfe":   # (little-endian only)
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
    except (struct.error, ValueError):
        return


def blobs(name, data, depth=0):
    """the data itself, or each file of an archive (and of the archives in it)"""
    data = unpack(data)
    if data is None:
        yield name, None
    elif data[:4] == b"SARC" and depth < 3:
        for inner, raw in sarc_entries(data):
            yield from blobs(name + " ! " + inner, raw, depth + 1)
    else:
        yield name, data


def look(name, data):
    """What a blob says about items: None, or (name, size, magic, {needle: count}, [strings near the first hits])"""
    hits = {}
    for n in NEEDLES:
        c = data.count(n)
        if c:
            hits[n.decode()] = c
    if not hits:
        return None
    near = []
    for n in NEEDLES:
        at = data.find(n)
        if at < 0:
            continue
        for m in PRINTABLE.finditer(data, max(0, at - 160), min(len(data), at + 240)):
            s = m.group().decode("ascii")
            if s not in near:
                near.append(s)
        if len(near) >= 14:
            break
    magic = "".join(chr(b) if 32 <= b < 127 else "." for b in data[:8])
    return name, len(data), magic, hits, near[:14]


def start_worker(romfs, max_bytes):
    global _dicts, _zs, _max_bytes
    import zstandard
    _zs, _max_bytes = zstandard, max_bytes
    try:
        raw = zstandard.ZstdDecompressor().decompress(open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb").read(),
                                                      max_output_size=1 << 28)
        _dicts = [zstandard.ZstdCompressionDict(d, dict_type=zstandard.DICT_TYPE_FULLDICT) for _, d in sarc_entries(raw)]
    except Exception:
        _dicts = []   # (no dictionary archive: the files that need one are counted as not read)


def scan(job):
    """one file: (relative path, [findings], blobs read, blobs not read)"""
    romfs, rel = job
    found, read, unread = [], 0, 0
    try:
        with open(os.path.join(romfs, rel), "rb") as f:
            data = f.read()
        for name, blob in blobs(rel, data):
            if blob is None:
                unread += 1
                continue
            read += 1
            if len(blob) <= _max_bytes * 8:
                r = look(name, blob)
                if r:
                    found.append(r)
    except Exception as e:   # (one odd file does not stop the report)
        return rel, [], read, unread + 1, "%s: %s" % (type(e).__name__, e)
    return rel, found, read, unread, None


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("romfs")
    p.add_argument("--out", default="rando_inventory.txt")
    p.add_argument("--minutes", type=float, default=20, help="stop reading file contents after this long")
    p.add_argument("--max-mb", type=int, default=16, help="skip files larger than this on disk")
    p.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    a = p.parse_args()
    romfs = os.path.abspath(a.romfs)
    if not os.path.isdir(romfs):
        sys.exit("not a folder: %s" % romfs)
    try:
        import zstandard   # noqa: F401
    except ImportError:
        sys.exit("the zstandard package is missing: python -m pip install zstandard")
    import multiprocessing

    out = []
    say = out.append
    t0 = time.time()

    # ---- 1. what is there ----
    files = []
    for top, dirs, names in os.walk(romfs):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(top, name)
            try:
                files.append((os.path.relpath(path, romfs).replace("\\", "/"), os.path.getsize(path)))
            except OSError:
                pass
    print("%d files; reading..." % len(files), flush=True)
    say("romfs inventory: %d files, %.2f GB" % (len(files), sum(s for _, s in files) / 2**30))
    say("")
    say("== 1. top folders: files, size, most common kinds ==")
    tops = collections.defaultdict(lambda: [0, 0, collections.Counter()])
    for rel, size in files:
        t = tops[rel.split("/")[0] if "/" in rel else "(root)"]
        t[0] += 1
        t[1] += size
        t[2][kind(rel)] += 1
    for top in sorted(tops, key=lambda k: -tops[k][1]):
        n, size, kinds = tops[top]
        say("%-28s %7d files %9.1f MB   %s" % (top, n, size / 2**20, ", ".join("%s x%d" % kv for kv in kinds.most_common(6))))
    say("")
    say("== 2. second-level folders of the 12 folders with the most files ==")
    for top in sorted(tops, key=lambda k: -tops[k][0])[:12]:
        sub = collections.Counter(rel.split("/")[1] for rel, _ in files if rel.startswith(top + "/") and rel.count("/") >= 2)
        if sub:
            say("%s/: %d folders; %s" % (top, len(sub), ", ".join("%s x%d" % kv for kv in sub.most_common(25))))
    say("")
    say("== 3. file names with an item-like word (first 400 of %d) ==" % sum(1 for rel, _ in files if NAME_WORDS.search(rel)))
    shown = 0
    for rel, size in files:
        if NAME_WORDS.search(rel) and shown < 400:
            say("%9d  %s" % (size, rel))
            shown += 1
    say("")

    # ---- 2. what the files say ----
    todo = [rel for rel, size in files if size <= a.max_mb << 20 and not HEAVY.search(rel)]
    skipped = len(files) - len(todo)
    findings, errors = [], []
    read = unread = done = 0
    deadline = t0 + a.minutes * 60
    stopped = False
    with multiprocessing.Pool(a.jobs, start_worker, (romfs, a.max_mb << 20)) as pool:
        for rel, found, r, u, err in pool.imap_unordered(scan, ((romfs, rel) for rel in todo), chunksize=32):
            done += 1
            read += r
            unread += u
            findings += found
            if err and len(errors) < 30:
                errors.append("%s: %s" % (rel, err))
            if done % 5000 == 0:
                print("  %d of %d files, %d with item names, %.0f s" % (done, len(todo), len(findings), time.time() - t0), flush=True)
            if time.time() > deadline:
                stopped = True
                pool.terminate()
                break
    say("== 4. contents: %d of %d files read (%d skipped as pictures, models, sound or larger than %d MB)%s ==" % (
        done, len(todo), skipped, a.max_mb, "; STOPPED at the time limit, run again with --minutes 60" if stopped else ""))
    say("%d pieces read, %d not read (compressed in a way this script does not open), %d pieces name an item" % (read, unread, len(findings)))
    for e in errors:
        say("  error: " + e)
    say("")
    say("== 5. where the item names are: by top folder, kind and file magic ==")
    groups = collections.defaultdict(lambda: [0, collections.Counter()])
    for name, size, magic, hits, near in findings:
        outer = name.split(" ! ")[0]
        inner = name.split(" ! ")[-1]
        g = groups[(outer.split("/")[0], kind(outer), kind(inner) if " ! " in name else "-", magic[:4])]
        g[0] += 1
        g[1].update(hits)
    say("%-22s %-22s %-18s %-5s %6s  %s" % ("folder", "file kind", "kind inside", "magic", "pieces", "names found (count)"))
    for key in sorted(groups, key=lambda k: -groups[k][0])[:120]:
        n, hits = groups[key]
        say("%-22s %-22s %-18s %-5s %6d  %s" % (key + (n, ", ".join("%s %d" % kv for kv in hits.most_common(10)))))
    say("")
    say("== 6. for each name: the pieces that say it most (8 each), with the text beside it ==")
    for needle in [n.decode() for n in NEEDLES]:
        with_it = sorted((f for f in findings if needle in f[3]), key=lambda f: -f[3][needle])
        if not with_it:
            continue
        say("-- %s: in %d pieces" % (needle, len(with_it)))
        for name, size, magic, hits, near in with_it[:8]:
            say("   %s  (%d bytes, %s) x%d" % (name, size, magic, hits[needle]))
            say("      near: " + " | ".join(near))
    say("")
    say("== 7. the pieces whose own name has an item-like word and that name an item (first 150) ==")
    shown = 0
    for name, size, magic, hits, near in sorted(findings):
        if NAME_WORDS.search(name) and shown < 150:
            say("   %s  (%d bytes, %s)  %s" % (name, size, magic, ", ".join("%s %d" % kv for kv in sorted(hits.items(), key=lambda kv: -kv[1])[:8])))
            shown += 1
    say("")
    say("took %.0f s" % (time.time() - t0))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("wrote %s (%d lines, %.0f KB) in %.0f s" % (os.path.abspath(a.out), len(out), os.path.getsize(a.out) / 1024, time.time() - t0))


if __name__ == "__main__":
    main()
