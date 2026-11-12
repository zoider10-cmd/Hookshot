"""The randomizer's Shops setting (tools/rando/rando_seed.py: SHOPS, shop_pack, shop_rows, shop_goods, shelf_actors,
shop_caption) on made-up files: no game data.

Four shelves of each of six shops sell what the shuffle put there, once. Checked here:

- the table: six shops, four shelves each, none the Happy Mask Shop's, no shield, tunic or potion among them, each
  with what goes into the pool for it;
- an item's shelf actor (shop_pack): the shelf base's files and the item's, an actor with the base's as its parent
  and the item's own name, model, animation and place in the pouch, a table of game parameters with the item's
  entries and a price of its own, and the three files no other pack has; a pouch file a pick-up changed is taken;
- its rows in the game's three lists of actors (shop_rows): in their order by name, the item's model with a
  shelf's heaps, a shelf's row in the game's list, the item's in the pouch's with what it costs; made again, one row;
- a keeper's goods list (shop_goods): the place sells the new actor, one in stock, with what the game waited for
  and its price offsets left out, the other places as they were; a place that is not the actor named is an error;
- a map file's shelves (shelf_actors): by actor and place in the row (none is 0), the others left;
- the words under an item's name (msbt_add, shop_caption): another line with the item's description, found by its
  label in the group the game's hash puts it in; the file's other lines as they were; done again, nothing;
- a price is never more than the child's wallet holds, rolled or not;
- the script reads the setting, names it in the seed's stamp, and writes the shops' files with the seed.

    python -I -B tests/test_rando_shops.py
"""
import collections
import importlib.util
import random
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rando_seed", ROOT / "tools" / "rando" / "rando_seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


def tree(value):
    """a Python value as a tree of byml_parse"""
    if isinstance(value, dict):
        return ("dict", collections.OrderedDict((k, tree(v)) for k, v in value.items()))
    if isinstance(value, list):
        return ("array", [tree(v) for v in value])
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, bool):
        return (0xD0, struct.pack("<I", int(value)))
    if isinstance(value, float):
        return (0xD2, struct.pack("<f", value))
    return (0xD1, struct.pack("<I", value & 0xffffffff))


def byml(value):
    return seed.byml_build(tree(value), 7)


def plain(node):
    if node[0] == "dict":
        return {k: plain(v) for k, v in node[1].items()}
    if node[0] == "array":
        return [plain(v) for v in node[1]]
    if node[0] == "string":
        return node[1]
    if node[0] == 0xD2:
        return struct.unpack("<f", node[1])[0]
    return struct.unpack("<I", node[1])[0]


def read(data):
    return plain(seed.byml_parse(data)[0])


def text_file(lines, groups=5):
    """A text file (MSBT, UTF-8) of the lines [(label, its bytes)], its labels in the groups the game's hash gives."""
    by = [[] for _ in range(groups)]
    for i, (label, _) in enumerate(lines):
        by[seed.msbt_hash(label, groups)].append(bytes([len(label)]) + label.encode() + struct.pack("<I", i))
    lbl = bytearray(struct.pack("<I", groups) + bytes(8 * groups))
    for g in range(groups):
        struct.pack_into("<II", lbl, 4 + 8 * g, len(by[g]), len(lbl))
        lbl += b"".join(by[g])
    txt = bytearray(struct.pack("<I", len(lines)) + bytes(4 * len(lines)))
    for i, (_, raw) in enumerate(lines):
        struct.pack_into("<I", txt, 4 + 4 * i, len(txt))
        txt += raw + b"\0"
    out = bytearray(b"MsgStdBn" + b"\xff\xfe" + bytes(2) + bytes([0, 3]) + struct.pack("<H", 2) + bytes(0x10))
    for kind, sec in ((b"LBL1", bytes(lbl)), (b"TXT2", bytes(txt))):
        out += kind + struct.pack("<I", len(sec)) + bytes(8) + sec + b"\xab" * (-len(sec) % 16)
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


ACTOR = seed.ACTOR_FILE
REF = seed.ACTOR_REF
TABLE = "GameParameter/GameParameterTable/%s.engine__actor__GameParameterTable.bgyml"
PRICE = "GameParameter/PriceParam/%s.game__pouchcontent__PriceParam.bgyml"
POUCH = "Component/PouchContentParam/%s.game__component__PouchContentParam.bgyml"
MODEL = "Component/ModelInfo/%s.engine__component__ModelInfo.bgyml"


