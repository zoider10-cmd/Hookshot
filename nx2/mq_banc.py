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
    # Dodongo's Cavern: the Bomb Bag in the Compass's big chest (first floor, the Armos room, reached before the upper floor and the
    # skull's eyes that need bombs), the Compass up where the Bomb Bag was. The child has the Goron's Bracelet (the cavern's
    # entrance), so the bomb flowers cover everything before it
    ("DodongoCavern", "DodongoCavern_Static.bcett.byml.zs", 12161709650443144121, ("Dynamic", "Drop__DropActor"),
     "Item_BombBag_Small", "Item_Dungeon_Compass"),
    ("DodongoCavern", "DodongoCavern_Static.bcett.byml.zs", 12161709650443144121, ("Dynamic", "GetEventName"),
     "Get_StoneOfFire_GetBombBag", "DodongoCavern_GetCompass"),
    ("DodongoCavern", "DodongoCavern_Static.bcett.byml.zs", 17531994809974271603, ("Dynamic", "Drop__DropActor"),
     "Item_Dungeon_Compass", "Item_BombBag_Small"),
    ("DodongoCavern", "DodongoCavern_Static.bcett.byml.zs", 17531994809974271603, ("Dynamic", "GetEventName"),
     "DodongoCavern_GetCompass", "Get_StoneOfFire_GetBombBag"),
    # no Heart Container after King Dodongo: the file has no recovery heart to name, a green rupee in its place
    ("DodongoCavern", "DodongoCavern_Static.bcett.byml.zs", 5936534468710061389, ("Gyaml",),
     "Obj_Heart_Container", "Obj_Rupee_Green"),
    # Inside Jabu-Jabu's Belly: the Map and the Compass trade chests (the Boomerang stays: the dungeon needs it). Their "you got"
    # events stay with the chests (the Compass's is Ruto's, the Map's has none)
    ("InsideJabuJabuBelly", "InsideJabuJabuBelly_Static.bcett.byml.zs", 14933854942830098290, ("Dynamic", "Drop__DropActor"),
     "Item_Dungeon_Map", "Item_Dungeon_Compass"),
    ("InsideJabuJabuBelly", "InsideJabuJabuBelly_Static.bcett.byml.zs", 3510516276638146208, ("Dynamic", "Drop__DropActor"),
     "Item_Dungeon_Compass", "Item_Dungeon_Map"),
]

# (Mako) no dungeon maps or compasses in Master Quest: their big chests give a green rupee (the string renamed in place in each
# file that names them, every chest with it), and the rupee's line says "......a rupee?" (RUPEE_LINE, Mals/<language>)
NO_MAPS = [
    ("InsideTheDekuTree", "InsideTheDekuTree_Static.bcett.byml.zs"),
    ("DodongoCavern", "DodongoCavern_Static.bcett.byml.zs"),
    ("DodongoCavern", "DodongoCavern_Dynamic.bcett.byml.zs"),
    ("InsideJabuJabuBelly", "InsideJabuJabuBelly_Static.bcett.byml.zs"),
]
NO_MAP_ITEM = "TBox_Rupee_Green"
# (their chests' GetEventName: RSDB EventSetting entries of NaviChat (TreasureBoxDM_NaviChat_Deku_Map...), Navi on the map or the
# compass. Jabu's compass chest keeps its own (TreasureBox_WithRuto_Room12: Ruto's, not the item's))
# Emptied, the chest no longer opened (user's play, 2026-11-12): the chest needs its event to open. Kept as they are
NO_MAP_EVENTS = ()
RUPEE_LINE = {
    "USen": "......a rupee?", "EUen": "......a rupee?",
    "USfr": "......un rubis?", "EUfr": "......un rubis ?",
    "USes": "......¿una rupia?", "EUes": "......¿una rupia?",
    "EUde": "......ein Rubin?", "EUit": "......una rupia?", "EUnl": "......een rupee?",
    "EUpl": "......rupia?", "EUru": "......рупия?", "USpt": "......uma rupia?",
    "JPja": "……ルピー？", "KRko": "……루피?", "CNzh": "……卢比？", "TWzh": "……盧比？",
}

