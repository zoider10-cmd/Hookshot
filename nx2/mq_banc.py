"""(Mako) Master Quest's dungeon changes, made at build time from the player's own game files.

Each change rewrites one value of one actor in a dungeon's placement file (romfs/Banc/<Scene>/<file>.bcett.byml.zs, BYML v7,
zstd with the dictionary bcett.byml.zsdic): which item a chest holds, which "you got..." event it plays, what a boss leaves.
The new value is always a string the same file already has, so only a 4-byte string index changes: the file keeps its size
(no resource size table change). The files go to <out>/mq/banc/<scene>/<file> (lower case, as the game asks for them),
as zstd frames of raw blocks; host/prompts.c serves them in place of the game's only while Master Quest is on.

The opened chests are remembered by the actor (Hash), not by what is inside: Master Quest keeps its own saves (user\\save_mq).

Rules (dev/masterquest/etude-master-quest.md, section 7/8): a chest's item moves with its event; a big item only goes to a chest
reached earlier, without that item; nothing moves from one dungeon to another; keys and boss keys stay.
"""
import os
import struct
import sys

# (scene, file, actor Hash, key path in the actor, the game's value, Master Quest's)
CHANGES = [
    # Inside the Deku Tree: the Slingshot in the first room's big chest (the map's), the map where the Slingshot was
    ("InsideTheDekuTree", "InsideTheDekuTree_Static.bcett.byml.zs", 8579518566955184384, ("Dynamic", "Drop__DropActor"),
     "Item_Dungeon_Map", "Item_Range_SlingShot"),
    ("InsideTheDekuTree", "InsideTheDekuTree_Static.bcett.byml.zs", 8579518566955184384, ("Dynamic", "GetEventName"),
     "InsideTheDekuTree_GetMap", "InsideTheDekuTree_GetSlingShot"),
    ("InsideTheDekuTree", "InsideTheDekuTree_Static.bcett.byml.zs", 821372075822700622, ("Dynamic", "Drop__DropActor"),
     "Item_Range_SlingShot", "Item_Dungeon_Map"),
    ("InsideTheDekuTree", "InsideTheDekuTree_Static.bcett.byml.zs", 821372075822700622, ("Dynamic", "GetEventName"),
     "InsideTheDekuTree_GetSlingShot", "InsideTheDekuTree_GetMap"),
    # the small chests: the Deku nuts (room 3) and the Deku sticks (room 4) trade places
    ("InsideTheDekuTree", "InsideTheDekuTree_Dynamic.bcett.byml.zs", 11368028582977069031, ("Dynamic", "Drop__DropActor"),
     "TBox_DekuNutBundle", "Item_DekuStickBundle_Small"),
    ("InsideTheDekuTree", "InsideTheDekuTree_Dynamic.bcett.byml.zs", 12889104996486369065, ("Dynamic", "Drop__DropActor"),
     "Item_DekuStickBundle_Small", "TBox_DekuNutBundle"),
    # no Heart Container after Queen Gohma: a recovery heart in its place (only the Pieces of Heart raise the life)
    ("InsideTheDekuTree", "InsideTheDekuTree_Static.bcett.byml.zs", 17948245526767051747, ("Gyaml",),
     "Obj_Heart_Container", "Obj_Heart"),
    # the same after Barinade and Twinrova (the other bosses' files have no recovery heart to point to yet)
    ("InsideJabuJabuBelly", "InsideJabuJabuBelly_Static.bcett.byml.zs", 17608884438514432711, ("Gyaml",),
     "Obj_Heart_Container", "Obj_Heart"),
    ("SpiritTemple", "SpiritTemple_Static.bcett.byml.zs", 4720088048159616469, ("Gyaml",),
     "Obj_Heart_Container", "Obj_Heart"),
]


def zs_dictionary(romfs, want):
    import zstandard
    with open(os.path.join(romfs, "Pack", "ZsDic.pack.zs"), "rb") as f:
        b = zstandard.ZstdDecompressor().decompressobj().decompress(f.read())
    data, = struct.unpack_from("<I", b, 12)
    hl, = struct.unpack_from("<H", b, 4)
    n, = struct.unpack_from("<H", b, hl + 6)
    names = hl + 12 + 16 * n + 8
    for i in range(n):
        attr, start, end = struct.unpack_from("<III", b, hl + 12 + 16 * i + 4)
        o = names + (attr & 0xFFFFFF) * 4
        if b[o:b.index(b"\0", o)] == want:
            return b[data + start:data + end]
    raise ValueError("no %s in Pack/ZsDic.pack.zs" % want.decode())


