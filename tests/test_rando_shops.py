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
- a price is rolled, 1 to 750: mostly low in the one way, evenly in the other with the child's a little more often,
  the same for the same seed; and the wallet it asks for is the one that holds it (200 a child's, 500 the Adult's,
  the Giant's past that);
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
          seed.shop_actor("Item_Hammer") == "Shop_Rando_Item_Hammer" and seed.shop_actor("kokiri_3") == "Shop_Rando_kokiri_3",
          "a shelf's item for the pool, or a shelf actor's name, is not what it was")
    check(all(seed.shelf_item(actor) in seed.ITEM_WORDS for _, _, actor in slots), "what goes into the pool for a shelf has no words for the tracker")

    # ---- a price ----
    low = [seed.shop_price(random.Random(k), 1) for k in range(4000)]
    even = [seed.shop_price(random.Random(k), 2) for k in range(4000)]
    check(seed.SHOP_PRICE_MAX == 750 and all(1 <= p <= 750 for p in low + even) and max(low) > 680 and max(even) > 740 and min(low + even) == 1,
          "a price is not rolled from 1 to 750")
    share = lambda prices, most: sum(1 for p in prices if p <= most) / len(prices)
    # (within the child's wallet: more than its share of the range, 200 of 750 = 0.27, in the even way, and a little more than the cube's 0.64 in the low)
    check(0.66 < share(low, 200) < 0.76 and 0.84 < share(low, 500) < 0.94 and 0.33 < share(even, 200) < 0.43 and 0.66 < share(even, 500) < 0.76,
          "the low prices are not mostly within the child's wallet, or the others are not even with the child's a little more often: %.2f %.2f %.2f %.2f" % (
              share(low, 200), share(low, 500), share(even, 200), share(even, 500)))
    check(all(p < 10 or p % 5 == 0 for p in low) and seed.shop_price(random.Random(7), 1) == seed.shop_price(random.Random(7), 1),
          "a low price is not in fives, or the same seed rolls another")
    check([seed.wallet_need(p) for p in (1, 200, 201, 500, 501, 750)] == [seed.NONE, seed.NONE, {seed.WM}, {seed.WM}, {seed.WL}, {seed.WL}] and
          seed.SHOP_GATES == {"Item_Wallet_Medium", "Item_Wallet_Large"} and seed.WALLETS[0][0] == 200 and seed.WALLETS[1][0] == 500,
          "a price does not ask for the wallet that holds it")
    by_key = {g.key: g for g in seed.GIFTS}
    check(sorted(by_key[k].item for k in seed.SHOP_WALLET_GIFTS) == sorted(seed.SHOP_GATES), "the gifts that take part with the shops are not the two that give the wallets")

    # ---- an item's shelf actor ----
    item, base, sample = packs()
    new, own, named = seed.shop_pack("Item_Thing", item, base, sample, 70)
    files = seed.sarc_read(new)
    name = "Shop_Rando_Item_Thing"
    check(own == [ACTOR % name, TABLE % name, PRICE % name] and named == "Obj_Thing", "the shelf actor's own files, or the name its texts go by, are not given")
    actor = read(files[ACTOR % name])
    check(actor["$parent"] == REF % seed.SHOP_BASE and actor["Components"] == {
        "ActorNameRef": "?ActorSystem/ActorName/Obj_Thing.engine__actor__ActorName.bgyml",
        "GameParameterTableRef": "?" + TABLE % name, "ModelInfoRef": "?" + MODEL % "Item_Thing", "PouchContentRef": "?" + POUCH % "Item_Thing"},
        "the shelf actor is not the base's with the item's own name, model and place in the pouch (the item's own before what it is made from), "
        "or it has the item's pose, which is its \"item got\" scene's: %r" % actor)
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
    high = {"Actors": [{"Gyaml": "Shop_Heart", "Translate": [1.0, 2.0, 3.0]}, {"Gyaml": "Shop_DekuStick", "Translate": [4.0, 5.0, 6.0], "Dynamic": {"ShopItemIndex": 7}}]}
    lifted = read(seed.shelf_actors(byml(high), {("Shop_Heart", 0): name, ("Shop_DekuStick", 7): "Shop_Rando_Other"}, {name: 0.25})[0])["Actors"]
    check(lifted[0]["Translate"] == [1.0, 2.25, 3.0] and lifted[1]["Translate"] == [4.0, 5.0, 6.0], "a shelf whose item asks for it is not put higher, or another is")
    check("Item_Gauntlet_Gold" not in seed.SHELF_LIFT and seed.SHELF_SCALE["Item_Gauntlet_Gold"] == 1.0 and set(seed.SHELF_TURN) == {"Item_GlassTruth"},
          "the gauntlets have a height of their own again (their box is right without the pose), or are made smaller, or another item is turned")
    info = byml([{"ModelAabbMin": {"X": -0.2, "Y": -0.193, "Z": 0.0}, "__RowId": "Item_Token_Gold"}, {"ModelAabbMin": {"X": 0.0, "Y": 1.171, "Z": 0.0}, "__RowId": "Item_Gauntlet_Gold"},
                 {"__RowId": "Item_Bare"}])
    check(abs(seed.model_floor(info, "Item_Token_Gold") + 0.193) < 1e-6 and seed.model_floor(info, "Item_Bare") is None and seed.model_floor(info, "Item_None") is None,
          "the lowest of a model's box is not read from the list of actors")
    # (how an item stands: by its box, lowered when made where it is worn, long ones made smaller, its own numbers first)
    box = lambda low, high: ((0.0, low, 0.0), (0.1, high, 0.1))
    check(seed.shelf_fit("Item_Thing", None) == (0.0, 1.0) and seed.shelf_fit("Item_Token_Gold", ((-0.19, -0.193, -0.01), (0.17, 0.19, 0.02))) == (0.19, 1.0) and
          seed.shelf_fit("Item_Gauntlet_Gold", ((-0.8, 1.171, -0.11), (0.8, 1.33, 0.05))) == (-1.17, 1.0) and
          seed.shelf_fit("Item_Hammer", ((-0.45, -0.28, -0.33), (0.22, 0.28, 1.45))) == (0.14, 0.51) and
          seed.shelf_fit("Item_Dungeon_SmallKey", box(0.0, 0.56)) == (0.0, 0.6) and seed.shelf_fit("Item_Arrow_Light", box(-0.38, 0.3)) == (0.1, 1.0) and
          seed.shelf_fit("Item_GlassTruth", box(0.92, 1.04)) == (0.15, 2.0) and seed.shelf_fit("Item_Thing", box(0.0, 1.0))[1] == 1.0,
          "an item is not put and sized on its shelf by its box and its own numbers: %r" % (seed.shelf_fit("Item_Hammer", ((-0.45, -0.28, -0.33), (0.22, 0.28, 1.45))),))
    full = byml([{"ModelAabbMin": {"X": -0.2, "Y": -0.19, "Z": 0.0}, "ModelAabbMax": {"X": 0.2, "Y": 0.2, "Z": 0.1}, "__RowId": "Item_Token_Gold"}, {"__RowId": "Item_Bare"}])
    got = seed.model_box(full, "Item_Token_Gold")
    check(got and [round(v, 2) for v in got[0] + got[1]] == [-0.2, -0.19, 0.0, 0.2, 0.2, 0.1] and seed.model_box(full, "Item_Bare") is None and seed.model_box(full, "Item_None") is None,
          "a model's box is not read from the list of actors")
    # (its size and its turn in the map file; the board of how many a bundle holds beside it out of sight, and no other)
    shop = {"Actors": [{"Gyaml": "Shop_Heart", "Translate": [1.0, 2.0, 3.0], "Rotate": [0.0, 1.0, 0.0]},
                       {"Gyaml": "Shop_Board_Bundle_10", "Translate": [1.2, 1.9, 3.3]}, {"Gyaml": "Shop_Board_Bundle_05", "Translate": [4.0, 2.0, 3.0]},
                       {"Gyaml": "Shop_Board_SoldOut", "Translate": [1.1, 2.0, 3.1]}]}
    done = read(seed.shelf_actors(byml(shop), {("Shop_Heart", 0): name}, {name: 0.5}, {name: 0.5}, {name: (-1.5, 0.0, 0.25)})[0])["Actors"]
    check(done[0]["Scale"] == [0.5, 0.5, 0.5] and done[0]["Rotate"] == [-1.5, 1.0, 0.25] and done[0]["Translate"] == [1.0, 2.5, 3.0],
          "a shelf's item is not made its size, turned and put higher in the map file: %r" % (done[0],))
    check(done[1]["Translate"][1] < -1000 and done[2]["Translate"] == [4.0, 2.0, 3.0] and [round(v, 2) for v in done[3]["Translate"]] == [1.1, 2.0, 3.1],
          "the board of how many beside a shuffled shelf is still in sight, or another shelf's board or a sold-out board is not")
    plain = read(seed.shelf_actors(byml(shop), {("Shop_Heart", 0): name})[0])["Actors"]
    check("Scale" not in plain[0] and plain[0]["Rotate"] == [0.0, 1.0, 0.0], "an item of its own size is given a size, or one not turned a turn")
    check(seed.shelf_lift("Item_Token_Gold", -0.193) == 0.19 and seed.shelf_lift("Item_Gauntlet_Gold", 1.171) == 0.0 and seed.shelf_lift("Item_Thing", 0.01) == 0.0 and
          seed.shelf_lift("Item_Thing", None) == 0.0 and seed.shelf_lift("Item_Thing", -0.9) == 0.0 and seed.shelf_lift("Item_Thing", -0.276) == 0.28,
          "a shelf is not put as high as its item's model reaches under its origin, or one whose model is made elsewhere is")

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
    check('"rando_shops": 0' in script and '(" shops %d prices 5" % a.shops if a.shops else "")' in script and 'a.shops = a.shops if 0 <= a.shops <= 2 else 0' in script,
          "the script does not read the setting, or does not name it in the seed's stamp")
    check('spots[gift_hash(g.key)] = [g.area, g.item, None, None, "shop", g.name, ""]' in script and "if gives[h] != g.item and g.flow and h not in lessons:" in script,
          "the shelves are not spots among the chests', or a shelf is taken for a scene's gift")
    check('shop_files["Pack/Actor/%s.pack.zs" % actor] = new' in script and 'shop_files["RSDB/" + n] = table' in script and
          "parts[name] = shop_goods(parts[name], sells)" in script and "new, count = shelf_actors(data, on_shelf, lifts, scales, turns)" in script and
          "text = shop_caption(text, name) or text" in script and "list(shop_files.items())" in script and
          'new_tables["System/Resource/" + n] = shop_table(' in script,
          "a shelf actor's pack, its rows, the goods lists, the map's shelves or the words are not written with the seed, or the size table does not know them")
    check('roll = random.Random("shop prices:%d:%d" % (seed, a.shops))' in script and "price = shop_price(roll, a.shops)" in script and
          "shop.need | wallet_need(price), \"shops\", None)" in script and "PROGRESSION = PROGRESSION | SHOP_GATES" in script and
          "if g.key in SHOP_WALLET_GIFTS and gift_hash(g.key) not in gifts:" in script and "(tuple(SHOP_GATES) if a.shops else ())" in script,
          "the prices are not rolled by the seed, a shelf does not ask for its price's wallet, or the wallets are not shuffled as gating items kept from the Skulltulas")
    check('on_sale = collections.OrderedDict((shop_actor("%s_%d" % (shop.key, index)), (gives[h], shelf_prices[h]))' in script and
          "table = shop_rows(table, kind, item, price, actor)" in script, "a shelf has not an actor of its own, with its own price")
    check("[(shop.areas[0], shop.place, shop.ages, needs[h], gifts[h].name, None, gives[h])" in script and "for h, (shop, _, _) in shelves.items() if h in gives]" in script,
          "the shelves are not among the tracker's checks")
    # ---- the Bombchu Shop: young Link's, at night, once Dodongo's Cavern is done (the door's own condition) ----
    chu = next(shop for shop in seed.SHOPS if shop.key == "bombchu")
    check(chu.ages == "C" and chu.need == seed.DODONGO_DONE == seed.RULES["DodongoCavern"][0] and seed.BB in chu.need,
          "the Bombchu Shop's shelves do not ask for what Dodongo's Cavern asks for, or are an adult's")
    check("night" in chu.name and "Dodongo" in chu.name, "the Bombchu Shop's name does not tell the tracker when its door opens")
    print("PASS: Shops")


if __name__ == "__main__":
    main()
