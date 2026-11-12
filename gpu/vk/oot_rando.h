/* (OoT randomizer) The randomizer's settings and its seed IDs, shared by the game side (host/oot_rando.c) and
   tests/test_rando_settings.py; the launcher's Randomizer page (launcher/Launcher.cs: RandoRows, RandoId) has the same
   table and the same IDs, written again in C#. The Insert menu had a Randomizer tab of these rows until Mako 3.3, whose
   menu was written anew: the settings are the launcher's now. Plain C, no other header of the project.

   The settings are the rando_ lines of hookshot_options.ini (the launcher's Randomizer page writes them too):
     rando_on=0|1          the randomizer
     rando_seed=<number>   the seed's random part, 0 to 2^31 - 1
     rando_<setting>=<n>   a choice of the table below, 0 the game's own
     rando_import=<ID>     a seed ID to load at the next start: it sets every line above and turns the randomizer on,
                           then the menu drops the line

   A seed ID is 15 characters, XXXXX-XXXXX-XXXXX (Crockford base32: no I, L, O or U; I and L read as 1, O as 0). It holds
   the random part and every setting, with a checksum, so the same ID on the same version is the same seed and IDs can
   be shared. Bits, low first: the format's version 4, the random part 31, 16 settings of 2 bits in the table's order
   (the ones past the table 0), the checksum 8. A new setting takes the next free pair: the IDs made before it hold 0
   there, the game's own, and keep loading.

   The 16 pairs are all taken, so there is a longer ID too, 20 characters, XXXXX-XXXXX-XXXXX-XXXXX: the version 2, the
   random part 31, 28 settings of 2 bits, a bit that is 0, the checksum 8. A seed whose settings past the sixteenth are
   all the game's own still gets the 15 characters, the ID it always had, which the versions before read; the longer
   one is made only when one of them is set. Both are read, told apart by their length.

   Modelled on LAS Recomp's randomizer settings and seed IDs (peiikai/LASRecomp, runtime/ui/rando_tab.mm, MIT). Nothing
   is copied from it.

   What is not here: the item placement. tools/rando/rando_seed.py reads rando_on, rando_seed, rando_chests,
   rando_skulltulas, rando_quests (with rando_frogs and rando_light_arrows), rando_keys, rando_major, rando_open_deku,
   rando_open_forest, rando_skip_intro, rando_start_rupees, rando_scrubs, rando_shops and rando_progressive, shuffles the chests, the Gold Skulltulas' drops and some characters' gifts and
   makes the open ways' and the opening's changes as a mod (the launcher runs it at Play); the other settings are not placed yet
   (host/oot_rando.c). */
#ifndef OOT_RANDO_H
#define OOT_RANDO_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* X(NAME, label, ini key, help, choices...): choice 0 is the game's own; 4 choices at most (2 bits in a seed ID).
   Append only: a setting's place is its place in a seed ID. Each is a selector of the launcher's Randomizer page
   (launcher/Launcher.cs RandoRows: the same keys and choices, kept in step by tests/test_rando_settings.py). */