# Navi's balloon after the map's or the compass's chest (NaviChat flow TreasureBoxDM_NaviChat_<dungeon>_Map/_Compass:
# "Now we won't get lost!", "Try looking at the map."), each fitting the shortest of the two slots in its language
NAVI_LINE = {
    "USen": "This chest is weird...", "EUen": "This chest is weird...",
    "USfr": "Bizarre, ce coffre...", "EUfr": "Bizarre, ce coffre...",
    "USes": "Qué cofre tan raro", "EUes": "Qué cofre tan raro",
    "EUde": "Komische Truhe...", "EUit": "Che forziere strano...", "EUnl": "Rare kist, zeg...",
    "EUpl": "Dziwna ta skrzynia...", "EUru": "Странный сундук.", "USpt": "Baú estranho...",
    "JPja": "へんな宝箱…", "KRko": "이상한 상자네...", "CNzh": "这宝箱好怪…", "TWzh": "這個寶箱好奇怪…",
}
TEXTS = [
    ("ActorMsg/PouchContent.msbt", ("Obj_Rupee_Green_GetCaption",), RUPEE_LINE),
    ("EventFlowMsg/NaviChat.msbt", ("Near_46", "Near_133"), NAVI_LINE),
]

# (Mako) the bosses take more hits in Master Quest: their actor pack's MaxLife (Life/LifeParameters, an integer in place: the
# pack keeps its size). (actor, the game's MaxLife, Master Quest's: about 1.5x)
BOSSES = [
    ("Enemy_DungeonBoss_Gohma", 21, 32),
    ("Enemy_DungeonBoss_Dodongo", 24, 36),
    ("Enemy_DungeonBoss_Barinade", 15, 23),
]

# (Mako) other integers of an actor pack's files, in place: (actor, file in its pack, key, the game's value, Master Quest's).
# The Kokiri shop's Deku Shield: 40 -> 55 rupees (the shop's texts name no price: the price shown is this one)
PACK_INTS = [
    ("Shop_Weapon_Shield_Deku", "GameParameter/PriceParam/Shop_Weapon_Shield_Deku.game__pouchcontent__PriceParam.bgyml",
     "BuyingPrice", 40, 55),
    ("Shop_Weapon_Shield_Hylian", "GameParameter/PriceParam/Weapon_Shield_Hylian.game__pouchcontent__PriceParam.bgyml",
     "BuyingPrice", 80, 300),
]

# (Mako) integers of RSDB tables' rows, in place: (table, __RowId, key, the game's value, Master Quest's). The shop shows and
# takes the price of PouchActorInfo's row, not the actor pack's PriceParam (the user saw 40 with only PACK_INTS)
RSDB_INTS = [
    ("PouchActorInfo", "Shop_Weapon_Shield_Deku", "BuyingPrice", 40, 55),
    ("PouchActorInfo", "Weapon_Shield_Deku", "BuyingPrice", 40, 55),   # (the shop item's name actor: in case its row is used)
    # the Market bazaar's Hylian Shield: 80 -> 300 (more than the Kokiri wallet's 200: the Gold Skulltulas' Grande bourse, 500, needed)
    ("PouchActorInfo", "Shop_Weapon_Shield_Hylian", "BuyingPrice", 80, 300),
    ("PouchActorInfo", "Weapon_Shield_Hylian", "BuyingPrice", 80, 300),
]

# (Mako) Master Quest's new games start with these game data flags set (GameData/GameDataList: the Bool's DefaultValue, in
# place). HavePlayedGetEvent.Obj_Rupee_Green: the first green rupee picked up has no "you got" show (Link holding it up), as if
# known already. (Chests play their show anyway: the map/compass chests' rupee keeps its "......a rupee?")
GAMEDATA_TRUE = ["HavePlayedGetEvent.Obj_Rupee_Green"]


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
        if not o:   # (no table: a file without strings)
            return []
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


