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
    check(len(seed.SHOPS) == 8 and all(len(shop.slots) == 4 for shop in seed.SHOPS) and len({shop.key for shop in seed.SHOPS}) == 8,
          "the shops are not eight of four shelves each")
    # (placement 11, SHOP_TOWNS: Kakariko's Bazaar and Potion Shop are the adult's, apart from the Market's; a seed made
    #  before has the six shops it had, the two of them in both towns, so that it keeps its items and its shelves' flags)
    by_key = {shop.key: shop for shop in seed.SHOPS}
    old = seed.shops(seed.SHOP_TOWNS - 1)
    check(seed.SHOP_TOWNS == 11 and seed.PLACEMENT >= 11 and seed.shops() == seed.SHOPS and [shop.key for shop in old] ==
          ["kokiri", "general", "medicine", "bombchu", "goron", "zora"] and old[1].areas == old[2].areas == ("Market", "KakarikoVillage") and
          old[1].params == ("Npc_Hylia_018_Shop", "Npc_Hylia_018_Shop_Adult") and old[1].ages == old[2].ages == "C" and
          by_key["general"].areas == by_key["medicine"].areas == ("Market",) and by_key["general"].params == ("Npc_Hylia_018_Shop",) and
          by_key["kgeneral"].areas == by_key["kmedicine"].areas == ("KakarikoVillage",) and by_key["kgeneral"].ages == by_key["kmedicine"].ages == "A" and
          by_key["kgeneral"].params == ("Npc_Hylia_018_Shop_Adult",) and by_key["kmedicine"].params == (seed.POTION_ADULT,) and
          by_key["kgeneral"].slots == by_key["general"].slots and by_key["kmedicine"].slots == by_key["medicine"].slots and
          by_key["kgeneral"].need == by_key["kmedicine"].need == seed.ADULT and
          all(len(seed.shop_actor("%s_%d_%d" % (key, 7, 2))) <= 25 for key in by_key),
          "Kakariko's shops are not the adult's own from placement 11, or a seed made before does not keep its six shops")
    # (the adult Potion Shop keeper's goods list of his own: a copy of the child's in his pack, and his actor naming it)
    goods_child = seed.byml_build(("dict", collections.OrderedDict((("GoodsList", ("array", [])),))), 7)
    actor = seed.byml_build(("dict", collections.OrderedDict((("$parent", ("string", "Work/Actor/Npc_Hylia_020_Shop_Child.engine__actor__ActorParam.gyml")),
                                                             ("Components", ("dict", collections.OrderedDict((("AIScheduleRef", ("string", "?x")),))))))), 7)
    made, mine, actor_file = seed.potion_adult(seed.sarc_write({seed.SHOP_PARAM % "Npc_Hylia_020_Shop": goods_child,
                                                                seed.ACTOR_FILE % seed.POTION_KEEPER: actor}))
    parts = seed.sarc_read(made)
    comps = seed.byml_parse(parts[actor_file])[0][1]["Components"][1]
    check(mine == seed.SHOP_PARAM % seed.POTION_ADULT and bytes(parts[mine]) == goods_child and comps["ShopRef"] == ("string", "?" + mine) and
          comps["AIScheduleRef"] == ("string", "?x") and "potion_adult(pack(POTION_KEEPER))" in (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8"),
          "the adult Potion Shop keeper is not given a goods list of his own")
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
    # (within the child's wallet: more than its share of the range, 200 of 750 = 0.27, in the even way; in the low
    #  way most, by the square of an even roll, and not the cube: one shelf in eight cost 1 rupee, seen in play)
    check(seed.SHOP_LOW_POWER == 2 and sum(1 for p in low if p == 1) / len(low) < 0.06,
          "the low prices pile up at 1 rupee again (%.3f of them)" % (sum(1 for p in low if p == 1) / len(low)))
    check(0.55 < share(low, 200) < 0.66 and 0.80 < share(low, 500) < 0.90 and 0.33 < share(even, 200) < 0.43 and 0.66 < share(even, 500) < 0.76,
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
    # (a shield's model file is the shelf's own, under the shelf's name: the shield's own name stays the cosmetics')
    check(seed.SHELF_OWN_MODEL == ("Weapon_Shield_Deku", "Weapon_Shield_Hylian", "Weapon_Shield_Mirror") and "Item_Thing" not in seed.SHELF_OWN_MODEL,
          "the shields whose model file a shelf keeps for itself are not the three")
    kept = seed.SHELF_OWN_MODEL
    seed.SHELF_OWN_MODEL = kept + ("Item_Thing",)
    try:
        mine = seed.sarc_read(seed.shop_pack("Item_Thing", item, base, sample, 70)[0])
    finally:
        seed.SHELF_OWN_MODEL = kept
    check(MODEL % "Item_Thing" not in mine and mine.get(seed.MODEL_INFO_FILE % name) == files[MODEL % "Item_Thing"] and
          read(mine[ACTOR % name])["Components"]["ModelInfoRef"] == "?" + seed.MODEL_INFO_FILE % name,
          "a shield's model file on a shelf is not the shelf's own, under its name, or the shelf's actor does not name it")
    check(seed.MODEL_INFO_FILE % "x" == MODEL % "x", "the shelf's own model file is not where a model file is")
    # (the Potion Shop keeper's bottle: a gift from placement 9, his errand of the bug passed over in every seed)
    potion = {g.key: g for g in seed.GIFTS}.get("potion_bottle")
    check(potion is not None and potion.flow == "Npc_Hylia_020_Shop_Child" and potion.olds == ("Item_Bottle",) and potion.area == "Market" and
          seed.GIFTS_FROM.get("potion_bottle") == 9 <= seed.PLACEMENT and "potion_bottle" in seed.GIFT_PLACES and
          seed.POTION_FLOW == "Event/EventFlow/Npc_Hylia_020_Shop_Child.bfevfl.zs",
          "the Potion Shop keeper's bottle is not a gift of the shuffle from placement 9, or has no place on the Tracker tab")
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("gift_files[POTION_FLOW] = potion_errand_skip(was)" in script and "if g.key in GIFTS_FROM and placement < GIFTS_FROM[g.key]:" in script,
          "the keeper's errand is not passed over in the seed's flows, or a gift added later changes the seeds made before")
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
    # ---- a shelf that sold its item stays sold: it waits for a flag of its own, which the game's side keeps ----
    # (reported from play: a shelf was for sale again after the Sun's Song. Seen without a window: a shelf whose flag
    #  is false is not there, and the shop is as it was)
    kept = read(seed.shop_goods(byml(goods), {0: ("Shop_Heart", name), 1: ("Shop_DekuStick", name)}, {0: "IsGet.Pouch_Amiibo"}))["GoodsList"]
    check(kept[0] == {"Actor": REF % name, "StockNum": 1, "Release": {"IsCheckReleaseGameData": 1, "ReleaseGameData": "IsGet.Pouch_Amiibo"}} and
          kept[1] == {"Actor": REF % name, "IsDefaultFocus": 1, "StockNum": 1},
          "a shelf does not wait for its flag, or one without a flag waits for something: %r" % kept[:2])
    for every, shield, count, placement in ((False, False, 24, 10), (False, True, 25, 10), (True, True, 48, 10), (True, False, 47, 10),
                                            (False, False, 32, 11), (False, True, 33, 11), (True, True, 64, 11), (True, False, 63, 11)):
        flags = seed.shelf_flags(count, every, shield, placement)
        check(len(flags) == count == len(set(flags)) and all(f.startswith(seed.SHELF_FLAG_WORDS) for f in flags),
              "the shelves' flags are not one each (%d shelves, every %r, the shield's %r)" % (count, every, shield))
        # (a flag of a shelf actor the seed still sells is the game's to set: not one of them)
        still = {actor for shop in seed.shops(placement) for index, actor in list(shop.slots) + list(shop.rest) + ([seed.SHIELD_SHELF[1:]] if shop.key == "kokiri" else [])
                 if (index, actor) not in seed.shop_slots(shop, every, shield)}
        check(placement >= 11 or flags == seed.shelf_flags(count, every, shield, 10)[:count], "a seed made before has other shelves' flags")
        check(not any(f.split(".", 1)[1] in still for f in flags), "a shelf waits for the flag of an actor the seed still sells: %r" % sorted(still))
    check(seed.shelf_flags(3)[0] == "HavePlayedGetEvent.Armor_Child_Mask_Amiibo0" and seed.shelf_flags(48, True, True)[-1].startswith("IsGet."),
          "the flags are not the never got actors' first, the scene's flag before the item's")
    try:
        seed.shelf_flags(200, True, True)
        check(False, "more shelves than flags is not an error")
    except ValueError:
        pass
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
    check("Item_Gauntlet_Gold" not in seed.SHELF_LIFT and seed.SHELF_SCALE["Item_Gauntlet_Gold"] == 1.0 and seed.SHELF_SCALE["Item_Gauntlet_Goron"] == 1.5 and seed.SHELF_TURN["TBox_ArrowBundle_Small"] == (0.0, 1.57, 0.0) and seed.SHELF_LIFT["TBox_ArrowBundle_Small"] == 0.2 and
          set(seed.SHELF_TURN) == {"TBox_ArrowBundle_Small", "Item_Range_Bow", "Item_Range_SlingShot", "Item_Sword_Kokiri", "Item_Shield_Mirror", "TBox_Shield_Deku", "TBox_Shield_Hylian"} | set(seed.SONG_ITEMS) and
          all(seed.SHELF_TURN[song] == (0.0, 0.0, 0.0) and seed.SHELF_LIFT[song] == 0.3 for song in seed.SONG_ITEMS),
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
          seed.shelf_fit("Item_GlassTruth", box(0.92, 1.04)) == (-0.67, 1.0) and seed.shelf_fit("Item_Thing", box(0.0, 1.0))[1] == 1.0,
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
    # (the name keeps its capitals in a keeper's line: a tag before each capital word, the game's own tags kept whole)
    cap = seed.NAME_CAP
    named = text_file([("Item_Song_Name", b"\x0e\xc9\x00\x00\x00\x04\x00\x00\x00\xff\x01Saria's Song"), ("Item_Kept_Name", cap + b"Deku " + cap + b"Shield"),
                       ("Item_Low_Name", b"bomb"), ("Item_Milk_Name", b"Half-Full Milk")])
    song = seed.shop_name_caps(named, "Item_Song")
    a, b = seed.msbt_text(song, "Item_Song_Name")
    check(song[a:b] == b"\x0e\xc9\x00\x00\x00\x04\x00\x00\x00\xff\x01" + cap + b"Saria's " + cap + b"Song\0", "a name's words are not each given the capital's tag, or its own tag is broken")
    milk = seed.shop_name_caps(named, "Item_Milk")
    a, b = seed.msbt_text(milk, "Item_Milk_Name")
    check(milk[a:b] == cap + b"Half-" + cap + b"Full " + cap + b"Milk\0", "a word after a hyphen keeps no capital")
    check(seed.shop_name_caps(named, "Item_Kept") is None and seed.shop_name_caps(named, "Item_Low") is None and seed.shop_name_caps(named, "Item_None") is None,
          "a name already tagged, one with no capitals or none at all is changed")
    script_now = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    check("caps = n.startswith(SHOP_NAME_CAPS) and shop_caption(text, name) is not None" in script_now and "text = shop_name_caps(text, name) or text" in script_now,
          "the names of what the game never sells are not given their capitals in English")
    extra = bytearray(data)
    extra[data.index(b"TXT2"):data.index(b"TXT2") + 4] = b"ATR1"
    try:
        seed.msbt_add(bytes(extra), "Item_New", b"x")
        check(False, "a line is added to a file with more than labels and texts")
    except ValueError:
        pass

    # ---- the script ----
    script = (ROOT / "tools" / "rando" / "rando_seed.py").read_text(encoding="utf-8")
    host = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    check('"rando_shops": 0' in script and '(" shops %d prices 5" % a.shops if a.shops else "")' in script and 'a.shops = a.shops if 0 <= a.shops <= 2 else 0' in script,
          "the script does not read the setting, or does not name it in the seed's stamp")
    check('spots[gift_hash(g.key)] = [g.area, g.item, None, None, "shop", g.name, ""]' in script and "if gives[h] != g.item and g.flow and h not in lessons:" in script,
          "the shelves are not spots among the chests', or a shelf is taken for a scene's gift")
    check('shop_files["Pack/Actor/%s.pack.zs" % actor] = new' in script and 'shop_files["RSDB/" + n] = table' in script and
          "parts[name] = shop_goods(parts[name], sells, shown)" in script and
          "shown = {index: shelf_flag[h] for h, (its, index, _) in shelves.items() if its is shop}" in script and
          "more = flag_defaults(new if new is not None else was, shelf_start) if shelf_start else None" in script and
          'with open(os.path.join(mod, SHELF_FLAGS), "w", encoding="utf-8", newline="\\n") as f:' in script and
          "static int oot_shelf_flags(Ctx *c) {" in host and "if (oot_checks[best].shelf || oot_checks[best].key) oot_checks[best].sold = 1;" in host and
          # (the flag is the save's and says what was bought; the record is the folder's and follows it)
          "if (now && oot_gamedata_set_bool(c, oot_checks[i].shelf, 0)) changed++;" in host and "oot_checks[i].done = !now;" in host and
          # (a flag written where it is was not in the next save: the game's own setter is called)
          "A64Fn set = a64_lookup(0x806a2b20ULL);" in host and "c->x[0] = mgr, c->x[1] = value ? 1 : 0, c->x[2] = hash;" in host and
          "const int want = oot_checks[i].done != 1;" not in host and
          'oot_game_file(path, sizeof path, "mods/rando-seed/shelf_flags.txt")' in host and "const int changed = oot_shelf_flags(c);" in host and
          "const char *tail = oot_checks[i].shelf && oot_checks[i].done != 1 ? strchr(oot_checks[i].item, '_') : NULL;" in host and "new, count = shelf_actors(data, on_shelf, lifts, scales, turns)" in script and
          "text = shop_caption(text, name) or text" in script and "list(shop_files.items())" in script and
          'new_tables["System/Resource/" + n] = shop_table(' in script,
          "a shelf actor's pack, its rows, the goods lists, the map's shelves or the words are not written with the seed, or the size table does not know them")
    check('roll = random.Random("shop prices:%d:%d" % (seed, a.shops))' in script and "price = shop_price(roll, a.shops)" in script and
          "shop_need(shop, placement, a.open_forest) | wallet_need(price), \"shops\", None)" in script and "PROGRESSION = PROGRESSION | SHOP_GATES" in script and
          "if g.key in SHOP_WALLET_GIFTS and gift_hash(g.key) not in gifts:" in script and "(tuple(SHOP_GATES) if a.shops else ())" in script,
          "the prices are not rolled by the seed, a shelf does not ask for its price's wallet, or the wallets are not shuffled as gating items kept from the Skulltulas")
    check('on_sale = collections.OrderedDict((shop_actor("%s_%d" % (shop.key, index)), (gives[h], shelf_prices[h]))' in script and
          "table = shop_rows(table, kind, item, price, actor)" in script, "a shelf has not an actor of its own, with its own price")
    check("[(shop.areas[0], shop.place, shop.ages, needs[h], gifts[h].name, None, gives[h])" in script and "for h, (shop, _, _) in shelves.items() if h in gives]" in script,
          "the shelves are not among the tracker's checks")
    # ---- Every shop shelf, and Shuffle sword and shield: which shelves take part ----
    for shop in seed.SHOPS:
        every = seed.shop_slots(shop, True, True)
        check(seed.shop_slots(shop) == list(shop.slots) and every[:4] == list(shop.slots),
              "%s: its four shelves are not the ones that take part with the settings off, or are not first (a shelf's number is its place)" % shop.key)
        check(sorted(index for index, _ in every) == list(range(8)) and len({actor for _, actor in every} | {""}) > 1,
              "%s: every shelf is not its eight places, each once: %r" % (shop.key, every))
        check(all(seed.shelf_item(actor) in seed.ITEM_WORDS for _, actor in every), "%s: what a shelf puts in the pool has no words for the tracker" % shop.key)
    kokiri = next(shop for shop in seed.SHOPS if shop.key == "kokiri")
    shield = seed.SHIELD_SHELF[1:]
    check(seed.SHIELD_SHELF == ("kokiri", 6, "Shop_Weapon_Shield_Deku") and shield not in seed.shop_slots(kokiri, True, False) and
          shield in seed.shop_slots(kokiri, False, True) and len(seed.shop_slots(kokiri, False, True)) == 5 and
          not any("Shield_Deku" in actor for shop in seed.SHOPS for _, actor in shop.slots + shop.rest),
          "the Deku Shield's shelf is not its own setting's: in with Shuffle sword and shield alone, out with Every shop shelf alone")
    check(seed.shelf_item("Shop_Weapon_Shield_Deku") == seed.DS == "TBox_Shield_Deku" and seed.shelf_item("Shop_Weapon_Shield_Hylian") == "TBox_Shield_Hylian" and
          seed.shelf_item("Shop_Armor_Goron") == seed.SHELF_OTHER and seed.shelf_item("Shop_Bottle_RedPotion") == seed.SHELF_OTHER,
          "a shield's shelf does not put the chests' shield in the pool, or a tunic's or a potion's something other than a red rupee")
    # (Mido lets Link by with a sword and a shield: with the shield's shelf shuffled, every rule that names the sword names the shield)
    check(seed.shield_need(seed.CHILD) == seed.CHILD | {seed.DS} and seed.shield_need(seed.NONE) == seed.NONE and
          seed.shield_need(frozenset((seed.BB,))) == frozenset((seed.BB,)) and seed.SHIELD_GATES == {seed.DS},
          "the shield is not asked for wherever the sword is, or where it is not")
    check("gear = shield_need if shield_shelf and not a.open_deku else (lambda need: need)" in script and
          "PROGRESSION = PROGRESSION | SHIELD_GATES" in script and
          "step = (lambda need: progressive_need(gear(need), PROGRESSION)) if a.progressive else gear" in script,
          "the shield is not a gating item when its shelf is shuffled, or is asked for with Open Deku Tree on")
    check('if c.event == SWORD_EVENT and not a.sword_shield:' in script and
          'a.shop_shelves = (a.shop_shelves if a.shop_shelves is not None else ini["rando_shop_shelves"]) == 1 and a.shops != 0' in script and
          "shield_shelf = a.sword_shield and a.shops != 0" in script and
          "for k, (index, actor) in enumerate(shop_slots(shop, a.shop_shelves, shield_shelf)):" in script and
          "for index, actor in shop_slots(shop, a.shop_shelves, shield_shelf)}" in script,
          "the two settings do not reach the sword's chest, the shelves priced or the shelves written")
    # (named in the stamp only when set: a seed made before the settings keeps its stamp, and is not made again)
    check('(" shelves all" if a.shop_shelves else "") + (" sword and shield 1" if a.sword_shield else "")' in script,
          "the two settings are not in the seed's stamp, or are named when off")
    # ---- Bombchus: a limit of their own, not the Bomb Bag's (found before a bag they were lost: seen in play) ----
    pouch = byml([{"__RowId": "Item_Bomb", "MaxNumGameData": "Bomb", "SmallBagActor": "Work/Actor/Item_BombBag_Small.engine__actor__ActorParam.gyml"},
                  {"__RowId": "Item_Bombchu", "MaxNumGameData": "Bomb", "PouchStockable": True, "SmallBagActor": "Work/Actor/Item_BombBag_Small.engine__actor__ActorParam.gyml"},
                  {"__RowId": "Item_MagicBean", "FixedMaxNum": 10}])
    now = seed.chu_limit(pouch)
    rows = {r["__RowId"]: r for r in read(now)}
    check(rows["Item_Bombchu"] == {"__RowId": "Item_Bombchu", "FixedMaxNum": seed.BOMBCHU_LIMIT, "PouchStockable": True} and seed.BOMBCHU_LIMIT == 50,
          "the Bombchus' row is not given a limit of its own, or still names the Bomb Bag: %r" % (rows["Item_Bombchu"],))
    check(rows["Item_Bomb"]["MaxNumGameData"] == "Bomb" and "SmallBagActor" in rows["Item_Bomb"] and rows["Item_MagicBean"] == {"__RowId": "Item_MagicBean", "FixedMaxNum": 10},
          "the bombs no longer ask for the Bomb Bag (the rules' gating item), or another row changed")
    check(seed.chu_limit(now) == now, "a list already changed is changed again")
    for bad in (byml([{"__RowId": "Item_Bomb"}]), byml([{"__RowId": "Item_Bombchu", "MaxNumGameData": "Other", "SmallBagActor": "x"}])):
        try:
            seed.chu_limit(bad)
            check(False, "a list that is not as the game's is changed all the same")
        except ValueError:
            pass
    check("table = chu_limit(shop_files[rel] if rel in shop_files else unpack(open(os.path.join(folder, n), \"rb\").read(), zs, dicts))" in script and
          script.index("# ---- Bombchus: a limit of their own, in every seed") > script.index("print(\"Shops (%s): %d shelves of %d shops take part"),
          "the Bombchus' limit is not written in every seed, over the shops' own rows of the same list")
    # ---- the Bombchu Shop: young Link's, at night, once Dodongo's Cavern is done (the door's own condition) ----
    chu = next(shop for shop in seed.SHOPS if shop.key == "bombchu")
    check(chu.ages == "C" and chu.need == seed.DODONGO_DONE == seed.RULES["DodongoCavern"][0] and seed.BB in chu.need,
          "the Bombchu Shop's shelves do not ask for what Dodongo's Cavern asks for, or are an adult's")
    check("night" in chu.name and "Dodongo" in chu.name, "the Bombchu Shop's name does not tell the tracker when its door opens")
    # (placement 4, asked for by the game's owner: with Open forest exit the Market's shops ask for nothing, a shelf
    #  under the child's wallet can be had from the start; the Bombchu Shop asks for a child, its door open at night)
    by = {shop.key: shop for shop in seed.SHOPS}
    check(seed.PLACEMENT >= 4 and all(seed.shop_need(by[k], 4, True) == seed.NONE for k in ("general", "medicine", "bombchu", "kokiri")) and
          seed.shop_need(by["bombchu"], 4, False) == seed.CHILD and seed.shop_need(by["goron"], 4, True) == by["goron"].need and
          seed.shop_need(by["zora"], 4, True) == seed.CHILD_BOMBS == next(g for g in seed.GIFTS if g.key == "diving").need and all(seed.shop_need(shop, 3, True) == shop.need for shop in seed.SHOPS) and
          seed.wallet_need(199) == seed.NONE and "shop_need(shop, placement, a.open_forest) | wallet_need(price)" in script,
          "a Market shop's shelf under the child's wallet cannot be had from the start with Open forest exit, or a seed made before changes")
    # ---- the Bombchu Shop's door open at night from the start: its two AND nodes made OR, nothing else ----
    names = [b"OperateAND", b"HoldGameDataGetBoolExpSimple", b"HoldWmGetTimeDiv", b"Obj_Door", b"OperateAND", b"OperateOR",
             b"ActorLogicSimpleActor", b"OperateInvertBool"]
    pool_at = 0x74 + 0x3C * 8
    strings, places = b"", []
    for n in names + [b"Get_StoneOfFire_IsCompleted_Exp"]:
        places.append(len(strings)); strings += n + bytes(1)
    fake = bytearray(pool_at) + strings
    fake[:4] = b"AIB "
    struct.pack_into("<I", fake, 4, 0x408); struct.pack_into("<I", fake, 0x10, 8); struct.pack_into("<I", fake, 0x24, pool_at)
    hashes = {b"OperateAND": 0x2eed4fe3, b"OperateOR": 0x24e01179}
    for i, n in enumerate(names):
        struct.pack_into("<II", fake, 0x74 + 0x3C * i + 8, places[i], hashes.get(n, i))
    opened = seed.bombchu_door_open(bytes(fake))
    name_of = lambda d, i: d[pool_at + struct.unpack_from("<I", d, 0x74 + 0x3C * i + 8)[0]:].split(bytes(1))[0]
    check(len(opened) == len(fake) and [name_of(opened, i) for i in range(8)] == [b"OperateOR"] + names[1:4] + [b"OperateOR"] + names[5:] and
          all(struct.unpack_from("<I", opened, 0x74 + 0x3C * i + 12)[0] == 0x24e01179 for i in (0, 4)) and
          sum(a != b for a, b in zip(opened, fake)) <= 16,
          "the Bombchu Shop's door is not opened by its two AND nodes made OR, or more than that is changed")
    try:
        seed.bombchu_door_open(bytes(fake[:0x74 + 0x3C * 4]) + bytes(len(fake) - 0x74 - 0x3C * 4))
        check(False, "a file that is not the door's logic is changed as if it were")
    except ValueError:
        pass
    check('flag_files[BOMBCHU_DOOR_LOGIC] = bombchu_door_open(' in script, "the Bombchu Shop's door is not opened in every seed")
    # (the keeper, the music and the sign the child's Market makes by the quest: seen in play, the door open and no keeper)
    check(seed.BOMBCHU_ACTORS == ("Npc_Hylia_021_Shop_Child", "BGM_Shop_Market_Bombchu") and seed.BOMBCHU_SIGN == "Land_HrlCity_ShopSign_A_01" and
          "new, count = bombchu_presence(data)" in script and "if chu_done != 3:" in script,
          "the Bombchu Shop's keeper is not there from the start, or its sign stays")
    # ---- placement 5: rules with alternatives; Zora's Domain by the river or the lake; Open forest exit ----
    E = seed.Either
    river = seed.song_need(seed.CHILD_BOMBS, "ZoraDomain")
    ways = seed.zora_ways(river, "ZoraDomain")
    check(seed.PLACEMENT >= 5 and isinstance(ways, E) and set(ways) == {river, seed.CHILD | {seed.SSC}} and
          seed.zora_ways(seed.CHILD_BOMBS, "KakarikoVillage") == seed.CHILD_BOMBS and seed.zora_ways(seed.ADULT, "ZoraDomain") == seed.ADULT,
          "a child's place in Zora's Domain is not had by the river or by the lake, or another rule is changed")
    opened = seed.each(seed.forest_open, ways)
    check(set(opened) == {frozenset({seed.BB, seed.ZL}), frozenset({seed.SSC})} and seed.forest_open(seed.ADULT) == seed.ADULT and
          seed.forest_open(seed.CHILD) == seed.NONE and seed.forest_open(frozenset({seed.S})) == frozenset({seed.S}),
          "Open forest exit does not take the forest's way out from a child's rules, or takes it from an adult's")
    check(seed.met(opened, {seed.SSC}) and seed.met(opened, {seed.BB, seed.ZL}) and not seed.met(opened, {seed.BB}) and
          seed.met(seed.CHILD, {seed.S, seed.SL}) and not seed.met(seed.CHILD, {seed.S}) and seed.either([seed.CHILD, seed.NONE]) == seed.NONE and
          seed.either([seed.CHILD, seed.CHILD]) == seed.CHILD and seed.collect([(E([{seed.BB}, {seed.HAM}]), seed.BOW), (seed.NONE, seed.HAM)])[-1] == [seed.BOW],
          "a rule with ways is not got by any one of them, or not as a plain rule otherwise")
    check("if placement >= 5:   # (Zora's Domain by the river or by the lake, zora_ways)" in script and
          "needs = {h: n if h in story else forest(n, spots[h][0]) for h, n in needs.items()}" in script and "met(needs[h], have)" in script and
          seed.forest_open(seed.CHILD, "DodongoCavern") == frozenset({seed.BB}) and seed.forest_open(seed.CHILD | {seed.BB}, "DodongoCavern") == frozenset({seed.BB}) and
          '"/".join(",".join([code for item, code in CHECK_CODES.items() if item in way] + token_codes(way))' in script,
          "the rules' ways are not made, read by the placement, or written for the tracker")
    check(seed.PLACEMENT >= 6 and set(seed.DEKU_STORY) == {"song_zelda", "song_saria"} and
          "story = ({h for h, g in gifts.items() if g.key in DEKU_STORY} if placement >= 6 else set()) | slingshot_room" in script and
          all('Gift("%s", ' % k in script for k in seed.DEKU_STORY),
          "Impa's and Saria's lessons do not keep the Deku Tree done with Open forest exit (DEKU_STORY)")
    check(seed.PLACEMENT >= 7 and seed.SLINGSHOT_ROOM == (0x0b66198d17d6584e, 0xb4ca60d52ca4d05f) and
          "needs = {h: n | CHILD if h in slingshot_room else n for h, n in needs.items()}" in script and
          "| slingshot_room" in script,
          "the Deku Tree's Slingshot room's chests do not ask for the Slingshot, with Open forest exit too (SLINGSHOT_ROOM)")
    check(seed.PLACEMENT >= 8 and "skull_door = skull_door if placement >= 8 else door" in script and
          "skull_asks = lambda h, at=None: (lambda area: skull_door(step(" in script,
          "Open forest exit still lightens the Gold Skulltulas' rules in new seeds (a Deku Tree Skulltula could hold the sword)")
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    check("const int held = tracker_way_held(way, strcspn(way, \"/\"), &left);" in menu and "if (held) return 1;" in menu,
          "the menu's tracker does not take a check with one of its rule's ways held as in logic")
    print("PASS: Shops")


if __name__ == "__main__":
    main()
