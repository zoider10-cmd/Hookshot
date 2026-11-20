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
   rando_open_forest, rando_skip_intro, rando_start_rupees, rando_scrubs, rando_shops (with rando_shop_shelves), rando_sword_shield and rando_progressive (rando_skip_cutscenes is the game's own: host/hos_main.c), shuffles the chests, the Gold Skulltulas' drops and some characters' gifts and
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
      "Which Gold Skulltulas take part as chests do: one can drop any item of the shuffle a pick-up can be (not rupees, Pieces of Heart, keys, songs or bottles), and its token can be anywhere. The Skulltula house's rewards ask for their tokens. Needs Chests.", \
      "Off", "Dungeons", "Overworld", "All") \
    X(QUESTS, "Quest rewards", "rando_quests", \
      "What some characters give takes part with the chests: Darunia, mini-games (the frogs of Zora's River among them), side quests, the Gold Skulltula family and the three Great Fairies of the spells (a fairy may then give only an item there is one of). Needs Chests.", \
      "Off", "On") \
    X(SONGS, "Songs", "rando_songs", \
      "Song spots: the twelve songs are shuffled among the twelve lessons. The teacher still plays the old song's notes; the song you get is named after. Anywhere: the songs are items like any other, in chests, shops and gifts (a song looks like a green rupee), and a lesson gives whatever the seed put there. Some lessons can only hold a song or a few one-of-a-kind items, so some songs stay in lessons. Anywhere, ocarina too: also the two ocarinas, Saria's on the bridge and Zelda's at the moat; every check that needs a song then needs the Fairy Ocarina.", \
      "Off", "Song spots", "Anywhere", "Anywhere, ocarina too") \
    X(HEART_PIECES, "Heart Pieces", "rando_heart_pieces", \
      "The 14 Pieces of Heart lying in the world and the 8 Heart Containers the bosses leave take part as chests do: each can give any item of the shuffle but keys and songs. It still looks like a Piece of Heart or a Heart Container and its scene says so, but the item is what Link gets, and the heart is somewhere else. Pieces given by a character or held by a chest are not these.", \
      "Off", "On") \
    X(SHOPS, "Shops", "rando_shops", \
      "Four shelves of each shop sell a shuffled item, once each, at a rolled price of 10 to 750 rupees, in tens. Affordable: every shelf costs 10 rupees. The wallets are shuffled too: a price asks for one that holds it. Needs Chests.", \
      "Off", "Low prices", "Any price", "Affordable") \
    X(SCRUBS, "Deku Scrubs", "rando_scrubs", \
      "The Business Scrubs' one-time sales (two Pieces of Heart, the Deku Stick and Deku Nut upgrades) take part with the chests. On, 10 rupees each: the same, and each of those four costs 10 rupees (moves no item). Needs Chests.", \
      "Off", "On", "On, 10 rupees each") \
    X(DUNGEON_REWARDS, "Dungeon rewards", "rando_dungeon_rewards", \
      "The Spiritual Stones and Medallions the eight dungeons end in. Dungeons: shuffled among those eight endings. Anywhere: any item's place. None is needed to go on: the story goes by each dungeon being done, not by its stone or medallion.", \
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
    /* (no longer a choice: the frogs take part whenever Quest rewards is on, tools/rando/rando_seed.py. The row keeps \
       its place here, which is its place in a seed's ID; the launcher does not show it) */ \
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
      "Off", "On") \
    X(SKIP_CUTSCENES, "Skip cutscenes", "rando_skip_cutscenes", \
      "Cutscenes are passed over as soon as they start, with the game's own skip: Saria's goodbye, the Deku Tree's story and the like. The scenes made of talk (Saria's first words, the owl's) lose their talk, camera moves and waits and keep what they do. Song lessons go straight to the song. Chests, item scenes, the Great Fairies and the Royal Family's Tomb still play. Not the title, the opening narration or the credits.", \
      "Off", "On") \
    X(SHOP_SHELVES, "Every shop shelf", "rando_shop_shelves", \
      "With Shops. Off: four shelves of each shop sell a shuffled item, and what a game buys again and again stays for sale (bombs, arrows, nuts, potions, shields, tunics). On: every shelf of the six shops does, each sold once; those supplies then come from grass, pots and enemies.", \
      "Off", "On") \
    X(SWORD_SHIELD, "Shuffle sword and shield", "rando_sword_shield", \
      "The Kokiri Sword in its chest and the Deku Shield on the Kokiri shop's shelf. Off: both stay where the game has them. On: the sword's chest takes part with Major items and the shield's shelf with Shops, and the way past Mido asks for both unless Open Deku Tree is on.", \
      "Off", "On") \
    X(OPEN_DOOR, "Open Door of Time", "rando_open_door", \
      "The Temple of Time's inner door is open from a new game's start, and the Master Sword takes Link forward and back in time whenever he draws it or puts it back. The story's own scene there (the Sage of Light) still comes when the three stones and the Song of Time are done. The seed's logic counts on it a little: places only an adult can reach no longer ask for the Boomerang, nor (with Open forest exit) for the Kokiri Sword and Slingshot; they still ask for bombs. With the Song of Time: the door stays shut until Link holds the Song of Time and an ocarina; then it is gone the next time he enters the temple, and the sword takes him through time as with On. With the songs shuffled, places only an adult has ask for the Song of Time in place of the three stones.", \
      "Off", "On", "With the Song of Time") \
    X(AMMO_PICKUPS, "Ammo pick-ups", "rando_ammo_pickups", \
      "Bombs, Deku Nuts, Deku Seeds, Deku Sticks and arrows lying in the world or dropped by grass, pots and enemies. As the game has it: what the pick-up says. 5 each: at least 5. Fill the bag: the bag is filled to what it holds. Not chests or shops.", \
      "As the game has it", "5 each", "Fill the bag") \
    X(RUPEE_FILL, "Rupees fill the wallet", "rando_rupee_fill", \
      "A rupee lying in the world or dropped by grass, pots and enemies fills the wallet to what it holds. Not chests, shops or prizes.", \
      "Off", "On") \
    X(SKULLTULAS_DAY, "Gold Skulltulas by day", "rando_skulltulas_day", \
      "The 30 Gold Skulltulas that come out only at night are there by day too. Moves no item.", \
      "Off", "On") \
    X(GANON_BRIDGE, "Ganon's Castle bridge", "rando_ganon_bridge", \
      "The rainbow bridge to Ganon's Castle. As the game has it: after the Shadow and Spirit Temples' sages wake. Open: from the start. 6 medallions: once Link holds all six. Its own scene plays when Link next stands at the castle's edge.", \
      "As the game has it", "Open", "6 medallions") \
    X(HINTS, "Gossip Stone hints", "rando_hints", \
      "Talking to a Gossip Stone gives one of the seed's hints, each said by two stones: where a needed item is, an area on the way of the hero (it holds a needed item), or a foolish one (it holds none). No Mask of Truth needed. Moves no item: it can be turned on for a seed being played.", \
      "Off", "On") \
    X(AGELESS, "Either age's swords", "rando_ageless", \
      "The Kokiri Sword and the Master Sword can be equipped by both ages: young Link with the Master Sword, adult Link with the Kokiri Sword. The logic does not count on it. Moves no item.", \
      "Off", "On") \
    X(LETTER, "Kakariko gate", "rando_letter", \
      "Kakariko's gate to Death Mountain. Letter shuffled: the letter Zelda gives at the end of her meeting is an item of the shuffle, and the meeting gives what the seed put there; a child's check up the mountain then asks for the letter, or bombs (the Lost Woods' way to Goron City), or the Bolero of Fire when the songs are shuffled. Open: the gate is open for a child from the start (and in a save being played), as if the letter had been shown to its guard.", \
      "As the game has it", "Letter shuffled", "Open") \
    X(MAGIC, "Magic and the fairies' gifts", "rando_magic", \
      "The Great Fairies of the improved spin attack, doubled magic and halved damage join the shuffle (as the spell fairies do with Quest rewards), and magic becomes two items of the shuffle: the first gives the magic meter, the second doubles it. The Lens of Truth, the spells and the magic arrows no longer give magic by themselves. Needs Quest rewards.", \
      "Off", "On") \
    X(AGELESS_ITEMS, "Either age's items", "rando_ageless_items", \
      "Each age can use the other's items: young Link the Bow with its arrows, fire, ice and light arrows too (held like the Slingshot), the Hammer and the Hookshots; adult Link the Slingshot, the Boomerang and Deku Sticks; both the Kokiri and Mirror Shields. Tested in play: young Link's Bow, Hammer and Longshot, adult Link's Deku Sticks, Slingshot and Boomerang. Known quirks: adult Link's Boomerang stops in front of him on its way back (equip another item and back to throw again); the shot's prompt may name the other age's ammo. Young Link can't use the boots or the Biggoron's Sword: those stay adult Link's. Harmless: Link's model may look stretched or wrong in some cutscenes and for a moment while he uses the other age's item, as it does whenever a cutscene plays at the age it was not made for. The logic does not count on it. Moves no item.", \
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
    OOT_RANDO_ID_XL_VERSION = 3,
    OOT_RANDO_ID_XL_SLOTS = 41,     /* settings the 25 characters have room for (made 2026-11-19, the 20's being full) */
    OOT_RANDO_ID_XL_BITS = 125,     /* 4 + 31 + 2 * 41 + 8 */
    OOT_RANDO_ID_TEXT = 30,      /* 25 characters, 4 dashes and the end */
    OOT_RANDO_SEED_MAX = 0x7fffffff
};
typedef char oot_rando_fits_an_id[(int)OOT_RANDO_N <= (int)OOT_RANDO_ID_XL_SLOTS ? 1 : -1];

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
/* (FNV-1a over the bits before the checksum, folded to its width; total: the ID's bits, 75, 100 or 125) */
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