def msbt_text(b, label):   # (an MSBT's message: its (start, end) in b, end at its NUL; UTF-8 messages only)
    if b[:8] != b"MsgStdBn" or b[0x0C] != 0:
        return None
    n = struct.unpack_from("<H", b, 0x0E)[0]
    o, sec = 0x20, {}
    for _ in range(n):
        size = struct.unpack_from("<I", b, o + 4)[0]
        sec[b[o:o + 4]] = (o + 0x10, size)
        o = (o + 0x10 + size + 15) & ~15
    if b"LBL1" not in sec or b"TXT2" not in sec:
        return None
    s, _ = sec[b"LBL1"]
    idx = None
    for i in range(struct.unpack_from("<I", b, s)[0]):
        cnt, off = struct.unpack_from("<II", b, s + 4 + 8 * i)
        p = s + off
        for _ in range(cnt):
            ln = b[p]
            if b[p + 1:p + 1 + ln] == label.encode():
                idx = struct.unpack_from("<I", b, p + 1 + ln)[0]
            p += 1 + ln + 4
    if idx is None:
        return None
    s, size = sec[b"TXT2"]
    n = struct.unpack_from("<I", b, s)[0]
    start = s + struct.unpack_from("<I", b, s + 4 + 4 * idx)[0]
    end = s + (struct.unpack_from("<I", b, s + 8 + 4 * idx)[0] if idx + 1 < n else size)
    return start, end - 1   # (the slot up to its last NUL: a message's tags may hold NULs of their own, the furigana's in Japanese)


def build_texts(romfs, out, log=print):
    """Master Quest's texts (TEXTS: the green rupee's line under its "you got", "......a rupee?"; Navi's balloon after a map or
    compass chest, "This chest is weird..."), each in its message's slot (NULs after it: the message file keeps its size)"""
    import zstandard
    folder = os.path.join(romfs, "Mals")
    if not os.path.isdir(folder):
        return 0
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zs_dictionary(romfs, b"zs.zsdic")))
    done = 0
    for name in sorted(os.listdir(folder)):
        dst = os.path.join(out, "mq", "mals", name.lower())
        if os.path.exists(dst):
            os.remove(dst)
        if not name.endswith(".sarc.zs"):
            continue
        with open(os.path.join(folder, name), "rb") as f:
            b = bytearray(d.decompressobj().decompress(f.read()))
        files = sarc_files(bytes(b))
        n = 0
        for msbt, labels, lines in TEXTS:
            line = lines.get(name[:4])
            where = files.get(msbt)
            if not line or where is None:
                continue
            s, e = where
            for label in labels:
                got = msbt_text(bytes(b[s:e]), label)
                new = line.encode()
                if got is None or len(new) > got[1] - got[0]:
                    log(f"master quest: {name}: {label} left as it is")
                    continue
                b[s + got[0]:s + got[1]] = new.ljust(got[1] - got[0], b"\0")
                n += 1
        if n:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            write_raw_zstd(dst, bytes(b))
            done += 1
    log(f"master quest: its texts in {done} languages")
    return done


def sarc_files(b):   # (a SARC's files: name -> (start, end) in b)
    assert b[:4] == b"SARC"
    hl = struct.unpack_from("<H", b, 4)[0]
    data = struct.unpack_from("<I", b, 12)[0]
    n = struct.unpack_from("<H", b, hl + 6)[0]
    names = hl + 12 + 16 * n + 8
    out = {}
    for i in range(n):
        _, attr, s, e = struct.unpack_from("<IIII", b, hl + 12 + 16 * i)
        o = names + (attr & 0xFFFFFF) * 4
        out[b[o:b.index(b"\0", o)].decode()] = (data + s, data + e)
    return out