def packs():
    base = collections.OrderedDict()
    base[ACTOR % seed.SHOP_BASE] = byml({"Components": {"GameParameterTableRef": "?" + TABLE % seed.SHOP_BASE, "PhysicsRef": "?Component/Physics/Shelf.bgyml"}})
    base[TABLE % seed.SHOP_BASE] = byml({"Category": "Default", "Components": {"PriceParam": "?" + PRICE % seed.SHOP_BASE}})
    base[PRICE % seed.SHOP_BASE] = byml({"BuyingPrice": 1, "SellingPrice": 1})
    base["Component/Physics/Shelf.bgyml"] = byml({"Shelf": True})
    sample = collections.OrderedDict(base)
    sample[ACTOR % seed.SHOP_SAMPLE] = byml({"$parent": REF % seed.SHOP_BASE, "Components": {"GameParameterTableRef": "?" + TABLE % seed.SHOP_SAMPLE}})
    sample[TABLE % seed.SHOP_SAMPLE] = byml({"$parent": "Work/" + (TABLE % seed.SHOP_BASE).replace(".bgyml", ".gyml"), "Category": "Default",
                                             "Components": {"PriceParam": "?" + PRICE % seed.SHOP_SAMPLE}})
    sample[PRICE % seed.SHOP_SAMPLE] = byml({"BuyingPrice": 20, "SellingPrice": 1})
    item = collections.OrderedDict()
    item[ACTOR % "Item_Thing"] = byml({"$parent": "Work/Actor/Item_Thing_Small.engine__actor__ActorParam.gyml",
                                       "Components": {"ActorNameRef": "?ActorSystem/ActorName/Obj_Thing.engine__actor__ActorName.bgyml",
                                                      "GameParameterTableRef": "?" + TABLE % "Item_Thing", "ModelInfoRef": "?" + MODEL % "Item_Thing"}})
    item[ACTOR % "Item_Thing_Small"] = byml({"Components": {"ASRef": "?AS/Item_Common.root.asb", "PouchContentRef": "?" + POUCH % "Item_Thing",
                                                            "ModelInfoRef": "?" + MODEL % "Item_Thing_Small"}})
    item[TABLE % "Item_Thing"] = byml({"Category": "Default", "Components": {"ThingParam": "?GameParameter/Thing/Item_Thing.bgyml"}})
    item[MODEL % "Item_Thing"] = byml({"FmdbName": "Item_Thing"})
    item[POUCH % "Item_Thing"] = byml({"PouchActor": REF % "Item_Thing"})
    item["Component/Physics/Shelf.bgyml"] = byml({"Shelf": False})   # (a name the base has too: the base's is kept)
    return seed.sarc_write(item), seed.sarc_write(base), seed.sarc_write(sample)


