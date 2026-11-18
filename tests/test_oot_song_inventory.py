"""Learned songs in the debug inventory use saved IsGet flags, not pouch quantities.

Compile the real host helpers with fake GameData and pouch calls. A learned song
with no pouch entry must show Unlocked; toggling it changes only its own flag.
No game, save or GPU is needed.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


FIXTURE = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include "gpu/vk/oot_cheat_items.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
struct Ctx {};
static std::map<std::string, int> pouch;
static std::map<uint32_t, int> flags;
static int pouch_reads, pouch_writes, flag_writes;
static bool reject_flag_write;
static void hos_log(const char *, ...) {}
static int oot_pouch_count(Ctx *, const char *name) { ++pouch_reads; return pouch[name]; }
static int oot_pouch_change(Ctx *, const char *name, int delta) { ++pouch_writes; pouch[name] += delta; return 2; }
static int oot_gamedata_bool(Ctx *, uint32_t hash, int *value) {
    const auto i = flags.find(hash);
    if (i == flags.end()) return 0;
    *value = i->second;
    return 1;
}
static int oot_gamedata_set_bool(Ctx *, uint32_t hash, int value) {
    const auto i = flags.find(hash);
    if (i == flags.end() || reject_flag_write) return 0;
    i->second = value;
    ++flag_writes;
    return 1;
}
static uint32_t rotate(uint32_t x, int n) { return x << n | x >> (32 - n); }
static uint32_t flag_hash(const std::string& name) {
    const std::string s = "IsGet." + name;
    uint32_t h = 0, k = 0;
    size_t i = 0;
    for (; i + 4 <= s.size(); i += 4) {
        k = uint8_t(s[i]) | uint32_t(uint8_t(s[i+1])) << 8 |
            uint32_t(uint8_t(s[i+2])) << 16 | uint32_t(uint8_t(s[i+3])) << 24;
        k *= 0xcc9e2d51u; k = rotate(k, 15); k *= 0x1b873593u;
        h ^= k; h = rotate(h, 13); h = h * 5 + 0xe6546b64u;
    }
    k = 0;
    for (size_t j = 0; i + j < s.size(); ++j) k |= uint32_t(uint8_t(s[i+j])) << (8 * j);
    if (i < s.size()) { k *= 0xcc9e2d51u; k = rotate(k, 15); k *= 0x1b873593u; h ^= k; }
    h ^= uint32_t(s.size()); h ^= h >> 16; h *= 0x85ebca6bu; h ^= h >> 13; h *= 0xc2b2ae35u;
    return h ^ (h >> 16);
}
#define ITEM_NAME(label, name, kind) name,
#define NO_SECTION(label)
static const char *const oot_item_names[] = {OOT_CHEAT_ITEMS(NO_SECTION, ITEM_NAME)};
#define OOT_ITEM_COUNT (sizeof oot_item_names / sizeof oot_item_names[0])
// HOST_HELPERS
int main() {
    Ctx c;
    CHECK(flag_hash("Item_Melody_EponaSong") == 0xb492ac33u);
    int songs = 0;
    for (unsigned i = 0; i < OOT_ITEM_COUNT; ++i) {
        const char *name = oot_item_names[i];
        if (std::strncmp(name, "Item_Melody_", 12)) continue;
        ++songs;
        const uint32_t own = flag_hash(name), other = 0x12345678u;
        pouch.clear(); flags.clear(); pouch_reads = pouch_writes = flag_writes = 0;
        flags[own] = 1; flags[other] = 1;
        CHECK(oot_item_count(&c, name) == 1);   // Learned; the pouch still holds zero.
        CHECK(pouch_reads == 0);
        flags[own] = 0; pouch[name] = 7;       // A stale pouch entry cannot grant a song.
        CHECK(oot_item_count(&c, name) == 0);
        CHECK(pouch_reads == 0);
        const int toggle = OOT_CHEAT_ITEM_ACTION + int(i) * 256 + 200;
        oot_inventory_edit(&c, toggle);
        CHECK(flags[own] == 1 && flags[other] == 1 && flag_writes == 1);
        CHECK(oot_item_count(&c, name) == 1 && pouch_writes == 0);
        oot_inventory_edit(&c, toggle);
        CHECK(flags[own] == 0 && flags[other] == 1 && flag_writes == 2);
        reject_flag_write = true;
        oot_inventory_edit(&c, toggle);
        CHECK(flags[own] == 0 && flags[other] == 1 && flag_writes == 2 && pouch_writes == 0);
        reject_flag_write = false;
        oot_inventory_edit(&c, OOT_CHEAT_ITEM_ACTION + int(i) * 256 + 65);
        CHECK(flag_writes == 2 && pouch_writes == 0);  // Songs have no editable quantity.
        flags.erase(own);
        CHECK(oot_item_count(&c, name) == -1);         // Missing state is unavailable, not Locked.
        oot_inventory_edit(&c, toggle);
        CHECK(flag_writes == 2 && pouch_writes == 0);
    }
    CHECK(songs == 12);
    unsigned sword = 0;
    while (sword < OOT_ITEM_COUNT && std::strcmp(oot_item_names[sword], "Weapon_Sword_Kokiri")) ++sword;
    CHECK(sword < OOT_ITEM_COUNT);
    pouch["Weapon_Sword_Kokiri"] = 1;
    CHECK(oot_item_count(&c, "Weapon_Sword_Kokiri") == 1);
    oot_inventory_edit(&c, OOT_CHEAT_ITEM_ACTION + int(sword) * 256 + 200);
    CHECK(pouch["Weapon_Sword_Kokiri"] == 0 && pouch_writes == 1);
    std::puts("PASS: all 12 songs read and toggle their saved flags; ordinary inventory still uses the pouch");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    source = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    helpers = [function(source, "static uint32_t oot_song_flag(")]
    helpers += [function(source, signature) for signature in (
        "static int oot_mask_alias(",
        "static int oot_item_count(Ctx *c, const char *name) {",
        "static const char *oot_item_holder(",   # (the randomizer's fork: an amount raised gives its holder first)
        "static void oot_inventory_edit(",
    )]
    with tempfile.TemporaryDirectory(prefix="oot-song-inventory-") as tmp:
        src, exe = Path(tmp) / "songs.cpp", Path(tmp) / "songs.exe"
        src.write_text(FIXTURE.replace("// HOST_HELPERS", "\n".join(helpers)), encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-I" + str(ROOT), str(src), "-o", str(exe)], check=True)
        return subprocess.run([str(exe)]).returncode


if __name__ == "__main__":
    raise SystemExit(main())