def build_bosses(romfs, out, log=print):
    """PACK_INTS (and BOSSES' MaxLife): an integer of a file in an actor pack, in place (the pack keeps its size)"""
    import zstandard
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zs_dictionary(romfs, b"pack.zsdic")))
    edits = {}
    for actor, old, new in BOSSES:
        edits.setdefault(actor, []).append((f"Life/LifeParameters/{actor}.game__life__LifeParameters.bgyml", "MaxLife", old, new))
    for actor, file, key, old, new in PACK_INTS:
        edits.setdefault(actor, []).append((file, key, old, new))
    done = total = 0
    for actor, changes in edits.items():
        total += len(changes)
        src = os.path.join(romfs, "Pack", "Actor", actor + ".pack.zs")
        dst = os.path.join(out, "mq", "pack", "actor", (actor + ".pack.zs").lower())
        if os.path.exists(dst):
            os.remove(dst)
        if not os.path.exists(src):
            log(f"master quest: no {src}: left as it is")
            continue
        with open(src, "rb") as f:
            b = bytearray(d.decompressobj().decompress(f.read()))
        files = sarc_files(bytes(b))
        n = 0
        for file, key, old, new in changes:
            where = files.get(file)
            if where is None:
                log(f"master quest: {actor}: no {file}: left as it is")
                continue
            s, e = where
            y = Byml(bytes(b[s:e]))
            got = y.dict_slot(y.root, key)
            if got is None or got[0] != 0xD1 or y.u32(got[1]) != old:
                log(f"master quest: {actor}: {key} is not {old}: left as it is")
                continue
            struct.pack_into("<I", b, s + got[1], new)
            n += 1
        if n:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            write_raw_zstd(dst, bytes(b))
        done += n
    log(f"master quest: {done} of {total} actor values changed (bosses' life, prices)")
    return done


def build_rsdb(romfs, out, log=print):
    """RSDB_INTS: an integer of a row of an RSDB table (RSDB/<table>.Product.111.rstbl.byml.zs: an array of dictionaries, each
    with its __RowId), in place: same size"""
    import zstandard
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zs_dictionary(romfs, b"zs.zsdic")))
    tables = {}
    for table, row, key, old, new in RSDB_INTS:
        tables.setdefault(table, []).append((row, key, old, new))
    done = 0
    for table, changes in tables.items():
        name = table + ".Product.111.rstbl.byml.zs"
        src = os.path.join(romfs, "RSDB", name)
        dst = os.path.join(out, "mq", "rsdb", name.lower())
        if os.path.exists(dst):
            os.remove(dst)
        if not os.path.exists(src):
            log(f"master quest: no {src}: left as it is")
            continue
        with open(src, "rb") as f:
            b = bytearray(d.decompressobj().decompress(f.read()))
        y = Byml(bytes(b))
        o = y.root
        assert y.b[o] == 0xC0
        n = y.u32(o) >> 8
        vo = o + 4 + ((n + 3) & ~3)
        rows = {}
        for i in range(n):
            r = y.u32(vo + 4 * i)
            got = y.dict_slot(r, "__RowId") if y.b[r] == 0xC1 else None
            if got and got[0] == 0xA0:
                rows[y.strs[y.u32(got[1])]] = r
        k = 0
        for row, key, old, new in changes:
            got = y.dict_slot(rows[row], key) if row in rows else None
            if got is None or got[0] != 0xD1 or y.u32(got[1]) != old:
                log(f"master quest: {table} {row}: {key} is not {old}: left as it is")
                continue
            struct.pack_into("<I", b, got[1], new)
            k += 1
        if k:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            write_raw_zstd(dst, bytes(b))
        done += k
    log(f"master quest: {done} of {len(RSDB_INTS)} table values changed (prices)")
    return done


def mm3(s, seed=0):   # (murmur3 x86 32: the game data names' hash)
    data = s.encode()
    m = 0xFFFFFFFF
    rotl = lambda x, r: ((x << r) | (x >> (32 - r))) & m
    h, n = seed, len(data) // 4
    for i in range(n):
        k = rotl((struct.unpack_from("<I", data, 4 * i)[0] * 0xCC9E2D51) & m, 15) * 0x1B873593 & m
        h = (rotl(h ^ k, 13) * 5 + 0xE6546B64) & m
    t, k = data[4 * n:], 0
    for i in reversed(range(len(t))):
        k = (k << 8) | t[i]
    if t:
        h ^= rotl((k * 0xCC9E2D51) & m, 15) * 0x1B873593 & m
    h ^= len(data)
    h = ((h ^ (h >> 16)) * 0x85EBCA6B) & m
    h = ((h ^ (h >> 13)) * 0xC2B2AE35) & m
    return h ^ (h >> 16)