#define OOT_RANDO_SETTINGS(X) \
    X(CHESTS, "Chests", "rando_chests", \
      "Which treasure chests hold a shuffled item. All is every chest in the game.", \
      "Off", "Overworld", "Dungeons", "All") \
    X(SKULLTULAS, "Gold Skulltulas", "rando_skulltulas", \
      "Which Gold Skulltulas take part: their tokens change places with the chests' supplies (all but rupees). Needs Chests.", \
      "Off", "Dungeons", "Overworld", "All") \
    X(QUESTS, "Quest rewards", "rando_quests", \
      "What some characters give takes part with the chests: Darunia, mini-games, side quests and the Gold Skulltula family. Needs Chests.", \
      "Off", "On") \
    X(SONGS, "Songs", "rando_songs", \
      "Song spots: the songs are shuffled among the places that teach one. Anywhere: a song can be any item's place.", \
      "Off", "Song spots", "Anywhere") \
    X(HEART_PIECES, "Heart Pieces", "rando_heart_pieces", \
      "Heart Pieces and the other items lying in the world are shuffled.", \
      "Off", "On") \
    X(SHOPS, "Shops", "rando_shops", \
      "Four shelves of each shop sell a shuffled item, once each, at a rolled price of 1 to 1000 rupees. The wallets are shuffled too: a price asks for one that holds it. Needs Chests.", \
      "Off", "Low prices", "Any price") \
    X(SCRUBS, "Deku Scrubs", "rando_scrubs", \
      "The Business Scrubs' one-time sales (two Pieces of Heart, the Deku Stick and Deku Nut upgrades) take part with the chests. Needs Chests.", \
      "Off", "On") \
    X(DUNGEON_REWARDS, "Dungeon rewards", "rando_dungeon_rewards", \
      "The Spiritual Stones and Medallions. Dungeons: shuffled among the dungeons' ends. Anywhere: any item's place.", \
      "Off", "Dungeons", "Anywhere") \
    X(KEYS, "Dungeon keys", "rando_keys", \
      "Small keys and Boss Keys. Own dungeon: shuffled inside their dungeon. Anywhere: they can be in any place of the game.", \
      "Off", "Own dungeon", "Anywhere") \
    X(MAJOR, "Major items", "rando_major", \
      "The big items in chests (Kokiri Sword, Bow, Megaton Hammer and the like) are shuffled too, placed so the game can be finished. Needs Chests.", \
      "Off", "On") \
    X(OPEN_DEKU, "Open Deku Tree", "rando_open_deku", \
      "A new game's way to the Great Deku Tree is open from the start: Mido lets Link by without a sword and a shield.", \
      "Off", "On") \
    X(OPEN_FOREST, "Open forest exit", "rando_open_forest", \
      "A new game's way out of Kokiri Forest is open from the start: Link can leave before the Deku Tree is done.", \
      "Off", "On") \
    X(SKIP_INTRO, "Skip opening", "rando_skip_intro", \
      "A new game starts in Link's house, without the narration and Navi's flight.", \
      "Off", "On") \
    X(FROGS, "Frogs", "rando_frogs", \
      "With Quest rewards: the frogs of Zora's River take part too.", \
      "Off", "On") \
    X(LIGHT_ARROWS, "Light Arrows", "rando_light_arrows", \
      "With Quest rewards: the Light Arrows Zelda gives take part too, and can be anywhere.", \
      "Off", "On") \
    X(START_RUPEES, "Starting rupees", "rando_start_rupees", \
      "A new game starts with 200 rupees in Link's wallet.", \
      "Off", "200") \
    X(PROGRESSIVE, "Progressive items", "rando_progressive", \
      "An upgrade found gives the next one Link has not: bomb bags, the bow and quivers, the slingshot and bullet bags, Hookshot and Longshot, strength, scales, wallets, stick and nut bags, magic. A chest still shows the item it was shuffled as.", \
      "Off", "On")

enum {
#define OOT_RANDO_ENUM(NAME, label, key, help, ...) OOT_RANDO_##NAME,
    OOT_RANDO_SETTINGS(OOT_RANDO_ENUM)
#undef OOT_RANDO_ENUM
    OOT_RANDO_N
};
enum {
    OOT_RANDO_ID_VERSION = 1,
    OOT_RANDO_ID_SLOTS = 16,     /* settings the 15 characters have room for */
    OOT_RANDO_ID_BITS = 75,      /* 4 + 31 + 2 * 16 + 8 */
    OOT_RANDO_ID_CHECK = 8,
    OOT_RANDO_ID_LONG_VERSION = 2,
    OOT_RANDO_ID_LONG_SLOTS = 28,   /* settings the 20 characters have room for */
    OOT_RANDO_ID_LONG_BITS = 100,   /* 4 + 31 + 2 * 28 + 1 + 8 */
    OOT_RANDO_ID_TEXT = 24,      /* 20 characters, 3 dashes and the end */
    OOT_RANDO_SEED_MAX = 0x7fffffff
};
typedef char oot_rando_fits_an_id[(int)OOT_RANDO_N <= (int)OOT_RANDO_ID_LONG_SLOTS ? 1 : -1];

typedef struct OotRandoSetting {
    const char *label, *key, *help;
    const char *const *choices;
    int count;   /* choices: values 0 to count - 1 */
} OotRandoSetting;