class Byml:
    """Just enough BYML (v7, little endian) to find a value's 4-byte slot"""

    def __init__(self, b):
        if b[:2] != b"YB":
            raise ValueError("not a little-endian BYML")
        self.b = b
        _, kt, st, self.root = struct.unpack_from("<HIII", b, 2)
        self.keys = self.table(kt)
        self.strs = self.table(st)

    def u32(self, o):
        return struct.unpack_from("<I", self.b, o)[0]

    def table(self, o):
        n = self.u32(o) >> 8
        out = []
        for i in range(n):
            s = o + self.u32(o + 4 + 4 * i)
            out.append(self.b[s:self.b.index(b"\0", s)].decode("utf-8"))
        return out

    def dict_slot(self, o, key):   # (a dictionary node at o: its key's (type, slot offset), or None)
        assert self.b[o] == 0xC1
        for i in range(self.u32(o) >> 8):
            e = o + 4 + 8 * i
            if self.keys[self.u32(e) & 0xFFFFFF] == key:
                return self.b[e + 3], e + 4
        return None

    def actors(self):   # (each actor's dictionary node offset)
        t, slot = self.dict_slot(self.root, "Actors")
        o = self.u32(slot)
        assert self.b[o] == 0xC0
        n = self.u32(o) >> 8
        vo = o + 4 + ((n + 3) & ~3)
        return [self.u32(vo + 4 * i) for i in range(n)]

    def actor_hash(self, a):
        t, slot = self.dict_slot(a, "Hash")
        assert t == 0xD5
        return struct.unpack_from("<Q", self.b, self.u32(slot))[0]


def apply(b, changes, log):
    y = Byml(b)
    b = bytearray(b)
    by_hash = {y.actor_hash(a): a for a in y.actors()}
    done = 0
    for scene, file, h, path, old, new in changes:
        node = by_hash.get(h)
        if node is None:
            log(f"master quest: {file}: no actor {h}: left as it is")
            continue
        slot = None
        for i, k in enumerate(path):
            got = y.dict_slot(node, k)
            if got is None:
                break
            t, s = got
            if i == len(path) - 1:
                slot = (t, s)
            else:
                node = y.u32(s)
        if slot is None or slot[0] != 0xA0:
            log(f"master quest: {file}: actor {h} has no {'.'.join(path)}: left as it is")
            continue
        now = y.strs[y.u32(slot[1])]
        if now != old or new not in y.strs:
            log(f"master quest: {file}: actor {h} {'.'.join(path)} is {now} (not {old}) or the file has no {new}: left as it is")
            continue
        struct.pack_into("<I", b, slot[1], y.strs.index(new))
        done += 1
    return bytes(b), done


def write_raw_zstd(path, data):   # (as host/prompts.c write_zstd_raw: a frame of raw blocks, no dictionary)
    with open(path, "wb") as f:
        f.write(struct.pack("<IBBI", 0xFD2FB528, 0x80, 7 << 3, len(data)))
        at = 0
        while True:
            k = min(len(data) - at, 131072)
            last = at + k == len(data)
            bh = (k << 3) | (1 if last else 0)
            f.write(bytes((bh & 0xFF, (bh >> 8) & 0xFF, (bh >> 16) & 0xFF)))
            f.write(data[at:at + k])
            at += k
            if last:
                break


def build(romfs, out, log=print):
    import zstandard
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zs_dictionary(romfs, b"bcett.byml.zsdic")))
    files = {}
    for c in CHANGES:
        files.setdefault((c[0], c[1]), []).append(c)
    total = 0
    for (scene, file), changes in files.items():
        src = os.path.join(romfs, "Banc", scene, file)
        if not os.path.exists(src):
            log(f"master quest: no {src}: left as it is")
            continue
        with open(src, "rb") as f:
            b = d.decompressobj().decompress(f.read())
        b2, done = apply(b, changes, log)
        dst = os.path.join(out, "mq", "banc", scene.lower(), file.lower())
        if done:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            write_raw_zstd(dst, b2)
        elif os.path.exists(dst):
            os.remove(dst)
        total += done
    log(f"master quest: {total} of {len(CHANGES)} dungeon changes")
    return total


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