def build_gamedata(romfs, out, log=print):
    """GAMEDATA_TRUE's Bools made true by default in GameDataList (big endian BYML: in each Bool's dictionary, the Hash entry,
    then the DefaultValue entry before it, its value 0 -> 1: same size)"""
    import zstandard
    name = "GameDataList.Product.110.byml.zs"
    src = os.path.join(romfs, "GameData", name)
    dst = os.path.join(out, "mq", "gamedata", name.lower())
    if os.path.exists(dst):
        os.remove(dst)
    if not os.path.exists(src):
        log(f"master quest: no {src}: left as it is")
        return 0
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zs_dictionary(romfs, b"zs.zsdic")))
    with open(src, "rb") as f:
        b = bytearray(d.decompressobj().decompress(f.read()))
    if b[:2] != b"BY":
        log("master quest: GameDataList is not big endian BYML: left as it is")
        return 0
    kt = struct.unpack_from(">I", b, 4)[0]
    nk = struct.unpack_from(">I", b, kt)[0] & 0xFFFFFF
    keys = [bytes(b[kt + struct.unpack_from(">I", b, kt + 4 + 4 * i)[0]:b.index(b"\0", kt + struct.unpack_from(">I", b, kt + 4 + 4 * i)[0])]).decode()
            for i in range(nk)]
    kh, kd = keys.index("Hash"), keys.index("DefaultValue")
    done = 0
    for flag in GAMEDATA_TRUE:
        pat = struct.pack(">II", (kh << 8) | 0xD3, mm3(flag))
        hits = []
        at = b.find(pat)
        while at >= 0:
            for back in range(8, 8 * 6, 8):   # (DefaultValue sorts before Hash: an earlier entry of the same dictionary)
                if struct.unpack_from(">I", b, at - back)[0] == (kd << 8) | 0xD0:
                    hits.append(at - back + 4)
                    break
            at = b.find(pat, at + 1)
        if len(hits) != 1:
            log(f"master quest: game data {flag}: {len(hits)} Bools found, not 1: left as it is")
            continue
        struct.pack_into(">I", b, hits[0], 1)
        done += 1
    if done:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        write_raw_zstd(dst, bytes(b))
    log(f"master quest: {done} of {len(GAMEDATA_TRUE)} game data flags true at the start")
    return done


def rename(b, file, old, new, log):   # (a value string of the file's table renamed in place, NULs after it: every value naming it)
    y = Byml(b)
    if old not in y.strs:
        return b, 0
    if len(new.encode()) > len(old.encode()):
        log(f"master quest: {file}: {new} is longer than {old}: left as it is")
        return b, 0
    i = y.strs.index(old)
    st = struct.unpack_from("<I", b, 8)[0]
    at = st + y.u32(st + 4 + 4 * i)
    b = bytearray(b)
    b[at:at + len(old.encode())] = new.encode().ljust(len(old.encode()), b"\0")
    return bytes(b), 1


def build(romfs, out, log=print):
    import zstandard
    d = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(zs_dictionary(romfs, b"bcett.byml.zsdic")))
    files = {}
    for c in CHANGES:
        files.setdefault((c[0], c[1]), []).append(c)
    for scene, file in NO_MAPS:
        files.setdefault((scene, file), [])
    total = 0
    for (scene, file), changes in files.items():
        src = os.path.join(romfs, "Banc", scene, file)
        if not os.path.exists(src):
            log(f"master quest: no {src}: left as it is")
            continue
        with open(src, "rb") as f:
            b = d.decompressobj().decompress(f.read())
        b2, done = apply(b, changes, log)
        if (scene, file) in NO_MAPS:
            for old in ("Item_Dungeon_Map", "Item_Dungeon_Compass"):
                b2, n = rename(b2, file, old, NO_MAP_ITEM, log)
                done += n
            for old in NO_MAP_EVENTS:   # (Navi's talk about the map or the compass after the chest: none, the name made empty)
                b2, n = rename(b2, file, old, "", log)
                done += n
        dst = os.path.join(out, "mq", "banc", scene.lower(), file.lower())
        if done:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            write_raw_zstd(dst, b2)
        elif os.path.exists(dst):
            os.remove(dst)
        total += done
    log(f"master quest: {total} dungeon changes ({len(CHANGES)} listed, the maps and compasses)")
    build_bosses(romfs, out, log)
    build_texts(romfs, out, log)
    build_gamedata(romfs, out, log)
    build_rsdb(romfs, out, log)
    return total


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