/* An ID's form (0: the 15 characters, 1: the 20, 2: the 25): its bits, the settings it holds, its version */
static inline int oot_rando_form_bits(int form) { return form == 2 ? OOT_RANDO_ID_XL_BITS : form ? OOT_RANDO_ID_LONG_BITS : OOT_RANDO_ID_BITS; }
static inline int oot_rando_form_slots(int form) { return form == 2 ? OOT_RANDO_ID_XL_SLOTS : form ? OOT_RANDO_ID_LONG_SLOTS : OOT_RANDO_ID_SLOTS; }
static inline int oot_rando_form_version(int form) { return form == 2 ? OOT_RANDO_ID_XL_VERSION : form ? OOT_RANDO_ID_LONG_VERSION : OOT_RANDO_ID_VERSION; }

/* The seed ID of a seed's random part and settings in one of its three forms, into out[OOT_RANDO_ID_TEXT]: the 15
   characters (form 0: the settings past the sixteenth are not in it), the 20 (1: not those past the 28th) or the 25. */
static inline void oot_rando_id_as(const OotRando *r, char *out, int form) {
    const int total = oot_rando_form_bits(form);
    uint8_t bits[OOT_RANDO_ID_XL_BITS];
    int n = 0;
    memset(bits, 0, sizeof bits);
    oot_rando_put(bits, &n, (uint32_t)oot_rando_form_version(form), 4);
    oot_rando_put(bits, &n, (uint32_t)r->seed & OOT_RANDO_SEED_MAX, 31);
    for (int i = 0; i < oot_rando_form_slots(form); i++) oot_rando_put(bits, &n, oot_rando_choice(r, i), 2);
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

/* The seed ID of a seed's random part and settings (on or not), into out[OOT_RANDO_ID_TEXT]: the 15 characters, the
   20 when a setting past the sixteenth is set, or the 25 when one past the 28th is. A choice past its setting's last
   counts as the game's own, as oot_rando_read keeps them. */
static inline void oot_rando_id(const OotRando *r, char *out) {
    int longer = 0, xl = 0;
    for (int i = OOT_RANDO_ID_SLOTS; i < OOT_RANDO_ID_LONG_SLOTS; i++) longer |= oot_rando_choice(r, i) != 0;
    for (int i = OOT_RANDO_ID_LONG_SLOTS; i < OOT_RANDO_ID_XL_SLOTS; i++) xl |= oot_rando_choice(r, i) != 0;
    oot_rando_id_as(r, out, xl ? 2 : longer);
}

/* A seed ID as typed or pasted (dashes, spaces and the line's end are skipped; small letters count) into r: its random
   part and settings, the randomizer on. Returns NULL, or what is wrong with the text, r untouched. */
static inline const char *oot_rando_from_id(const char *text, OotRando *r) {
    uint8_t bits[OOT_RANDO_ID_XL_BITS];
    int n = 0;
    for (const char *p = text; *p; p++) {
        char ch = *p;
        if (ch == '-' || ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n') continue;
        if (ch >= 'a' && ch <= 'z') ch = (char)(ch - 'a' + 'A');
        if (ch == 'O') ch = '0';
        if (ch == 'I' || ch == 'L') ch = '1';
        const char *at = strchr(oot_rando_alphabet(), ch);
        if (!at) return "not a seed ID (a character no seed ID has)";
        if (n == OOT_RANDO_ID_XL_BITS) return "too long for a seed ID (15, 20 or 25 characters)";
        oot_rando_put(bits, &n, (uint32_t)(at - oot_rando_alphabet()), 5);
    }
    if (n < OOT_RANDO_ID_BITS) return "too short for a seed ID (15, 20 or 25 characters)";
    if (n != OOT_RANDO_ID_BITS && n != OOT_RANDO_ID_LONG_BITS && n != OOT_RANDO_ID_XL_BITS)
        return "not as long as a seed ID is (15, 20 or 25 characters)";
    const int total = n, form = n == OOT_RANDO_ID_XL_BITS ? 2 : n == OOT_RANDO_ID_LONG_BITS, longer = form == 1;
    n = total - OOT_RANDO_ID_CHECK;
    if (oot_rando_get(bits, &n, OOT_RANDO_ID_CHECK) != oot_rando_check_of(bits, total)) return "a typo? (the seed ID's checksum does not match)";
    n = 0;
    if ((int)oot_rando_get(bits, &n, 4) != oot_rando_form_version(form))
        return "a seed ID from another version of the randomizer";
    OotRando t;
    memset(&t, 0, sizeof t);
    t.on = 1;
    t.seed = (int)oot_rando_get(bits, &n, 31);
    for (int i = 0; i < oot_rando_form_slots(form); i++) {
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