#define OOT_RANDO_CHOICES(NAME, label, key, help, ...) static const char *const oot_rando_choices_##NAME[] = {__VA_ARGS__};
OOT_RANDO_SETTINGS(OOT_RANDO_CHOICES)
#undef OOT_RANDO_CHOICES
static const OotRandoSetting oot_rando_settings[OOT_RANDO_N] = {
#define OOT_RANDO_ROW(NAME, label, key, help, ...) \
    {label, key, help, oot_rando_choices_##NAME, (int)(sizeof oot_rando_choices_##NAME / sizeof oot_rando_choices_##NAME[0])},
    OOT_RANDO_SETTINGS(OOT_RANDO_ROW)
#undef OOT_RANDO_ROW
};

typedef struct OotRando {
    int on;
    int seed;               /* the random part: 0 to OOT_RANDO_SEED_MAX */
    int v[OOT_RANDO_N];     /* each setting's choice */
} OotRando;

static inline void oot_rando_put(uint8_t *bits, int *n, uint32_t value, int width) {
    for (int i = 0; i < width; i++) bits[(*n)++] = (uint8_t)(value >> i & 1);
}
static inline uint32_t oot_rando_get(const uint8_t *bits, int *n, int width) {
    uint32_t value = 0;
    for (int i = 0; i < width; i++) value |= (uint32_t)bits[(*n)++] << i;
    return value;
}
/* (FNV-1a over the bits before the checksum, folded to its width; total: the ID's bits, 75 or 100) */
static inline uint32_t oot_rando_check_of(const uint8_t *bits, int total) {
    uint32_t h = 0x811c9dc5u;
    for (int i = 0; i < total - OOT_RANDO_ID_CHECK; i++) h = (h ^ bits[i]) * 0x01000193u;
    return (h ^ h >> 8 ^ h >> 16 ^ h >> 24) & ((1u << OOT_RANDO_ID_CHECK) - 1);
}
static inline uint32_t oot_rando_check(const uint8_t *bits) { return oot_rando_check_of(bits, OOT_RANDO_ID_BITS); }
static inline const char *oot_rando_alphabet(void) { return "0123456789ABCDEFGHJKMNPQRSTVWXYZ"; }

/* A setting's choice as an ID holds it: one past its setting's last, or of a setting past the table, is the game's own */
static inline uint32_t oot_rando_choice(const OotRando *r, int i) {
    const int v = i < OOT_RANDO_N ? r->v[i] : 0;
    return i < OOT_RANDO_N && v > 0 && v < oot_rando_settings[i].count ? (uint32_t)v : 0;
}

/* The seed ID of a seed's random part and settings in one of its two forms, into out[OOT_RANDO_ID_TEXT]: the 15
   characters (longer 0: the settings past the sixteenth are not in it) or the 20. */
static inline void oot_rando_id_as(const OotRando *r, char *out, int longer) {
    const int total = longer ? OOT_RANDO_ID_LONG_BITS : OOT_RANDO_ID_BITS;
    uint8_t bits[OOT_RANDO_ID_LONG_BITS];
    int n = 0;
    memset(bits, 0, sizeof bits);
    oot_rando_put(bits, &n, longer ? OOT_RANDO_ID_LONG_VERSION : OOT_RANDO_ID_VERSION, 4);
    oot_rando_put(bits, &n, (uint32_t)r->seed & OOT_RANDO_SEED_MAX, 31);
    for (int i = 0; i < (longer ? OOT_RANDO_ID_LONG_SLOTS : OOT_RANDO_ID_SLOTS); i++) oot_rando_put(bits, &n, oot_rando_choice(r, i), 2);
    n = total - OOT_RANDO_ID_CHECK;   /* (the longer one's bit before the checksum stays 0) */
    oot_rando_put(bits, &n, oot_rando_check_of(bits, total), OOT_RANDO_ID_CHECK);
    char *p = out;
    for (int c = 0; c < total / 5; c++) {
        int at = c * 5;
        if (c && c % 5 == 0) *p++ = '-';
        *p++ = oot_rando_alphabet()[oot_rando_get(bits, &at, 5)];
    }
    *p = 0;
}

/* The seed ID of a seed's random part and settings (on or not), into out[OOT_RANDO_ID_TEXT]: the 15 characters, or
   the 20 when a setting past the sixteenth is set. A choice past its setting's last counts as the game's own, as
   oot_rando_read keeps them. */
static inline void oot_rando_id(const OotRando *r, char *out) {
    int longer = 0;
    for (int i = OOT_RANDO_ID_SLOTS; i < OOT_RANDO_ID_LONG_SLOTS; i++) longer |= oot_rando_choice(r, i) != 0;
    oot_rando_id_as(r, out, longer);
}

/* A seed ID as typed or pasted (dashes, spaces and the line's end are skipped; small letters count) into r: its random
   part and settings, the randomizer on. Returns NULL, or what is wrong with the text, r untouched. */
static inline const char *oot_rando_from_id(const char *text, OotRando *r) {
    uint8_t bits[OOT_RANDO_ID_LONG_BITS];
    int n = 0;
    for (const char *p = text; *p; p++) {
        char ch = *p;
        if (ch == '-' || ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n') continue;
        if (ch >= 'a' && ch <= 'z') ch = (char)(ch - 'a' + 'A');
        if (ch == 'O') ch = '0';
        if (ch == 'I' || ch == 'L') ch = '1';
        const char *at = strchr(oot_rando_alphabet(), ch);
        if (!at) return "not a seed ID (a character no seed ID has)";
        if (n == OOT_RANDO_ID_LONG_BITS) return "too long for a seed ID (15 or 20 characters)";
        oot_rando_put(bits, &n, (uint32_t)(at - oot_rando_alphabet()), 5);
    }
    if (n < OOT_RANDO_ID_BITS) return "too short for a seed ID (15 or 20 characters)";
    if (n != OOT_RANDO_ID_BITS && n != OOT_RANDO_ID_LONG_BITS) return "not as long as a seed ID is (15 or 20 characters)";
    const int total = n, longer = n == OOT_RANDO_ID_LONG_BITS;
    n = total - OOT_RANDO_ID_CHECK;
    if (oot_rando_get(bits, &n, OOT_RANDO_ID_CHECK) != oot_rando_check_of(bits, total)) return "a typo? (the seed ID's checksum does not match)";
    n = 0;
    if ((int)oot_rando_get(bits, &n, 4) != (longer ? OOT_RANDO_ID_LONG_VERSION : OOT_RANDO_ID_VERSION))
        return "a seed ID from another version of the randomizer";
    OotRando t;
    memset(&t, 0, sizeof t);
    t.on = 1;
    t.seed = (int)oot_rando_get(bits, &n, 31);
    for (int i = 0; i < (longer ? OOT_RANDO_ID_LONG_SLOTS : OOT_RANDO_ID_SLOTS); i++) {
        const int v = (int)oot_rando_get(bits, &n, 2);
        if (v >= (i < OOT_RANDO_N ? oot_rando_settings[i].count : 1)) return "a seed ID with a setting this version does not have";
        if (i < OOT_RANDO_N) t.v[i] = v;
    }
    if (longer && oot_rando_get(bits, &n, 1)) return "a seed ID with a setting this version does not have";
    *r = t;
    return NULL;
}

/* The randomizer's lines of an options file into r (what the file does not say: off, seed 0, the game's own; a choice
   out of its setting's range too). A rando_import line wins over the others when it holds a seed ID: 1 then, and
   *import_error is NULL. -1 when it holds something else (*import_error says what, r is the other lines'). 0: no
   such line. import_error may be NULL. */
static inline int oot_rando_read(FILE *f, OotRando *r, const char **import_error) {
    char line[160], import[64] = "";
    int has_import = 0;
    memset(r, 0, sizeof *r);
    if (import_error) *import_error = NULL;
    while (fgets(line, sizeof line, f)) {
        char *eq = strchr(line, '=');
        if (!eq || strncmp(line, "rando_", 6)) continue;
        *eq++ = 0;
        if (!strcmp(line, "rando_import")) {
            has_import = 1;
            snprintf(import, sizeof import, "%s", eq);
        } else if (!strcmp(line, "rando_on")) {
            r->on = atoi(eq) != 0;
        } else if (!strcmp(line, "rando_seed")) {
            const long long seed = atoll(eq);
            r->seed = seed < 0 ? 0 : seed > OOT_RANDO_SEED_MAX ? OOT_RANDO_SEED_MAX : (int)seed;
        } else {
            for (int i = 0; i < OOT_RANDO_N; i++)
                if (!strcmp(line, oot_rando_settings[i].key)) {
                    const int v = atoi(eq);
                    r->v[i] = v > 0 && v < oot_rando_settings[i].count ? v : 0;
                }
        }
    }
    if (!has_import) return 0;
    const char *bad = oot_rando_from_id(import, r);
    if (import_error) *import_error = bad;
    return bad ? -1 : 1;
}

#endif