def main():
    # ---- the table ----
    slots = [(shop, index, actor) for shop in seed.SHOPS for index, actor in shop.slots]
    check(len(seed.SHOPS) == 6 and all(len(shop.slots) == 4 for shop in seed.SHOPS) and len({shop.key for shop in seed.SHOPS}) == 6,
          "the shops are not six of four shelves each")
    check(all(len({index for index, _ in shop.slots}) == 4 and all(0 <= index < 8 for index, _ in shop.slots) for shop in seed.SHOPS),
          "a shop's shelves are not four places of its row of eight")
    check(not any(word in actor for _, _, actor in slots for word in ("Mask", "Shield", "Armor", "Potion", "Fairy")) and
          not any("023" in param for shop in seed.SHOPS for param in shop.params),
          "a mask, a shield, a tunic, a potion or a fairy is among the shelves, or the Happy Mask Shop among the shops")
    check(all(shop.areas and shop.areas[0] in seed.AREA_NAMES and shop.ages in ("C", "A", "CA") and len(shop.place) == 3 and shop.params for shop in seed.SHOPS),
          "a shop has no area the tracker names, no ages, no place or no goods list")
    check(seed.shelf_item("Shop_DekuSeedBundle_02") == "Item_ScrubBusinessSeed" and seed.shelf_item("Shop_DekuStick") == "Item_DekuStickBundle_Small" and
          seed.shelf_item("Shop_ArrowBundle_03") == "TBox_ArrowBundle_Medium" and seed.shelf_item("Shop_Heart") == seed.SHELF_OTHER == "TBox_Rupee_Red" and
          seed.shop_actor("Item_Hammer") == "Shop_Rando_Item_Hammer", "a shelf's item for the pool, or an item's shelf actor, is not what it was")
    check(all(seed.shelf_item(actor) in seed.ITEM_WORDS for _, _, actor in slots), "what goes into the pool for a shelf has no words for the tracker")

    # ---- a price ----
    roll = random.Random(1)
    rolled = [seed.shop_price("Item_Hammer", roll) for _ in range(300)]
    check(seed.shop_price("Item_Hammer") == seed.shop_price("Item_BombBag_Medium") == seed.SHOP_PRICE_BIG and seed.shop_price("Obj_Heart_Piece") == 100 and
          seed.shop_price("TBox_Rupee_Purple") == seed.SHOP_PRICE_RUPEE and seed.shop_price("TBox_DekuNutBundle") == seed.SHOP_PRICE_OTHER,
          "an item's price is not its kind's")
    check(max([seed.SHOP_PRICE_BIG, seed.SHOP_PRICE_OTHER, seed.SHOP_PRICE_RUPEE] + list(seed.SHOP_PRICES.values()) + rolled) <= 200 and min(rolled) >= 10 and
          len(set(rolled)) > 10 and all(p % 10 == 0 for p in rolled), "a price is more than the child's wallet holds, or is not rolled in tens")

    # ---- an item's shelf actor ----
    item, base, sample = packs()
    new, own, named = seed.shop_pack("Item_Thing", item, base, sample, 70)
    files = seed.sarc_read(new)
    name = "Shop_Rando_Item_Thing"
    check(own == [ACTOR % name, TABLE % name, PRICE % name] and named == "Obj_Thing", "the shelf actor's own files, or the name its texts go by, are not given")
    actor = read(files[ACTOR % name])
    check(actor["$parent"] == REF % seed.SHOP_BASE and actor["Components"] == {
        "ASRef": "?AS/Item_Common.root.asb", "ActorNameRef": "?ActorSystem/ActorName/Obj_Thing.engine__actor__ActorName.bgyml",
        "GameParameterTableRef": "?" + TABLE % name, "ModelInfoRef": "?" + MODEL % "Item_Thing", "PouchContentRef": "?" + POUCH % "Item_Thing"},
        "the shelf actor is not the base's with the item's own name, model and place in the pouch (the item's own before what it is made from): %r" % actor)
    table = read(files[TABLE % name])
    check(table["$parent"].endswith((TABLE % seed.SHOP_BASE).replace(".bgyml", ".gyml")) and
          table["Components"] == {"PriceParam": "?" + PRICE % name, "ThingParam": "?GameParameter/Thing/Item_Thing.bgyml"},
          "the shelf actor's table is not the item's entries, the shelf base's table as its parent, and its price: %r" % table)
    check(read(files[PRICE % name]) == {"BuyingPrice": 70, "SellingPrice": 1}, "the price is not the one asked")
    check(read(files["Component/Physics/Shelf.bgyml"]) == {"Shelf": 1} and POUCH % "Item_Thing" in files and ACTOR % seed.SHOP_BASE in files and
          ACTOR % "Item_Thing" in files, "the pack is not the shelf base's files with the item's, the base's kept where both have one")
    changed = {POUCH % "Item_Thing": byml({"PouchActor": REF % "Item_Thing", "DefaultAutoGet": True}), "Component/Other.bgyml": b"x"}
    again = seed.sarc_read(seed.shop_pack("Item_Thing", item, base, sample, 70, changed)[0])
    check(read(again[POUCH % "Item_Thing"]).get("DefaultAutoGet") == 1 and "Component/Other.bgyml" not in again,
          "a pouch file a pick-up changed is not taken, or a file the pack has not is")
    for bad, why in ((seed.sarc_write({ACTOR % "Item_Other": b""}), "an item whose pack has no actor of its name"),):
        try:
            seed.shop_pack("Item_Thing", bad, base, sample, 70)
            check(False, "%s is put on a shelf" % why)
        except ValueError:
            pass

    # ---- its rows in the game's lists ----
    rows = {"ActorInfo": [{"__RowId": "Aaa"}, {"FmdbName": "Item_Thing", "InstanceHeapSize": 1000, "PreActorRenderInfoHeapSize": 500000, "__RowId": "Item_Thing"},
                          {"FmdbName": "Obj_Armor", "InstanceHeapSize": 9000, "PreActorRenderInfoHeapSize": 300, "__RowId": seed.SHOP_ROW_HEAPS}, {"__RowId": "Zzz"}],
            "GameActorInfo": [{"__RowId": "Item_Thing"}, {"MainRigidBodyLayer": "SmallObject", "__RowId": seed.SHOP_ROW}, {"__RowId": "Zzz"}],
            "PouchActorInfo": [{"PouchGetType": "Large", "__RowId": "Item_Thing"}, {"BuyingPrice": 10, "SellingPrice": 3, "__RowId": seed.SHOP_ROW}]}
    for kind in seed.SHOP_TABLES:
        once = seed.shop_rows(byml(rows[kind]), kind, "Item_Thing", 70)
        got = read(seed.shop_rows(once, kind, "Item_Thing", 80))
        ids = [r["__RowId"] for r in got]
        mine = next(r for r in got if r["__RowId"] == name)
        check(ids == sorted(ids) and ids.count(name) == 1 and len(got) == len(rows[kind]) + 1, "%s: the shelf's row is not in its place by name, once: %r" % (kind, ids))
        check([r for r in got if r["__RowId"] != name] == rows[kind], "%s: another row was changed" % kind)
        if kind == "ActorInfo":
            check(mine == {"FmdbName": "Item_Thing", "InstanceHeapSize": 9000 + 32768, "PreActorRenderInfoHeapSize": 500000 + 32768, "__RowId": name},
                  "the row is not the item's model with a shelf's heaps where they are larger: %r" % mine)
        elif kind == "GameActorInfo":
            check(mine == {"MainRigidBodyLayer": "SmallObject", "__RowId": name}, "the game's row is not a shelf's: %r" % mine)
        else:
            check(mine == {"BuyingPrice": 80, "PouchGetType": "Large", "SellingPrice": 1, "__RowId": name}, "the pouch's row is not the item's with what it costs: %r" % mine)
    try:
        seed.shop_rows(byml(rows["PouchActorInfo"]), "PouchActorInfo", "Item_NotThere", 70)
        check(False, "an item the pouch's list has not is given a row")
    except ValueError:
        pass

    # ---- a keeper's goods list ----
    goods = {"GoodsFrontOffsetPosFromCamera": 1.0, "GoodsList": [
        {"Actor": REF % "Shop_Heart", "Release": {"IsCheckReleaseGameData": True, "ReleaseGameData": "Later"}, "StockNum": 0xffffffff},
        {"Actor": REF % "Shop_DekuStick", "IsDefaultFocus": True, "PriceOffset": 5, "ConditionalPriceOffsetList": [], "StockNum": 0xffffffff},
        {"Actor": REF % "Shop_Weapon_Shield_Deku"}]}
    sold = read(seed.shop_goods(byml(goods), {1: ("Shop_DekuStick", name)}))
    check(sold["GoodsList"][1] == {"Actor": REF % name, "IsDefaultFocus": 1, "StockNum": 1} and sold["GoodsList"][0] == read(byml(goods))["GoodsList"][0] and
          sold["GoodsList"][2] == {"Actor": REF % "Shop_Weapon_Shield_Deku"} and sold["GoodsFrontOffsetPosFromCamera"] == 1.0,
          "the place does not sell the new actor once from the start, or another place changed: %r" % sold)
    first = read(seed.shop_goods(byml(goods), {0: ("Shop_Heart", name)}))["GoodsList"][0]
    check(first == {"Actor": REF % name, "StockNum": 1}, "what the game waited for before it showed the shelf is not left out: %r" % first)
    for sells, why in (({1: ("Shop_Heart", name)}, "a place that is another actor's"), ({7: ("Shop_Heart", name)}, "a place past the list")):
        try:
            seed.shop_goods(byml(goods), sells)
            check(False, "%s is changed" % why)
        except ValueError:
            pass

    # ---- a map file's shelves ----
    world = {"Actors": [{"Gyaml": "Shop_Heart", "Hash": 1}, {"Gyaml": "Shop_Heart", "Hash": 2, "Dynamic": {"ShopItemIndex": 3}},
                        {"Gyaml": "Shop_DekuStick", "Hash": 3, "Dynamic": {"ShopItemIndex": 7}}, {"Gyaml": "Npc_Keeper", "Hash": 4}]}
    new, count = seed.shelf_actors(byml(world), {("Shop_Heart", 0): name, ("Shop_DekuStick", 7): "Shop_Rando_Other", ("Shop_Heart", 5): "Shop_Rando_No"})
    got = [a["Gyaml"] for a in read(new)["Actors"]]
    check(count == 2 and got == [name, "Shop_Heart", "Shop_Rando_Other", "Npc_Keeper"], "the shelves are not found by actor and place in the row (none: the first): %r" % got)
    check(seed.shelf_actors(byml(world), {("Shop_Heart", 5): name}) == (None, 0), "a file with none of the shelves is written anew")

    # ---- the words under an item's name ----
    lines = [("Item_Thing_Name", b"Thing"), ("Item_Thing_Caption", b"A thing.\nIt does things."), ("Item_Other_Name", b"Other"),
             ("Item_Other_GetCaption", b"You got the other!"), ("Item_Sold_Name", b"Sold"), ("Item_Sold_ShopCaption", b"For sale.")]
    data = text_file(lines)
    for label, raw in lines:
        a, b = seed.msbt_text(data, label)
        check(data[a:b].rstrip(b"\0") == raw, "the made-up text file's line %s is not found" % label)
    new = seed.shop_caption(data, "Item_Thing")
    a, b = seed.msbt_text(new, "Item_Thing_ShopCaption")
    check(new[a:b] == b"A thing.\nIt does things.\0", "the words under the name are not the item's description")
    check(all(new[x:y] == data[p:q] for (x, y), (p, q) in ((seed.msbt_text(new, l), seed.msbt_text(data, l)) for l, _ in lines)), "another line was changed")
    check(struct.unpack_from("<I", new, 0x12)[0] == len(new) and len(new) % 16 == 0 and seed.shop_caption(new, "Item_Thing") is None, "the file's size is not set, or done again a line is added")
    both = seed.shop_caption(new, "Item_Other")
    a, b = seed.msbt_text(both, "Item_Other_ShopCaption")
    check(both[a:b] == b"You got the other!\0" and seed.msbt_text(both, "Item_Thing_ShopCaption"), "an item with no description is not given what is said when it is got")
    check(seed.shop_caption(data, "Item_Sold") is None and seed.shop_caption(data, "Item_Nothing") is None, "an item that has the line, or no words at all, is given one")
    check(seed.msbt_add(data, "Item_Thing_Name", b"New") == seed.msbt_set(data, "Item_Thing_Name", b"New"), "a label the file has is added again")
    extra = bytearray(data)
    extra[data.index(b"TXT2"):data.index(b"TXT2") + 4] = b"ATR1"
    try:
        seed.msbt_add(bytes(extra), "Item_New", b"x")
        check(False, "a line is added to a file with more than labels and texts")
    except ValueError:
        pass

    # ---- the script ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check('"rando_shops": 0' in script and '(" shops %d" % a.shops if a.shops else "")' in script and 'a.shops = a.shops if 0 <= a.shops <= 2 else 0' in script,
          "the script does not read the setting, or does not name it in the seed's stamp")
    check('spots[gift_hash(g.key)] = [g.area, g.item, None, None, "shop", g.name, ""]' in script and "if gives[h] != g.item and g.flow:" in script,
          "the shelves are not spots among the chests', or a shelf is taken for a scene's gift")
    check('shop_files["Pack/Actor/%s.pack.zs" % shop_actor(item)] = new' in script and 'shop_files["RSDB/" + n] = table' in script and
          "parts[name] = shop_goods(parts[name], sells)" in script and "new, count = shelf_actors(data, on_shelf)" in script and
          "text = shop_caption(text, name) or text" in script and "list(shop_files.items())" in script and
          'new_tables["System/Resource/" + n] = shop_table(' in script,
          "a shelf actor's pack, its rows, the goods lists, the map's shelves or the words are not written with the seed, or the size table does not know them")
    check('roll = random.Random("shop prices:%d" % seed) if a.shops == 2 else None' in script, "Random prices does not roll them by the seed")
    check("[(shop.areas[0], shop.place, shop.ages, needs[h], gifts[h].name) for h, (shop, _, _) in shelves.items() if h in gives]" in script,
          "the shelves are not among the tracker's checks")
    print("PASS: Shops")


if __name__ == "__main__":
    main()
