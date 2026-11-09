// The randomizer's settings and seed IDs (gpu/vk/oot_rando.h): an ID holds its seed and settings and gives them back,
// a mistyped one is refused, and an options file's rando_ lines are read as the menu and the game side read them.
// argv[1]: a folder for the options files it writes.
#include "../gpu/vk/oot_rando.h"

#include <cstdio>
#include <cstring>
#include <string>

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

static bool same(const OotRando& a, const OotRando& b) {
    if (a.on != b.on || a.seed != b.seed) return false;
    for (int i = 0; i < OOT_RANDO_N; i++)
        if (a.v[i] != b.v[i]) return false;
    return true;
}
static int read_text(const std::string& path, const char* text, OotRando* r, const char** bad) {
    FILE* f = std::fopen(path.c_str(), "w");
    if (!f) return -100;
    std::fputs(text, f);
    std::fclose(f);
    f = std::fopen(path.c_str(), "r");
    if (!f) return -100;
    const int got = oot_rando_read(f, r, bad);
    std::fclose(f);
    return got;
}

int main(int argc, char** argv) {
    if (argc < 2) return 2;
    const std::string file = std::string(argv[1]) + "/hookshot_options.ini";
    char id[OOT_RANDO_ID_TEXT], other[OOT_RANDO_ID_TEXT];

    // ---- the table ----
    for (int i = 0; i < OOT_RANDO_N; i++) {
        const OotRandoSetting& s = oot_rando_settings[i];
        CHECK("a setting has 2 to 4 choices (2 bits in an ID)", s.count >= 2 && s.count <= 4);
        CHECK("a setting's first choice is Off, the game's own", !std::strcmp(s.choices[0], "Off"));
        CHECK("a setting's line starts with rando_", !std::strncmp(s.key, "rando_", 6) && std::strcmp(s.key, "rando_on") &&
                                                      std::strcmp(s.key, "rando_seed") && std::strcmp(s.key, "rando_import"));
        for (int k = 0; k < i; k++) CHECK("no two settings share a line", std::strcmp(s.key, oot_rando_settings[k].key));
    }

    // ---- an ID and back: every setting at each of its choices, a few seeds ----
    uint32_t roll = 12345;
    for (int n = 0; n < 2000; n++) {
        OotRando a{}, b{};
        a.on = 1;
        roll = roll * 1664525u + 1013904223u;
        a.seed = n == 0 ? 0 : n == 1 ? OOT_RANDO_SEED_MAX : (int)(roll >> 1);
        for (int i = 0; i < OOT_RANDO_N; i++) {
            roll = roll * 1664525u + 1013904223u;
            a.v[i] = (int)((roll >> 16) % (uint32_t)oot_rando_settings[i].count);
        }
        oot_rando_id(&a, id);
        CHECK("an ID is 15 characters in three groups", std::strlen(id) == 17 && id[5] == '-' && id[11] == '-');
        CHECK("an ID loads", oot_rando_from_id(id, &b) == nullptr);
        CHECK("an ID gives back its seed and settings, the randomizer on", same(a, b));
        oot_rando_id(&b, other);
        CHECK("the same seed is the same ID", !std::strcmp(id, other));
    }

    // ---- the ID is its seed's and its settings', not the on / off row's ----
    OotRando base{}, got{};
    base.seed = 20261109;
    base.v[OOT_RANDO_CHESTS] = 3, base.v[OOT_RANDO_SKULLTULAS] = 3, base.v[OOT_RANDO_QUESTS] = 1;
    oot_rando_id(&base, id);
    base.on = 1;
    oot_rando_id(&base, other);
    CHECK("on or off: the same ID", !std::strcmp(id, other));
    OotRando changed = base;
    changed.v[OOT_RANDO_CHESTS] = 2;
    oot_rando_id(&changed, other);
    CHECK("another setting: another ID", std::strcmp(id, other));
    changed = base, changed.seed++;
    oot_rando_id(&changed, other);
    CHECK("another seed: another ID", std::strcmp(id, other));
    changed = base, changed.v[OOT_RANDO_QUESTS] = 9;
    oot_rando_id(&changed, other);
    changed.v[OOT_RANDO_QUESTS] = 0;
    char off[OOT_RANDO_ID_TEXT];
    oot_rando_id(&changed, off);
    CHECK("a choice past its setting's last is the game's own in an ID", !std::strcmp(other, off));

    // ---- as typed: small letters, no dashes, spaces, a line's end; O for 0, I and L for 1 ----
    std::string typed;
    for (const char* p = id; *p; p++)
        if (*p != '-') typed += (char)(*p >= 'A' && *p <= 'Z' ? *p - 'A' + 'a' : *p == '0' ? 'o' : *p == '1' ? 'l' : *p);
    typed = "  " + typed.substr(0, 7) + " " + typed.substr(7) + "\r\n";
    CHECK("an ID as typed loads", oot_rando_from_id(typed.c_str(), &got) == nullptr && same(got, base));

    // ---- what is not an ID: r is left alone ----
    OotRando kept{};
    kept.seed = 77, kept.v[OOT_RANDO_SONGS] = 2;
    const OotRando before = kept;
    CHECK("empty", oot_rando_from_id("", &kept) != nullptr && same(kept, before));
    CHECK("too short", oot_rando_from_id(std::string(id).substr(0, 16).c_str(), &kept) != nullptr && same(kept, before));
    CHECK("too long", oot_rando_from_id((std::string(id) + "0").c_str(), &kept) != nullptr && same(kept, before));
    CHECK("a character no ID has", oot_rando_from_id((std::string(id).substr(0, 16) + "U").c_str(), &kept) != nullptr);
    int refused = 0, tried = 0;
    for (size_t at = 0; id[at]; at++) {   // (one character changed, anywhere: the checksum's)
        if (id[at] == '-') continue;
        for (const char* c = oot_rando_alphabet(); *c; c++) {
            if (*c == id[at]) continue;
            std::string typo = id;
            typo[at] = *c;
            tried++;
            refused += oot_rando_from_id(typo.c_str(), &kept) != nullptr;
        }
    }
    CHECK("every other character tried in every place", tried == 15 * 31);
    CHECK("a typo is refused (an 8-bit checksum: 255 of 256)", refused >= tried * 97 / 100);
    kept = before;   // (a typo the checksum let through loaded)
    {   // (an ID of another format version, and one with a choice this version's setting does not have: both with a
        // right checksum, so it is the version and the choice that refuse them)
        uint8_t bits[OOT_RANDO_ID_BITS] = {};
        auto text_of = [&](char* out) {
            int n = OOT_RANDO_ID_BITS - OOT_RANDO_ID_CHECK;
            oot_rando_put(bits, &n, oot_rando_check(bits), OOT_RANDO_ID_CHECK);
            for (int c = 0; c < 15; c++) {
                int at = c * 5;
                out[c] = oot_rando_alphabet()[oot_rando_get(bits, &at, 5)];
            }
            out[15] = 0;
        };
        int n = 0;
        oot_rando_put(bits, &n, OOT_RANDO_ID_VERSION + 1, 4);
        text_of(other);
        CHECK("another version's ID", oot_rando_from_id(other, &kept) != nullptr && same(kept, before));
        n = 0;
        oot_rando_put(bits, &n, OOT_RANDO_ID_VERSION, 4);
        text_of(other);
        CHECK("the plainest ID loads", oot_rando_from_id(other, &got) == nullptr && got.on && !got.seed);
        n = 4 + 31 + 2 * (OOT_RANDO_ID_SLOTS - 1);   // (the last pair: a setting no version has yet)
        oot_rando_put(bits, &n, 1, 2);
        text_of(other);
        CHECK("a setting this version does not have", oot_rando_from_id(other, &kept) != nullptr && same(kept, before));
        if (oot_rando_settings[OOT_RANDO_QUESTS].count < 4) {
            std::memset(bits, 0, sizeof bits);
            n = 0;
            oot_rando_put(bits, &n, OOT_RANDO_ID_VERSION, 4);
            n = 4 + 31 + 2 * OOT_RANDO_QUESTS;
            oot_rando_put(bits, &n, 3, 2);
            text_of(other);
            CHECK("a choice its setting does not have", oot_rando_from_id(other, &kept) != nullptr && same(kept, before));
        }
    }

    // ---- an options file ----
    const char* bad = "unset";
    CHECK("no randomizer lines: off", read_text(file, "fullscreen=1\noptions_version=3\npad_a=1\n", &got, &bad) == 0 && !bad &&
                                      same(got, OotRando{}));
    std::string lines = "frame_pacing=1\nrando_on=1\nrando_seed=20261109\n";
    lines += std::string(oot_rando_settings[OOT_RANDO_CHESTS].key) + "=3\n";
    lines += std::string(oot_rando_settings[OOT_RANDO_SKULLTULAS].key) + "=3\r\n";
    lines += std::string(oot_rando_settings[OOT_RANDO_QUESTS].key) + "=1\noptions_version=3\nkey_a=65,0\n";
    CHECK("the menu's lines", read_text(file, lines.c_str(), &got, &bad) == 0 && same(got, base));
    CHECK("a choice out of range is the game's own, a seed out of range held to it",
          read_text(file, "rando_chests=7\nrando_songs=-2\nrando_seed=99999999999\nrando_on=5\n", &got, nullptr) == 0 && got.on == 1 &&
              got.seed == OOT_RANDO_SEED_MAX && !got.v[OOT_RANDO_CHESTS] && !got.v[OOT_RANDO_SONGS]);
    CHECK("a negative seed", read_text(file, "rando_seed=-4\n", &got, nullptr) == 0 && !got.seed && !got.on);
    // (an import wins over the lines beside it, wherever it is in the file, and turns the randomizer on)
    CHECK("an import before the other lines",
          read_text(file, (std::string("rando_import=") + id + "\nrando_on=0\nrando_seed=5\nrando_songs=2\n").c_str(), &got, &bad) == 1 &&
              !bad && same(got, base));
    CHECK("an import after them",
          read_text(file, (std::string("rando_on=0\nrando_seed=5\nrando_songs=2\nrando_import= ") + typed).c_str(), &got, &bad) == 1 &&
              same(got, base));
    OotRando file_only{};
    file_only.seed = 5, file_only.v[OOT_RANDO_SONGS] = 2;
    CHECK("an import that is no ID: the other lines stay, and why",
          read_text(file, "rando_seed=5\nrando_songs=2\nrando_import=HELLO\n", &got, &bad) == -1 && bad && same(got, file_only));
    CHECK("an empty import", read_text(file, "rando_import=\n", &got, &bad) == -1 && bad);

    std::puts("randomizer settings: all checks passed");
}
