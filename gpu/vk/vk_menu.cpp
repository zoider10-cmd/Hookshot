// The Insert menu. Drawn with Dear ImGui over the window's image at the last step of a present (menu_record; vk_imgui.h, in the
// game's style: vk_ui.h), so it costs nothing while closed and it never touches the game's picture, nor what frame interpolation
// sees. The FPS counter and the start-up screen are drawn the same way. F1 always opens and closes it, Insert too by default.
// Up and Down choose, Left and Right change, Esc closes; the game gets no keyboard input while it is open.
// (hookshot) A gamepad's Home button, or Select and Start together, opens it too; the D-pad chooses and changes, the button
// the Switch's A is bound to changes too (and opens a page), the one B is bound to goes back (vk_menu_keys.h). The game gets no gamepad input while it is open either.
// Its Controls page binds the Switch's buttons to gamepad inputs and keys.
// (hookshot) The mouse is free while it is open (the window lets it go: WM_APP + 8, host/display.c and
// host/posix/display_sdl.c): the row under the cursor is selected, a click on a tab shows it, on a value's left or right
// half changes it down or up, on a toggle flips it, on a slider's track sets it (or drag it); the wheel scrolls the rows
// (never a value, wherever the cursor is); a right click is Esc. On the Cheats page and its lists a click is Enter (on a
// choice's or an amount's left or right half, Left or Right) and a right click goes back. The drawing records each control's
// place and the mouse is tested against that (vk_menu_hit.h).
// (hookshot) The rows that take a restart (Row::restart) are tagged "After restart" while their value is not the one the game
// started with, and the Graphics tab's help lists them. Closing the menu then asks whether to restart now (menu_restart.h):
// Later keeps the saved settings for the next start and is not asked again until they change; Restart now saves and
// closes the window as the player would, and the game starts again (WM_APP + 9: host/hos_relaunch.c).
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <utility>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <mutex>
#include <string>
#include <filesystem>
#include <unordered_map>
#include <thread>
#include <system_error>
#include <vector>

#include "vk_paths.h"
#include "vk_menu.h"
#include "perf_monitor.h"
#include "intel_compiles.h"
#include "vk_menu_hit.h"
#include "vk_fps.h"    // (the FPS counter's levels and numbers)
#include "vk_draw.h"   // (pipeline_cache_save: Restart now keeps what was built)
#include "vk_texture.h"   // (the FPS counter's Dev level: texture_count, texture_bytes, texture_stats)
#include "oot_cheat_items.h"
#include "vk_progress.h"   // (StartupView, version_text: the start-up screen)
#include "vk_imgui.h"   // (the renderer's side of the overlay: begin, fonts, logo, record)
#include "vk_ui.h"
#include "vk_menu_keys.h"   // (which gamepad buttons confirm and go back: those A and B are bound to)         // (how it looks: Dear ImGui, vk_imgui.h)
#include "vk_dlss.h"
#include "vk_framegen.h"   // (Frame generation by: who makes the frames now, framegen_maker)
#include "vk_bug_report.h"   // (the Gameplay tab's Bug report: what it writes, and how)
#include "../../host/hos_wide_size.h"   // (the widescreen picture's size, as host/hos_main.c works it out)
#include "../../host/audio_output_devices.h"
#include "monitor_choice.h"
#include "vk_fsr3.h"      // (the Upscaler row: whether AMD FSR 3.1 runs on this GPU)
#include "vk_fsr3fi.h"    // (the Frame generation row: whether FSR 3.1 makes the frame)
#include "vk_fsr4.h"
#include "vk_xess.h"
#include "vk_temporal.h"
#include "vk_reflex.h"
#include "vk_antilag.h"
#include "upscaler_rows.h"
#include "auto_settings.h"
#include "menu_restart.h"
#include "threaded_rendering.h"   // (the Threaded rendering row's rule, and the one gate over its Auto)
#include "vk_menu_i18n.h"
#include "display_modes.h"   // (the Aspect ratio and Output resolution rows: the screen's sizes and their shapes)
#ifndef HOOKSHOT_ENV_H   // (env_on: the switches' one rule)
#include "hookshot_env.h"
#endif
#include "pipeline_share.h"   // (Save my pipeline list: the zip for issue 14)
#ifndef _WIN32   // (Save my pipeline list: the desktop's programs. On Windows, shell32 and ole32 are loaded when it is used)
#include <fcntl.h>
#include <spawn.h>
#include <csignal>
#include <cerrno>
#include <pthread.h>
#include <sys/stat.h>   // (save: the options file's mode)
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#endif
#include "vk_work.h"   // (after the others: counts the commands that do GPU work, for full_barrier)
#ifndef HOOKSHOT_VERSION   // (nx2/build.py gives it to this file: nx2/version.py)
#define HOOKSHOT_VERSION "unknown"
#endif

namespace mkwvk {
int64_t slot_wait_ns();   // (vk_replay.cpp: the replay's waits for a recording slot so far, the FPS counter's Dev line)
int display_refresh_mhz();   // (vk_main.cpp: the window's display, asked once a second at most: the FPS counter's V-Sync target)
HWND app_window();
extern std::atomic<bool> present_native_pq;   // (vk_replay.cpp: the presented picture is Native HDR, bypassing the SDR CRT filters)

Options opts;

namespace {
enum MenuTab {
    TAB_GRAPHICS = 0,
    TAB_AUDIO = 1,
    TAB_GAMEPLAY = 2,
    TAB_CONTROLS = 3,
    TAB_DEBUG = 4,   // (the OoT debug tools of #785, a tab of their own)
    TAB_TRACKER = 5, // (the randomizer: what the seed placed in each area, kTrackerRows rows filled from a file)
    TAB_COUNT = 6,
    TAB_MOTION = TAB_COUNT,   // (hookshot: not a tab of the strip, the Motion page that the Controls tab's Motion row
                              // opens: one past the strip's tabs, so a tab added before TAB_COUNT moves it along)
    TAB_FPS_DEV = TAB_MOTION + 1,   // (hookshot: not a tab either, the FPS counter's Dev lines page, from the Gameplay tab)
    TAB_PAGE = TAB_FPS_DEV + 1   // (hookshot: the Controls page's rows, above its grid; no tab shows them)
};

struct Row {
    MenuTab tab;
    const char* name;
    int* value;
    int lo, hi, step;
    const char* (*text)(int v);
    const char* help;   // (shown under the list while the row is selected: what the row is, the same whatever its value)
    // (a line about the value chosen, under the help, or nullptr: hint(v, -1) is the one to show now for v, hint(v, 0),
    // hint(v, 1), ... every one v can have (those that depend on the other rows or on the GPU), until nullptr, so the
    // menu keeps the height of the tallest: measure_help)
    const char* (*hint)(int v, int variant) = nullptr;
    bool restart = false;   // (read once, at the start: a change applies after a restart)
    bool preset_exempt = false;   // (a change here leaves the Quality preset alone: every row apply_preset does not set,
                                  // tests/test_preset_exempt.py)
    signed char cheat = -1;   // (a debug tool, on the Debug tab with the tools on: its index in the cheat_ tables, -1 none)
    bool heading = false;     // (a section's title on its tab, not a row: the selection steps over it)
    signed char tracker = -1; // (a line of the Tracker tab: its index in tracker_name and tracker_value, -1 none)
};
// ---- (the randomizer) the Tracker tab: the checks the seed has in each area ----
// tools/rando/rando_seed.py writes <game folder>\mods\rando-seed\tracker.txt with the seed: a line "<name>|<what>" for
// each row, read here as it is (tracker_load, below ini_path). The rows are in the table, kTrackerRows of them; the
// ones past the file's lines are not shown (row_shown). tests/test_rando_tracker.py
constexpr int kTrackerRows = 48;
char tracker_name[kTrackerRows][48];
char tracker_value[kTrackerRows][72];
int tracker_count = 0;
std::atomic<int> tracker_on{0};   // (the game side said the randomizer's game is the one played: OOT_TRACKER_ON)
// (the strip's tabs: the Tracker, the last, is the randomizer's and is not there in the normal game or in Master Quest)
static_assert(TAB_TRACKER == TAB_COUNT - 1, "the Tracker is the strip's last tab: it is left out by counting one less");
int tabs_shown() { return tracker_on.load(std::memory_order_relaxed) ? TAB_COUNT : TAB_TRACKER; }
void tracker_load();
// (the whole game's row; an area's row shows its checks in the panel instead: tracker_panel)
const char kTrackerHelp[] =
    "Every check of the randomizer's seed: treasure chests, Gold Skulltulas, gifts and shop shelves. Choose an area below to see "
    "its checks; Left and Right step through them, and with the debug tools on, confirm takes Link to the one shown. The area "
    "Link is in comes first, then the areas with something in logic.\n\n"
    "In logic: Link carries all that the seed's rules ask for at that check. The rules ask for more than a check may need, so "
    "one not in logic may still be within reach.\n\n"
    "Junk: a check stepped to can be marked as not worth going for (Y, or J), and again to count it. It is left out of the "
    "checks left, and the Show row's Left lists hide it.\n\n"
    "Collected is the randomizer's own record of the items given. Starting the seed again? Confirm twice here to forget it, "
    "and the junk marks with it.";
const char kTrackerShowHelp[] =
    "Which checks the tab lists: all of them, only the ones left to collect, or only the ones left that are in logic now. An "
    "area with nothing to list is left out.";
constexpr int kTrackerShowRow = 1;    // (the tab's second row: what it lists)
// (the tab's third row, Return home: confirmed twice, Link is taken to the Kokiri Forest as a child and to the Market as
// an adult, the action kTrackerHomeAction to the game's side. Asked for 2026-11-14: the Requiem of Spirit played with no
// other way back leaves a child in the desert, and no rule of a seed can keep a song from being played. It is the
// randomizer's own, not a debug tool: there with the debug tools off)
constexpr int kTrackerHomeRow = 2;
constexpr int kTrackerFirstArea = 3;  // (the first of the areas' rows, after the whole game's and those two)
const char kTrackerHomeHelp[] =
    "Takes Link home: to the Kokiri Forest as a child, to the Market as an adult; in a dungeon, to its entrance. For when "
    "there is no way back from where he is, a warp song played with no other to leave by. Confirm twice.";
ULONGLONG tracker_home_asked = 0;         // (when the row was confirmed once; within kTrackerForgetMs the next one goes)
// The checks one by one: tools/rando/rando_seed.py writes <game folder>\mods\rando-seed\checks.txt beside the tracker's
// file, a line "<area>|<kind>|<folder>|<ages>|<x> <y> <z>" for each chest and Gold Skulltula of the seed (tracker_load
// reads it too). A row steps through the checks of its area, the ones whose <area> is the row's name (tracker_pick: 0 the
// row's own words, n its n-th check), and confirm has the game take Link there: the check is written to
// <game folder>\rando\goto_check.txt and the action kTrackerGoAction sent (host/hos_main.c: the debug teleport to the
// folder's map when Link is in another, then the place).
constexpr int kTrackerChecks = 512;
constexpr int kTrackerGoAction = 5;
constexpr int kTrackerForgetAction = 6;   // (the first row, confirmed twice: the record of what is collected is forgotten)
constexpr int kTrackerHomeAction = 7;     // (the third row, confirmed twice: host/hos_main.c takes Link home)
ULONGLONG tracker_forget_asked = 0;       // (when the first row was confirmed once; within kTrackerForgetMs the next one forgets)
constexpr ULONGLONG kTrackerForgetMs = 4000;
struct TrackerCheck {
    char area[48], kind[80], folder[40], ages[4];   // (kind: the check's name; Chest or Gold Skulltula in a file without names)
    float pos[3];
    float stand[3];   // (where Link is put to go to it: a chest's front; its own place where the file has no other)
    char gives[64];   // (the item it gives, the game's name for it: said once it is collected; "" a file without it)
    char needs[192];   // (what the seed's rules ask for: kLogicItems' letters with commas, "-" nothing, "?" a file without it; a rule's ways apart by "/", any one of them enough (placement 5: Zora's Domain by the river or the lake), two of a whole rule of 24 items at most)
    char hash[20];   // (the check's actor hash as the file has it, "" none: its way in tracker_ways)
};
// (the randomizer's fork) The way to a check, by its actor hash: tools/rando/rando_seed.py writes check_ways.txt beside
// checks.txt, "<hash>|<words>", from Ocarina Atlas's directions (MIT, tools/rando/ATLAS_NOTICE.txt) for the Gold
// Skulltulas, Pieces of Heart and Heart Containers it describes. tracker_hint says it under the check's state
std::unordered_map<std::string, std::string> tracker_ways;
/// A check with what Link carries: 1 in logic (he has all its rule asks for), 0 not (missing, when given: what he has
/// not, by name), -1 not known (the file does not say, or no save's inventory has been read). Below the inventory's counts
int tracker_in_logic(const TrackerCheck& k, std::string* missing = nullptr);
int tracker_way_held(const char* way, size_t len, std::string* missing);   // (one way of a check's rule: tracker_in_logic)
TrackerCheck tracker_checks[kTrackerChecks];
int tracker_check_count = 0;
// What the game's side says of each check, in the file's order (host/hos_main.c oot_tracker_refresh, each second): 1
// collected (its item was given near it: the randomizer's own record, rando\collected.txt), 0 not, -1 not known (no game
// loaded yet).
static_assert(kTrackerChecks == OOT_TRACKER_MAX, "the game side reports as many checks as the menu keeps");
std::atomic<signed char> tracker_done[kTrackerChecks];
int tracker_pick[kTrackerRows];
// (the randomizer's fork) Junk: a check the player marks as not worth going for (asked for 2026-11-18), with Y on a
// controller (the Switch's Y as bound: menu_keys::extra) or J, on an area's row stepped to the check; again, and it counts
// again. A junk check is left out of the checks left and of those in logic, and the Show row's Left lists hide it. The
// marks are the Tracker's own record, <game folder>\rando\junk.txt beside the game's rando\collected.txt and in its form:
// "seed <the seed's stamp>" (the first line of mods\rando-seed\rando_stamp.txt), then each junk check's place in
// checks.txt, a line each. Another seed's record is not taken. Read when the seed's checks are (tracker_load), written at
// each change, and emptied by the first row's Forget with the record of what is collected. tests/test_tracker_junk.py
bool tracker_junk[kTrackerChecks];
std::string tracker_junk_stamp;   // (the seed the marks are of, as its stamp file says: "" none)
constexpr int kTrackerJunkPress = 18;   // (menu_tick's press[]: J, or the controller's button for it)
std::string tracker_junk_path() { return game_folder_path() + "rando\\junk.txt"; }
/// The seed's stamp: the first line of its rando_stamp.txt without the line's end ("" none), as host/hos_main.c reads it
std::string tracker_seed_stamp() {
    char line[512] = "";
    if (FILE* f = fopen((game_folder_path() + "mods\\rando-seed\\rando_stamp.txt").c_str(), "r")) {
        if (!fgets(line, sizeof line, f)) line[0] = 0;
        fclose(f);
    }
    line[strcspn(line, "\r\n")] = 0;
    return line;
}
/// The junk marks from the record at path, if it is of the seed stamp (count: the seed's checks); none otherwise
void tracker_junk_read(const std::string& path, const std::string& stamp, int count) {
    for (bool& junk : tracker_junk) junk = false;
    FILE* f = fopen(path.c_str(), "r");
    if (!f) return;
    char line[512];
    if (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!strncmp(line, "seed ", 5) && stamp == line + 5)   // (this seed's record)
            while (fgets(line, sizeof line, f)) {
                const int i = atoi(line);
                if (line[0] >= '0' && line[0] <= '9' && i < count && i < kTrackerChecks) tracker_junk[i] = true;
            }
    }
    fclose(f);
}
/// The junk marks written whole to the record at path, for the seed stamp: whether it was written
bool tracker_junk_write(const std::string& path, const std::string& stamp, int count) {
    std::error_code ec;
    std::filesystem::create_directories(std::filesystem::path(path).parent_path(), ec);   // (rando\: the game makes it too)
    FILE* f = fopen(path.c_str(), "w");
    if (!f) return false;
    fprintf(f, "seed %s\n", stamp.c_str());
    for (int i = 0; i < count && i < kTrackerChecks; i++)
        if (tracker_junk[i]) fprintf(f, "%d\n", i);
    return fclose(f) == 0;
}
// What the tab shows (the first row's Left and Right): every check, only the ones left to collect, or only the ones left
// that are in logic now. A check not shown is stepped over, and an area with none to show has no row.
enum { kTrackerShowAll, kTrackerShowLeft, kTrackerShowReachable, kTrackerShows };
int tracker_show = kTrackerShowAll;
const char* const kTrackerShowWords[kTrackerShows] = {"All checks", "Left to collect", "Left and in logic"};
std::atomic<int> tracker_here{-1};   // (a check of the map Link is in, by the game's side: OOT_TRACKER_HERE; -1 none)
/// The area Link is in (a row's name), or nullptr
const char* tracker_here_area() {
    const int i = tracker_here.load(std::memory_order_relaxed);
    return i >= 0 && i < tracker_check_count ? tracker_checks[i].area : nullptr;
}
/// What a check gives, in words: the game's name for the item made readable (the ones a seed places most by a table)
std::string tracker_item_name(const char* actor) {
    static const struct { const char *actor, *name; } known[] = {
        {"Item_Token_Gold", "Gold Skulltula Token"}, {"Obj_Heart_Piece", "Piece of Heart"}, {"Obj_Heart_Container", "Heart Container"},
        {"Item_GlassTruth", "Lens of Truth"}, {"Item_Range_Bow", "Fairy Bow"}, {"Item_Range_SlingShot", "Fairy Slingshot"},
        {"Item_HeavyBoot", "Iron Boots"}, {"Item_HoverBoot", "Hover Boots"}, {"Item_Hammer", "Megaton Hammer"},
        {"Item_Gauntlet_Goron", "Goron's Bracelet"}, {"Item_Gauntlet_Silver", "Silver Gauntlets"}, {"Item_Gauntlet_Gold", "Golden Gauntlets"},
        {"Item_Shield_Mirror", "Mirror Shield"}, {"TBox_Shield_Hylian", "Hylian Shield"}, {"TBox_Shield_Deku", "Deku Shield"},
        {"Item_Sword_Kokiri", "Kokiri Sword"}, {"Item_AgonyStone", "Stone of Agony"}, {"Item_ScrubBusinessSeed", "Deku Seeds"},
        {"Item_Wallet_Medium", "Adult's Wallet"}, {"Item_Wallet_Large", "Giant's Wallet"}, {"Item_Scale_Silver", "Silver Scale"},
        {"Item_Scale_Gold", "Golden Scale"}, {"Item_BombBag_Small", "Bomb Bag"}, {"Item_BombBag_Medium", "Big Bomb Bag"},
        {"Item_BombBag_Large", "Biggest Bomb Bag"}, {"Item_Quiver_Medium", "Big Quiver"}, {"Item_Quiver_Large", "Biggest Quiver"},
        {"Item_BulletBag_Medium", "Big Deku Seed Bag"}, {"Item_BulletBag_Large", "Biggest Deku Seed Bag"},
        {"Item_NutBag_Medium", "Big Deku Nut Bag"}, {"Item_NutBag_Large", "Biggest Deku Nut Bag"},
        {"Item_StickBag_Medium", "Big Deku Stick Bag"}, {"Item_StickBag_Large", "Biggest Deku Stick Bag"},
        {"Item_Arrow_Fire", "Fire Arrows"}, {"Item_Arrow_Ice", "Ice Arrows"}, {"Item_Arrow_Light", "Light Arrows"},
        {"Item_DinFire", "Din's Fire"}, {"Item_FaroreWind", "Farore's Wind"}, {"Item_NayruLove", "Nayru's Love"},
        {"Item_BombBundle_Small", "Bombs"}, {"Item_BombchuBundle_Small", "Bombchus"}, {"Item_DekuStickBundle_Small", "Deku Sticks"},
        {"TBox_DekuNutBundle", "Deku Nuts"}, {"TBox_ArrowBundle_Medium", "Arrows"}, {"TBox_ArrowBundle_Large", "Arrows"},
        {"Tbox_MagicJar_Large", "Magic Jar"}, {"TBox_Rupee_Green", "Green Rupee"}, {"TBox_Rupee_Blue", "Blue Rupee"},
        {"TBox_Rupee_Red", "Red Rupee"}, {"TBox_Rupee_Purple", "Purple Rupee"}, {"TBox_Rupee_Gold", "Gold Rupee"},
        {"Item_Melody_ZeldaLullaby", "Zelda's Lullaby"}, {"Item_Melody_EponaSong", "Epona's Song"}, {"Item_Melody_SariaSong", "Saria's Song"},
        {"Item_Melody_SunSong", "Sun's Song"}, {"Item_Melody_TimeSong", "Song of Time"}, {"Item_Melody_StormSong", "Song of Storms"},
        {"Item_Melody_ForestMinuet", "Minuet of Forest"}, {"Item_Melody_FireBolero", "Bolero of Fire"},
        {"Item_Melody_WaterSerenade", "Serenade of Water"}, {"Item_Melody_SpiritRequiem", "Requiem of Spirit"},
        {"Item_Melody_ShadowNocturne", "Nocturne of Shadow"}, {"Item_Melody_LightPrelude", "Prelude of Light"},
        {"Item_Dungeon_SmallKey", "Small Key"}, {"Item_Dungeon_BossKey", "Boss Key"}, {"Item_Dungeon_Map", "Dungeon Map"},
        {"Item_Dungeon_Compass", "Compass"},
    };
    for (const auto& k : known)
        if (!strcmp(k.actor, actor)) return k.name;
    // (any other: its name without the first word, a space before each capital and for each underscore)
    const char* p = strchr(actor, '_');
    std::string words;
    for (p = p ? p + 1 : actor; *p; p++) {
        if (*p == '_') words += ' ';
        else {
            if (*p >= 'A' && *p <= 'Z' && !words.empty() && words.back() != ' ' && !(p[-1] >= 'A' && p[-1] <= 'Z')) words += ' ';
            words += *p;
        }
    }
    return words;
}
/// A check is shown: not one collected when those are hidden, nor one out of logic when only the reachable are shown (one
/// whose logic is not known is)
bool tracker_check_shown(int i) {
    if (tracker_show == kTrackerShowAll) return true;
    if (tracker_done[i].load(std::memory_order_relaxed) == 1) return false;
    if (tracker_junk[i]) return false;   // (marked junk: not one left to go for)
    return tracker_show != kTrackerShowReachable || tracker_in_logic(tracker_checks[i]) != 0;
}
/// How many checks a row's area has to show (every one of the area: any true), and (n from 1) its n-th shown: nullptr past them
int tracker_row_checks(int row, bool any = false) {
    int n = 0;
    for (int i = 0; i < tracker_check_count; i++) n += !strcmp(tracker_checks[i].area, tracker_name[row]) && (any || tracker_check_shown(i));
    return n;
}
const TrackerCheck* tracker_row_check(int row, int n) {
    for (int i = 0; i < tracker_check_count; i++)
        if (!strcmp(tracker_checks[i].area, tracker_name[row]) && tracker_check_shown(i) && !--n) return &tracker_checks[i];
    return nullptr;
}
/// An area's row is hidden: it has checks, and none of them to show
bool tracker_row_hidden(int row) {
    return row >= kTrackerFirstArea && tracker_show != kTrackerShowAll && tracker_row_checks(row, true) > 0 && !tracker_row_checks(row);
}
/// The check a row is stepped to marked junk, or counted again, and the record written (tracker_junk): whether there was one.
/// One a Left list hides now leaves the row on the next it shows, or on its own words
bool tracker_junk_flip(int row) {
    const TrackerCheck* k = tracker_pick[row] ? tracker_row_check(row, tracker_pick[row]) : nullptr;
    if (!k) return false;
    const int i = (int)(k - tracker_checks);
    tracker_junk[i] = !tracker_junk[i];
    if (!tracker_junk_write(tracker_junk_path(), tracker_junk_stamp, tracker_check_count))
        logf("menu: tracker: rando\\junk.txt could not be written");
    logf("menu: tracker: %s of %s %s", k->kind, k->area, tracker_junk[i] ? "marked junk" : "counted again");
    const int shown = tracker_row_checks(row);
    if (tracker_pick[row] > shown) tracker_pick[row] = shown;
    return true;
}
/// What a row says: its own words, or the check it is stepped to ("3 of 10: Chest, child's, at -27 68 65")
std::string tracker_says(int row) {
    const TrackerCheck* k = tracker_pick[row] ? tracker_row_check(row, tracker_pick[row]) : nullptr;
    if (!k) {   // (its own words, how many of its checks are left and how many of those are in logic: the first row is the whole game's)
        if (!row && tracker_forget_asked && GetTickCount64() - tracker_forget_asked < kTrackerForgetMs)
            return "Press again to forget what is collected";
        if (row == kTrackerHomeRow && tracker_check_count)
            return tracker_home_asked && GetTickCount64() - tracker_home_asked < kTrackerForgetMs ? "Press again to go home" : "Kokiri Forest, the Market, or the dungeon's entrance";
        int in = 0, known = 0, left = 0, told = 0, all = 0, junk = 0;
        for (int i = 0; i < tracker_check_count; i++) {
            if (row && strcmp(tracker_checks[i].area, tracker_name[row])) continue;
            all++;
            const int done = tracker_done[i].load(std::memory_order_relaxed);
            told += done >= 0, left += done != 1 && !tracker_junk[i], junk += done != 1 && tracker_junk[i];
            if (done == 1) continue;   // (a check collected is not one to go for)
            if (tracker_junk[i]) continue;   // (nor one marked junk: tracker_junk)
            const int state = tracker_in_logic(tracker_checks[i]);
            known += state >= 0, in += state > 0;
        }
        // (how many are left and how many of those are in logic, and nothing of their kinds: its owner's word. The file's own
        // words only where there is no check to count: no seed)
        const auto checks = [](int n) { return std::to_string(n) + (n == 1 ? " check" : " checks"); };
        if (row == kTrackerShowRow && tracker_check_count) return kTrackerShowWords[tracker_show];
        if (!row && all && told) {   // (the whole game: how far the seed is, and what can be gone for now)
            std::string words = std::to_string(all - left - junk) + " of " + std::to_string(all) + " collected";
            if (junk) words += ", " + std::to_string(junk) + " junk";
            if (known) words += ", " + std::to_string(in) + " in logic now";
            return words;
        }
        std::string words = all ? checks(told ? left : all - junk) + (told ? " left" : "") : std::string(tracker_value[row]);
        if (all && told && !left) words = "All collected";
        else if (all && known) words += ", " + std::to_string(in) + " in logic";
        if (all && junk) words += ", " + std::to_string(junk) + " junk";
        const char* here = row >= kTrackerFirstArea ? tracker_here_area() : nullptr;
        if (here && !strcmp(here, tracker_name[row])) words = "Here: " + words;   // (the area Link is in: the first of them)
        return words;
    }
    const bool collected = tracker_done[k - tracker_checks].load(std::memory_order_relaxed) == 1;
    const bool junk = !collected && tracker_junk[k - tracker_checks];
    const int state = collected || junk ? -1 : tracker_in_logic(*k);
    char text[232], place[48] = "";   // (a check without a name of its own, from a file made before them: its place tells it from the next)
    if (!strcmp(k->kind, "Chest") || !strcmp(k->kind, "Gold Skulltula")) snprintf(place, sizeof place, " at %.0f %.0f %.0f", k->pos[0], k->pos[1], k->pos[2]);
    snprintf(text, sizeof text, "%d of %d: %s%s%s%s%s", tracker_pick[row], tracker_row_checks(row), k->kind,
             !strcmp(k->ages, "C") ? ", child's," : !strcmp(k->ages, "A") ? ", adult's," : "", place,
             collected ? ": done" : state > 0 ? ": in logic" : state == 0 ? ": not in logic" : "", junk ? ": junk" : "");
    return text;
}
/// The help's panel for an area's row: every check of the area that the tab lists, one a line, each with its mark (collected,
/// and then what it gave; in logic; not in logic), the one the row is stepped to lit and kept in view; under them what the
/// marks mean, and the stepped check's own line (hint). From y0 down, no lower than y_max.
void tracker_panel(ui::Ctx& c, float x0, float x1, float y0, float y_max, int row, const char* hint) {
    const float s = c.s, px = 17 * s, pitch = 26 * s, w = x1 - x0 - 48 * s;
    constexpr ImU32 kIn = ui::rgba(120, 224, 150), kOut = ui::rgba(138, 156, 184), kGot = ui::rgba(110, 126, 152);
    constexpr ImU32 kJunk = ui::rgba(92, 102, 120);   // (a junk check: dimmer than one collected, its words struck through)
    struct Line { const TrackerCheck* k; int state; };   // (state: 3 junk, 2 collected, 1 in logic, 0 not, -1 not known)
    std::vector<Line> lines;
    for (int i = 0; i < tracker_check_count; i++) {
        if (strcmp(tracker_checks[i].area, tracker_name[row]) || !tracker_check_shown(i)) continue;
        const bool got = tracker_done[i].load(std::memory_order_relaxed) == 1;
        lines.push_back({&tracker_checks[i], got ? 2 : tracker_junk[i] ? 3 : tracker_in_logic(tracker_checks[i])});
    }
    const int n = (int)lines.size(), pick = tracker_pick[row];
    const float hh = hint ? ui::para(c, c.f.body, 16 * s, ImVec2(), 0, hint, w - 18 * s, false) : 0;
    const float fixed = 22 * s + 32 * s + 12 * s + 24 * s + (hint ? 14 * s + hh : 0) + 20 * s;
    const int fit = std::max(1, std::min(n, (int)((y_max - y0 - fixed) / pitch)));
    const int first = n > fit ? std::clamp(pick - 1 - fit / 2, 0, n - fit) : 0;
    const float y1 = std::min(y0 + fixed + fit * pitch, y_max);
    ui::box(c, ImVec2(x0, y0), ImVec2(x1, y1));
    c.d->PushClipRect(ImVec2(x0, y0), ImVec2(x1, y1), true);
    float y = y0 + 22 * s;
    ui::text(c, c.f.heading, 21 * s, ImVec2(x0 + 24 * s, y), ui::kInk, tracker_name[row]);
    if (n > fit) {   // (more of them than fit: which are shown)
        char range[40];
        snprintf(range, sizeof range, "%d-%d of %d", first + 1, first + fit, n);
        ui::text_mid(c, c.f.body, 15 * s, x1 - 24 * s - ui::size_of(c.f.body, 15 * s, range).x, y + 12 * s, ui::kDim, range);
    }
    y += 32 * s;
    const auto mark = [&](float mx, float my, int state) {
        if (state == 2) {   // (collected: a tick)
            c.d->AddLine(ImVec2(mx - 5 * s, my), ImVec2(mx - 1.5f * s, my + 4 * s), kGot, 2 * s);
            c.d->AddLine(ImVec2(mx - 1.5f * s, my + 4 * s), ImVec2(mx + 5.5f * s, my - 4.5f * s), kGot, 2 * s);
        } else if (state == 3) {   // (junk: a cross)
            c.d->AddLine(ImVec2(mx - 4 * s, my - 4 * s), ImVec2(mx + 4 * s, my + 4 * s), kJunk, 1.8f * s);
            c.d->AddLine(ImVec2(mx - 4 * s, my + 4 * s), ImVec2(mx + 4 * s, my - 4 * s), kJunk, 1.8f * s);
        } else if (state == 1) c.d->AddCircleFilled(ImVec2(mx, my), 5 * s, kIn);
        else if (state == 0) c.d->AddCircle(ImVec2(mx, my), 4.5f * s, kOut, 0, 1.6f * s);
        else c.d->AddLine(ImVec2(mx - 4 * s, my), ImVec2(mx + 4 * s, my), kOut, 1.6f * s);
    };
    for (int i = first; i < first + fit && i < n; i++, y += pitch) {
        const Line& l = lines[i];
        if (i + 1 == pick) c.d->AddRectFilled(ImVec2(x0 + 14 * s, y - 2 * s), ImVec2(x1 - 14 * s, y + pitch - 4 * s), ui::kCellNameSel, 4 * s);
        mark(x0 + 32 * s, y + pitch * 0.5f - 3 * s, l.state);
        std::string text = l.k->kind;
        if (!strcmp(l.k->ages, "C")) text += " (child)";
        else if (!strcmp(l.k->ages, "A")) text += " (adult)";
        const ImU32 col = l.state == 3 ? kJunk : l.state == 2 ? kGot : l.state == 1 ? ui::kInkBright : ui::kSoft;
        const float tx = x0 + 48 * s, ty = y + pitch * 0.5f - 3 * s;
        c.d->PushClipRect(ImVec2(tx, y), ImVec2(x1 - 20 * s, y + pitch), true);
        const float end = tx + ui::text_mid(c, c.f.body, px, tx, ty, col, text.c_str());   // (text_mid: the words' width)
        if (l.state == 3) c.d->AddLine(ImVec2(tx - 2 * s, ty), ImVec2(end + 2 * s, ty), kJunk, 1.5f * s);   // (junk: struck through)
        if (l.state == 2 && l.k->gives[0])   // (what it gave, once it is collected)
            ui::text_mid(c, c.f.body, px, end + 10 * s, ty, ui::kSoft, tracker_item_name(l.k->gives).c_str());
        c.d->PopClipRect();
    }
    y += 12 * s;
    {   // (what the marks mean)
        float lx = x0 + 32 * s;
        const struct { int state; const char* says; } legend[] = {{1, "in logic"}, {0, "not yet"}, {2, "collected"}, {3, "junk"}};
        for (const auto& e : legend) {
            mark(lx, y + 8 * s, e.state);
            lx += 12 * s + ui::text_mid(c, c.f.body, 14 * s, lx + 12 * s, y + 8 * s, ui::kDim, e.says) + 26 * s;
        }
    }
    if (hint) {
        const float hy = y + 24 * s + 14 * s;
        c.d->AddRectFilled(ImVec2(x0 + 24 * s, hy + 2 * s), ImVec2(x0 + 26.5f * s, hy + hh - 2 * s), ui::kAccent, s);
        ui::para(c, c.f.body, 16 * s, ImVec2(x0 + 40 * s, hy), ui::kSoft, hint, w - 18 * s);
    }
    c.d->PopClipRect();
}
/// The help's last line for a row stepped to a check: in logic, or what Link still needs for it
std::string tracker_hint(int row) {
    const TrackerCheck* k = tracker_pick[row] ? tracker_row_check(row, tracker_pick[row]) : nullptr;
    std::string missing;
    if (k && tracker_done[k - tracker_checks].load(std::memory_order_relaxed) == 1)
        return k->gives[0] ? "Collected: it gave " + tracker_item_name(k->gives) + "." : std::string("Collected: its item was given to Link here.");
    if (k && tracker_junk[k - tracker_checks]) return "Junk: not counted among the checks left. Mark it again to count it.";
    const int state = k ? tracker_in_logic(*k, &missing) : -1;
    std::string says = state > 0 ? "In logic: Link carries all the seed's rules ask for here." : state == 0 ? "Not in logic. Still asked for: " + missing + "." : "";
    if (k && k->hash[0]) {   // (and the way there, where Ocarina Atlas describes it: tracker_ways)
        const auto way = tracker_ways.find(k->hash);
        if (way != tracker_ways.end()) says += (says.empty() ? "" : "\n") + std::string("How to get there: ") + way->second;
    }
    return says;
}
/// A row's hints from a table, the value lo first (nullptr: none for that value)
const char* hint_in(const char* const* t, int n, int lo, int v, int variant) {
    return variant <= 0 && v - lo >= 0 && v - lo < n ? t[v - lo] : nullptr;
}
#define MENU_HINTS(fn, lo, ...)                                                                                              \
    const char* fn(int v, int variant) {                                                                                     \
        static const char* const t[] = {__VA_ARGS__};                                                                        \
        return hint_in(t, (int)(sizeof t / sizeof t[0]), lo, v, variant);                                                    \
    }
const char* tx_framegen(int v) {
    static const char* t[] = {"Off", "Auto", "2x", "3x", "4x", "5x", "6x", "7x", "8x"};
    return t[v];
}
const char* tx_onoff(int v) { return v ? "On" : "Off"; }
const char* tx_fps_level(int v) { return fps_stats::level_name(v); }
const char* tx_fps_corner(int v) { return fps_stats::corner_name(v); }
const char* tx_fps_size(int v) {   // (the FPS counter size row: Auto, then the Menu size row's names)
    static const char* t[] = {"Auto", "Small", "Medium", "Large"};
    return v >= 0 && v <= 3 ? t[v] : t[0];
}
const char* tx_profile(int v) { return v ? "Handheld" : "Docked"; }   // (opts.handheld: the Profile row)
const char* tx_menu_shortcut(int v) {
    // (F1 is never turned off: the menu is always one key away. Esc as well, as a PC game's pause menu)
    static const char* const names[] = {"Insert or F1", "F1 only", "Insert, F1 or Esc"};
    return names[std::clamp(v, 0, 2)];
}
const char* tx_compact_menu_key(int v) {
    static const char* const names[] = {"Right Shift", "Right Ctrl"};
    return names[std::clamp(v, 0, 1)];
}
const char* tx_hdr(int v) { return v == 1 ? "Expanded" : v == 2 ? "Native (the game's)" : "Off"; }
const char* tx_tonemap(int v) { return v == 1 ? "PsychoV35" : "Vanilla"; }
const char* tx_nits(int v) {
    static char b[24];
    snprintf(b, sizeof b, "%d nits", v);
    return b;
}
const char* tx_fps_cap(int v) {
    if (v == -1) return "30";
    static const char* const t[] = {"60 (the console's)", "90", "120", "144", "165", "240", "Uncapped"};
    return t[v < 0 ? 0 : v > 6 ? 6 : v];
}
// (hookshot) Motion controls: the choice, and whether a connected controller has a gyroscope (host/pad_sdl.c). Either can be
// chosen whatever is connected: a pad plugged in later is read when it comes
const char* tx_gyro(int v) {
    const int status = host && host->gyro_status ? host->gyro_status() : -1;
    if (status == 2) return v ? "On (gyro found)" : "Off (gyro found)";
    if (status == 1) return v ? "On (no gyro on this pad)" : "Off (no gyro on this pad)";
    if (status == 0) return v ? "On (no controller)" : "Off (no controller)";
    return v ? "On" : "Off";
}
const char* tx_mousecam(int v) { return v == 2 ? "Off" : v ? "Native" : "As the stick"; }
const char* tx_sens(int v) {
    static char b[12];
    snprintf(b, sizeof b, "%.2f", v / 100.0);
    return b;
}
// (the game's picture and the window it is shown in, as the last present had them: menu_note_present_sizes)
std::atomic<uint64_t> present_sizes{0};
bool filter_needed() {
    const uint64_t v = present_sizes.load(std::memory_order_relaxed);
    return upscaler_rows::filter_needed((unsigned)(v >> 48), (unsigned)(v >> 32) & 0xffff, (unsigned)(v >> 16) & 0xffff,
                                        (unsigned)v & 0xffff);
}
const char* tx_upscale(int v) {
    static const char* t[] = {"Off", "Catmull-Rom", "Lanczos"};
    if ((unsigned)v >= sizeof t / sizeof t[0]) return t[0];   // (a setting past the row: the label, not the next bytes)
    return t[v];
}
/// The Window scaling filter row's value: its filter, or that none is needed (the saved value stays, for another window size)
const char* tx_filter(int v) { return filter_needed() ? tx_upscale(v) : "Not needed (window = output)"; }
const char* tx_crt_filter(int v) {
    static const char* const t[] = {"Off", "Lottes aperture grille", "Lottes consumer TV", "Hyllian Fast", "zfast CRT"};
    return (unsigned)v < std::size(t) ? t[v] : t[0];
}
const char* tx_crt_lines(int v) {
    static const char* const t[] = {"240", "480", "720"};
    return (unsigned)v < std::size(t) ? t[v] : t[0];
}
const char* tx_reflex(int v) {
    static const char* t[] = {"Off", "On", "On + Boost"};
    return t[reflex_available() ? std::clamp(v, 0, 2) : 0];
}
/// Reflex: on the value (the row is shown only where Reflex runs: row_shown)
const char* hn_reflex(int v, int variant) {
    static const char* const t[] = {"The game as without it.", "The driver paces the frames for less latency.",
                                    "As On, and the GPU's clocks are kept up as well."};
    return variant <= 0 ? t[std::clamp(v, 0, 2)] : nullptr;
}
const char* tx_antilag(int v) { return antilag_available() && v ? "On" : "Off"; }
/// Anti-Lag 2: on the value (the row is shown only where Anti-Lag 2 runs: row_shown)
const char* hn_antilag(int v, int variant) {
    static const char* const t[] = {"The game as without it.", "The driver delays each frame's start for less latency."};
    return variant <= 0 ? t[v ? 1 : 0] : nullptr;
}
// The Upscaler (opts.dlss): what scales the 3D up to the output. DLSS and DLAA only where dlss_why() lets them run, FSR 3.1
// only where vk_fsr3.cpp says it does, FSR 4 and its native AA only where fsr4_why() does, Intel XeSS and its Native AA only
// where xess_why() does, Off (no upscaler: vk_temporal.cpp temporal_off) everywhere; the menu shows (and steps from) what runs,
// and keeps the saved choice for a PC where it can
namespace ur = upscaler_rows;
/// One bit per upscaler that runs here (upscaler_rows.h bit). Each backend caches its own answer, so this costs nothing
unsigned upscalers_available() {
    return ur::bit(ur::GAME) | ur::bit(ur::OFF) | ur::dlss_bits(dlss_why() == DLSS_OK) |
           (fsr3::supported() ? ur::bit(ur::FSR3) : 0u) | ur::fsr4_bits(fsr4_why() == FSR_OK) |
           ur::xess_bits(xess_why() == XESS_OK);
}
/// (FSR 3.1 has inputs of its own; DLSS, FSR 4 and XeSS run on the frame chain they share, temporal_mode; Off is neither)
int upscaler() { return fsr3_wanted() ? (int)ur::FSR3 : temporal_off() ? (int)ur::OFF : temporal_mode(); }
const char* tx_upscaler(int) {
    static const char* t[ur::kUpscalers] = {"Game's own", "NVIDIA DLSS", "NVIDIA DLAA", "AMD FSR 3.1", "AMD FSR 4",
                                            "AMD FSR 4 Native AA", "Off (no upscaling)", "Intel XeSS", "Intel XeSS Native AA"};
    // (by engine: DLAA and FSR 4's and XeSS's native AA are the Render resolution row's Native, upscaler_rows.h engine)
    return t[std::clamp(ur::engine(upscaler()), 0, ur::kUpscalers - 1)];
}
/// Why DLSS and DLAA do not run here (vk_dlss.h DlssWhy), for the Upscaler row and Frame generation by; nullptr for DLSS_OK
const char* dlss_why_text(int why) {
    static const char* const t[DLSS_WHY_COUNT] = {
        nullptr,
        "DLSS and DLAA: not in this build (built without NVIDIA's DLSS SDK, see the readme).",
        "DLSS and DLAA: off for this run (RX_VK_DLSS=0).",
        "DLSS and DLAA: need an NVIDIA RTX GPU.",
        "DLSS and DLAA: need a newer NVIDIA driver.",
        "DLSS and DLAA: DLSS's runtime was not found (the game folder's ngx folder, see the readme).",
        "DLSS and DLAA: NVIDIA's NGX on Linux loads DLSS's runtime only from a folder named in ASCII (see the readme).",
    };
    return why > 0 && why < DLSS_WHY_COUNT ? t[why] : nullptr;
}
/// The Upscaler: the one shown (what runs, upscaler()), and with the game's own, why DLSS, FSR and XeSS are not offered.
/// Variants (every one): each value, then the game's own with each of DLSS's reasons, then with each of FSR's, then XeSS's
const char* hn_upscaler(int v, int variant) {
    static const char* const t[ur::kUpscalers] = {
        "The game's own network.",
        "NVIDIA's, from a smaller 3D. Softer than the game's own: set Sharpness to around 80%. Things that move by "
        "themselves can trail for now.",
        "NVIDIA's, the 3D at full size with its edges smoothed; the slowest. Softer than the game's own: set Sharpness to "
        "around 80%. Things that move by themselves can trail for now.",
        "AMD's, from a smaller 3D, on any GPU: built from AMD's own shaders. Things that move by themselves can trail for "
        "now.",
        "AMD's machine-learned upscaler, from a smaller 3D, with AMD's files beside the game. Things that move by themselves "
        "can trail for now.",
        "AMD's machine-learned upscaler, the 3D at full size with its edges smoothed; the slowest.",
        "No upscaler, not even the game's network: the 3D is stretched to the output with a plain linear filter. The "
        "fastest choice and the roughest picture: no edge smoothing, and softer below 100%.",
        "Intel's machine-learned upscaler, from a smaller 3D, with Intel's libxess.dll beside the game. Things that move by "
        "themselves can trail for now.",
        "Intel's machine-learned upscaler, the 3D at full size with its edges smoothed; the slowest.",
    };
    static const char* const fsr_no[FSR_WHY_COUNT] = {
        nullptr,
        "AMD FSR 4: not in this build (see the readme).",
        "AMD FSR 4: off for this run (RX_VK_FSR4=0).",
        "AMD FSR 4: AMD's files were not found beside the game (see the readme).",
        "AMD FSR 4: AMD's files have no FSR 4 for this GPU.",
    };
    static const char* const xess_no[XESS_WHY_COUNT] = {
        nullptr,
        "Intel XeSS: Windows only (Intel makes no XeSS library for Linux).",
        "Intel XeSS: off for this run (RX_VK_XESS=0).",
        "Intel XeSS: Intel's libxess.dll was not found beside the game (see the readme).",
        "Intel XeSS: the GPU or its Vulkan driver lacks what XeSS needs.",
        "Intel XeSS: Intel's library does not run on this GPU or driver.",
    };
    // (now: the value shown and what runs here, with every engine's reasons; every one: as said above)
    int d = 0, f = 0, x = 0;
    if (variant < 0) {
        v = std::clamp(upscaler(), 0, ur::kUpscalers - 1), d = (int)dlss_why(), f = (int)fsr4_why(), x = (int)xess_why();
    } else if (v == ur::GAME) {
        if (variant < DLSS_WHY_COUNT) d = variant;
        else if (variant < DLSS_WHY_COUNT + FSR_WHY_COUNT - 1) f = variant - DLSS_WHY_COUNT + 1;
        else if (variant < DLSS_WHY_COUNT + FSR_WHY_COUNT + XESS_WHY_COUNT - 2) x = variant - DLSS_WHY_COUNT - FSR_WHY_COUNT + 2;
        else return nullptr;
    } else if (variant > 0) {
        return nullptr;
    }
    v = std::clamp(v, 0, ur::kUpscalers - 1);
    // (the reasons are said only where the engine is in the build: one without FSR does not tell an NVIDIA user why, and a
    // Linux build does not tell anyone that XeSS is Windows only)
    const char* dn = dlss_built() || variant >= 0 ? dlss_why_text(d) : nullptr;
    const char* fn = fsr4_built() || variant >= 0 ? fsr_no[f] : nullptr;
    const char* xn = xess_built() || variant >= 0 ? xess_no[x] : nullptr;
    if (v != ur::GAME || (!dn && !fn && !xn)) return t[v];
    static char b[DLSS_WHY_COUNT][FSR_WHY_COUNT][XESS_WHY_COUNT][400];
    snprintf(b[d][f][x], sizeof b[d][f][x], "%s%s%s%s%s%s%s", t[0], dn ? " " : "", dn ? dn : "", fn ? " " : "", fn ? fn : "",
             xn ? " " : "", xn ? xn : "");
    return b[d][f][x];
}
/// The DLSS model row (opts.dlss_model): NVIDIA's network by its preset (the K row's E on a card with less than 7 GB of video
/// memory: upscaler_rows.h cnn_for_vram, as DLSS is made), or RX_VK_DLSS_PRESET's for this run
const char* dlss_preset_env() {
    static const char* const e = getenv("RX_VK_DLSS_PRESET");
    return ur::preset_env(e) ? e : nullptr;
}
const char* tx_dlss_model(int v) {
    static const char* const t[] = {"Transformer (K)", "Transformer 2 (M)", "Transformer 2 (L)", "NVIDIA default", "CNN (E)", "CNN (F)"};
    if (const char* e = dlss_preset_env()) {
        static char b[48];
        const unsigned p = ur::dlss_preset(v, e);
        if (p) snprintf(b, sizeof b, "Preset %c (RX_VK_DLSS_PRESET)", ur::preset_letter(p));
        else snprintf(b, sizeof b, "NVIDIA default (RX_VK_DLSS_PRESET)");
        return b;
    }
    if (ur::cnn_for_vram(v, device_vram_bytes())) return "CNN (E)";
    return t[std::clamp(v, 0, ur::kModels - 1)];
}
/// The DLSS model: the value chosen (the K row's on a card under 7 GB: why it is E); variant 1: the game's own upscales (the
/// row waits for DLSS or DLAA); variant 2: set for this run by RX_VK_DLSS_PRESET
const char* hn_dlss_model(int v, int variant) {
    static const char* const t[] = {
        "NVIDIA's transformer model: the one tested most here.",
        "NVIDIA's second-generation transformer, its pick for Performance: sharper, at a little more GPU time.",
        "The second-generation transformer as NVIDIA tuned it for Ultra Performance, the smallest Render resolutions.",
        "Lets DLSS's runtime pick for each mode: what it picks can change with a runtime update.",
        "NVIDIA's lightweight CNN model: uses ~59 MB VRAM and runs faster on constrained RTX GPUs.",
        "NVIDIA's lightweight CNN model tuned for DLAA and Ultra Performance (~59 MB VRAM).",
    };
    static const char* const unused = "Used by NVIDIA DLSS and DLAA: choose one in the Upscaler row.";
    static const char* const env = "Set for this run by RX_VK_DLSS_PRESET.";
    static const char* const cnn = "NVIDIA's CNN model, chosen for graphics cards with less than 7 GB of memory: less video "
                                   "memory and GPU time than the transformer.";
    if (variant < 0) variant = dlss_preset_env() ? 2 : upscaler() == ur::GAME || upscaler() == ur::OFF ? 1 : 0;
    if (variant == 1) return unused;
    if (variant == 2) return env;
    if (variant == 0 && ur::cnn_for_vram(v, device_vram_bytes())) return cnn;
    return variant == 0 ? t[std::clamp(v, 0, ur::kModels - 1)] : nullptr;
}
/// The Game language row (opts.game_lang): language.txt's language, written once the row is left (game_lang_tick); the game
/// reads it at its start
const char* tx_game_lang(int v) { return i18n::game_lang_name(v); }
/// The Menu language row (opts.menu_lang): Auto, then each language by its own name (vk_menu_i18n.h)
const char* tx_menu_lang(int v) {
    if (v <= 0) return "Auto (game's language)";
    return i18n::lang_name(v - 1);
}
const char* hn_menu_lang(int v, int variant) {
    if (variant > 0) return nullptr;
    return v <= 0 ? "Follows the game's language (language.txt in the game folder)." : "The language of this menu.";
}
bool mic_testing = false; // session only, never saved or restored
int mic_levels[2] = {}, mic_test_state = 0;
constexpr const char* kMicLevelHelp =
    "Shows microphone signal strength, not note recognition.\n\n"
    "- First percentage: incoming peak before gain.\n"
    "- Second percentage: peak after Microphone gain, also shown by the bar.\n\n"
    "At 100% gain they match. Increasing gain also raises noise and can clip the signal.";
const char* tx_percent(int v) {
    static char b[8];
    snprintf(b, sizeof b, "%d%%", v);
    return b;
}
/// The host's screen: the main one, whose shape host/hos_main.c gives a 16:9 Output resolution at the start with ultrawide=1
/// (Windows: the primary's size; Linux: SDL's primary desktop, MkwVkHost.screen_size): false where it is not known
bool host_screen_size(uint32_t* w, uint32_t* h) {
#ifdef _WIN32
    const int sw = GetSystemMetrics(SM_CXSCREEN), sh = GetSystemMetrics(SM_CYSCREEN);
    if (sw > 0 && sh > 0) return *w = (uint32_t)sw, *h = (uint32_t)sh, true;
#endif
    int hw = 0, hh = 0;
    if (host && host->screen_size && host->screen_size(&hw, &hh) && hw > 0 && hh > 0)
        return *w = (uint32_t)hw, *h = (uint32_t)hh, true;
    return false;
}
#ifdef _WIN32
/// The monitor the game's window is on (the nearest), with its size; false before there is a window
bool window_monitor(MONITORINFOEXW& mi) {
    const HWND wnd = app_window();
    mi = {};
    mi.cbSize = sizeof mi;
    return wnd && GetMonitorInfoW(MonitorFromWindow(wnd, MONITOR_DEFAULTTONEAREST), &mi) && mi.rcMonitor.right > mi.rcMonitor.left &&
           mi.rcMonitor.bottom > mi.rcMonitor.top;
}
#endif
/// The screen the Aspect ratio and Output resolution rows mark ("(monitor's)", "(native)"): the one the game's window is on,
/// its size now (a desktop size changed while running is followed: outputs_follow_screen); the host's before there is a
/// window, and on Linux. False where neither is known
bool screen_size(uint32_t* w, uint32_t* h) {
#ifdef _WIN32
    MONITORINFOEXW mi;
    if (window_monitor(mi))
        return *w = (uint32_t)(mi.rcMonitor.right - mi.rcMonitor.left), *h = (uint32_t)(mi.rcMonitor.bottom - mi.rcMonitor.top), true;
#endif
    return host_screen_size(w, h);
}
/// That screen's display modes, each as Windows lists it (every refresh rate and depth: display_modes.h keeps each size once);
/// the primary's before there is a window; none where they are not known (Linux)
std::vector<display_modes::Size> screen_modes() {
    std::vector<display_modes::Size> v;
#ifdef _WIN32
    MONITORINFOEXW mi;
    const wchar_t* device = window_monitor(mi) ? mi.szDevice : nullptr;
    DEVMODEW m{};
    m.dmSize = sizeof m;
    for (DWORD i = 0; EnumDisplaySettingsW(device, i, &m); i++) v.push_back({(uint32_t)m.dmPelsWidth, (uint32_t)m.dmPelsHeight});
#endif
    return v;
}
// The output the menu's sizes are shown for: the Output resolution row's (applied at the next start), so the rows below follow a change
// at once; the Handheld profile runs the game's own (1536x864)
struct Out {
    uint32_t w, h;
};
namespace dm = display_modes;
// The Output resolution's choices: 0 the game's own (2048x1152), then the sizes the main screen offers (display_modes.h: its
// display modes and its own size, each side rounded down to 8, those the game accepts, with the common sizes of the shapes
// they have, 1440p, 4K and 5K at 16:9 on a 1080p screen too, by width then height; HOS_DISPLAY_MODES=<w>x<h>,... for a run;
// where they are not known, the sizes offered before: 1920x1080, 2560x1440, 3840x2160, 5120x1440, 5120x2880), then, last,
// a size of the player's own from hookshot_options.ini (output_res=<width>x<height>, host/nn_applet.c hos_output_parse: the
// same rules) when it is none of them. The ini keeps the size, not the choice's number: output_res=3840x2160
constexpr Out kGameOutput{2048, 1152};
// (the sizes offered before the screen's: output_res=0 to 5 as saved then, and where the screen's are not known, by width then
// height. nx2/pipeline_share.py OUTPUTS mirrors it)
constexpr Out kOutputs[] = {{2048, 1152}, {2560, 1440}, {3840, 2160}, {1920, 1080}, {5120, 1440}, {5120, 2880}};
Out outputs_screen{0, 0};   // (the window's screen's size the choices were read for: outputs_follow_screen)
/// A screen's own size among the modes, and its shape at the most pixels a picture of another shape takes when the size itself
/// is past what the game accepts: a 7680x2160 32:9 screen gets 6256x1760, so its shape is still offered
void add_screen_size(std::vector<dm::Size>& modes, uint32_t sw, uint32_t sh) {
    modes.push_back({sw, sh});
    unsigned w = 0, h = 0;
    if (sh && !hos_output_size_valid(sw & ~7u, sh & ~7u)) {
        hos_wide_size(sh, hos_wide_clamp((double)sw / sh), hos_wide_max_px(), &w, &h);
        if (dm::ratio_name({w, h}) == dm::ratio_name({sw, sh})) modes.push_back({w, h});
    }
}
const std::vector<Out>& outputs() {
    static const std::vector<Out> v = [] {
        const char* e = getenv("HOS_DISPLAY_MODES");
        std::vector<Out> o{kGameOutput};
        std::vector<dm::Size> modes = e ? dm::parse_list(e) : screen_modes();
        if (!e) {
            uint32_t sw = 0, sh = 0, hw = 0, hh = 0;
            const bool screen = screen_size(&sw, &sh), host_screen = host_screen_size(&hw, &hh);
            // (no modes but a screen's size (Linux): the sizes offered before, with the screen's)
            if (modes.empty() && (screen || host_screen))
                for (int i = 1; i < (int)std::size(kOutputs); i++) modes.push_back({kOutputs[i].w, kOutputs[i].h});
            if (screen) add_screen_size(modes, sw, sh), outputs_screen = {sw, sh};
            if (host_screen) add_screen_size(modes, hw, hh);   // (the host's shape, which ultrawide=1 gives a 16:9 size)
        }
        for (dm::Size s : dm::with_common(dm::offered(modes)))
            if (!(s.w == kGameOutput.w && s.h == kGameOutput.h)) o.push_back({s.w, s.h});
        if (o.size() == 1) {
            o.insert(o.end(), std::begin(kOutputs) + 1, std::end(kOutputs));
            std::sort(o.begin() + 1, o.end(), [](Out a, Out b) { return a.w != b.w ? a.w < b.w : a.h < b.h; });
        }
        return o;
    }();
    return v;
}
int custom_index() { return (int)outputs().size(); }   // (the player's own size's choice: after the sizes offered)
Out custom_output{0, 0};   // (the player's own size; 0 x 0: none)
// (a screen's sizes found while running, the window moved to another monitor or its desktop size changed: after the player's
// own, so the choices' numbers before them keep their sizes; outputs_follow_screen)
std::vector<Out> output_extras;
int last_choice() { return custom_index() + (int)output_extras.size(); }
int output_choice(int v) {
    const int c = custom_index();
    return v >= 0 && (v < c || (v == c && custom_output.w) || (v > c && v <= last_choice())) ? v : 0;
}
Out output_at(int v) {
    v = output_choice(v);
    const int c = custom_index();
    return v < c ? outputs()[v] : v == c ? custom_output : output_extras[v - c - 1];
}
/// The choice of size w x h: one of the sizes offered (or found since), else the player's own from now on
int output_choice_of(uint32_t w, uint32_t h) {
    for (int i = 0; i < custom_index(); i++)
        if (outputs()[i].w == w && outputs()[i].h == h) return i;
    for (int i = 0; i < (int)output_extras.size(); i++)
        if (output_extras[i].w == w && output_extras[i].h == h) return custom_index() + 1 + i;
    custom_output = {w, h};
    return custom_index();
}
/// output_res= (or HOS_OUTPUT_RES) to a choice: "<width>x<height>" (each side a multiple of 8, rounded down; at least 640 x 360,
/// at most 5120 x 2880's pixels, 5:4 to 48:9), one of the sizes offered or the player's own (custom_output); the numbers saved
/// before (0 to 5: 2048x1152, 2560x1440, 3840x2160, 1920x1080, 5120x1440, 5120x2880) as those sizes; anything else the game's
/// own (host/nn_applet.c hos_output_parse: the same rules)
int parse_output(const char* text) {
    unsigned w = 0, h = 0;
    if (text && sscanf(text, "%u%*[xX]%u", &w, &h) == 2) {
        w &= ~7u, h &= ~7u;
        if (!hos_output_size_valid(w, h))
            return 0;
        return output_choice_of(w, h);
    }
    const int v = text ? atoi(text) : 0;
    return v >= 1 && v < (int)std::size(kOutputs) ? output_choice_of(kOutputs[v].w, kOutputs[v].h) : 0;
}
dm::Size size_of(Out o) { return {o.w, o.h}; }
/// Every choice there is, in order (the player's own when there is one, then the sizes found while running)
std::vector<int> output_ids() {
    std::vector<int> v;
    for (int i = 0; i <= last_choice(); i++)
        if (output_choice(i) == i) v.push_back(i);
    return v;
}
/// Their sizes, in the same order
std::vector<dm::Size> output_sizes() {
    std::vector<dm::Size> v;
    for (int i : output_ids()) v.push_back(size_of(output_at(i)));
    return v;
}
/// The shapes of the choices, narrowest first: made again only when the player's own size changes (the sizes offered are
/// fixed once read), as the rows ask for them at every frame they are drawn
const std::vector<dm::Shape>& output_shapes() {
    static std::vector<dm::Shape> v;
    static Out made_for{~0u, ~0u};
    static size_t extras = ~size_t(0);
    if (made_for.w != custom_output.w || made_for.h != custom_output.h || extras != output_extras.size())
        v = dm::shapes(output_sizes()), made_for = custom_output, extras = output_extras.size();
    return v;
}
/// The shape (a place in output_shapes) of choice v
int output_shape_of(int v) { return dm::shape_index(output_shapes(), size_of(output_at(v))); }
/// The monitor's shape: the main screen's (as host/hos_main.c takes it), when it is one of output_shapes; "" where the screen's
/// size is not known (Linux) or its shape is not offered (a portrait screen): the row then has a Monitor's shape value of its own
std::string monitor_shape() {
    uint32_t sw = 0, sh = 0;
    if (!screen_size(&sw, &sh)) return std::string();
    const std::string name = dm::ratio_name({sw, sh});
    for (const dm::Shape& s : output_shapes())
        if (s.name == name) return name;
    return std::string();
}
/// The Aspect ratio row's values: output_shapes' places, the monitor's own marked; where monitor_shape is not known, one more
/// after them, Monitor's shape (ultrawide=1 with a 16:9 size, as host/hos_main.c takes the screen's shape), as on main
int aspect_monitor_value() { return monitor_shape().empty() ? (int)output_shapes().size() : -1; }
int aspect_last() { return std::max(0, (int)output_shapes().size() - 1 + (aspect_monitor_value() >= 0 ? 1 : 0)); }
/// The shape the Aspect ratio row's value v names (Monitor's shape where the monitor's is not known: 16:9 sizes)
std::string aspect_shape(int v) {
    const std::vector<dm::Shape>& shapes = output_shapes();
    if (shapes.empty() || v == aspect_monitor_value()) return std::string("16:9");
    return shapes[std::clamp(v, 0, (int)shapes.size() - 1)].name;
}
/// The row's value for shape name (16:9's when it is not one of them)
int aspect_index(const std::string& name) {
    const std::vector<dm::Shape>& shapes = output_shapes();
    for (int i = 0; i < (int)shapes.size(); i++)
        if (shapes[i].name == name) return i;
    for (int i = 0; i < (int)shapes.size(); i++)
        if (shapes[i].name == "16:9") return i;
    return 0;
}
/// Whether the row's value v is the monitor's shape: the window's screen's, marked "(monitor's)"
bool aspect_is_monitors(int v) {
    const std::string m = monitor_shape();
    return m.empty() ? v == aspect_monitor_value() : aspect_shape(v) == m;
}
/// The host's screen's shape when it is one of output_shapes ("" otherwise): what ultrawide=1 gives a 16:9 size at the start
std::string host_shape() {
    uint32_t w = 0, h = 0;
    if (!host_screen_size(&w, &h)) return std::string();
    const std::string name = dm::ratio_name({w, h});
    for (const dm::Shape& s : output_shapes())
        if (s.name == name) return name;
    return std::string();
}
/// Whether the row's value v is saved as ultrawide=1: the host's shape (a 16:9 size then takes it at the next start, as it
/// shows), or Monitor's shape where the monitor's is not known. The same as the mark where the window is on the host's screen
bool aspect_follows_host(int v) {
    if (v == aspect_monitor_value()) return true;
    const std::string h = host_shape();
    return h.empty() ? aspect_is_monitors(v) : aspect_shape(v) == h;
}
/// The Aspect ratio row's value for Output resolution choice v: a size of a shape of its own is that shape; a 16:9 one is the
/// monitor's shape when ultrawide (0 or 1, as host/hos_main.c started with it) follows the monitor, else 16:9
int aspect_of_choice(int v, int ultrawide) {
    const Out o = output_at(v);
    if (hos_output_own_shape(o.w, o.h)) return aspect_index(dm::ratio_name(size_of(o)));
    if (ultrawide != 1) return aspect_index("16:9");
    const std::string h = host_shape(), m = monitor_shape();   // (the shape the host gives it: its screen's)
    return !h.empty() ? aspect_index(h) : m.empty() ? aspect_monitor_value() : aspect_index(m);
}
/// The Aspect ratio row's value that choice v needs (the control bridge, before it walks the Output resolution to a size of
/// another shape): its own shape; a 16:9 size, 16:9 itself, not the monitor's shape the row may be at
int aspect_for_choice(int v) { return aspect_of_choice(v, 0); }
/// The shape the Output resolution's arrows walk from choice id: its own; but a 16:9 size kept from before at the host's
/// shape (ultrawide=1, the host widening it) walks into that shape's own sizes, the list the Aspect ratio row names
std::string step_shape(int id) {
    const std::string own = dm::ratio_name(size_of(output_at(id))), h = aspect_shape(opts.ultrawide);
    return own == "16:9" && h != own && opts.ultrawide != aspect_monitor_value() && aspect_follows_host(opts.ultrawide) ? h : own;
}
Out picture_for(int v, bool* native);
// (the choices of id's shape (step_shape), from smallest to largest by the size each shows (picture_for), width then height:
// 1920x1080, 2048x1152, 2560x1440, 3840x2160 at 16:9, the player's own in its place; id itself among them. A 16:9 size walked
// at the host's wider shape is where its picture is: the game's own 2048x1152 at a 5120x2160 screen's 21:9 draws 2728x1152,
// between 2560x1080 and 3008x1264, not before them, and reached from either. What is saved is the choice, as before)
int step_output_choice(int id, int dir) {
    const std::string shape = step_shape(id);
    std::vector<std::pair<Out, int>> order;
    for (int i = 0; i <= last_choice(); i++) {
        if (output_choice(i) != i) continue;
        const Out shown = picture_for(i, nullptr);
        // (the game's own is in the walk of the shape it is drawn at, as its row shows it)
        if (i == output_choice(id) || dm::ratio_name(size_of(output_at(i))) == shape || (i == 0 && dm::ratio_name(size_of(shown)) == shape))
            order.push_back({shown, i});
    }
    std::stable_sort(order.begin(), order.end(), [](const std::pair<Out, int>& a, const std::pair<Out, int>& b) {
        return a.first.w != b.first.w ? a.first.w < b.first.w : a.first.h < b.first.h;
    });
    int at = 0;
    while (at < (int)order.size() && order[at].second != output_choice(id)) at++;
    return order[std::clamp(at + dir, 0, (int)order.size() - 1)].second;
}
/// The Output resolution the Aspect ratio row's value v takes: the one the game started with at its shape; the one chosen when
/// it has that shape; else the screen's own size when it has it; else the one whose height is nearest the screen's
/// (display_modes.h pick)
int aspect_started = -1;   // (the Aspect ratio row's value at the start, from the size the run started with: outputs_sync)
int output_started = 0;    // (the Output resolution the run started with)
int output_for_aspect(int v) {
    // (back at the shape the game started with: the size it started with, so nothing is left to restart for. A first start on a
    // 21:9 screen is 21:9 with the game's own size, which ultrawide=1 widens: stepping away and back took 5120x2160 (native))
    if (v == aspect_started && output_choice(output_started) == output_started) return output_started;
    const std::string name = aspect_shape(v);
    if (dm::ratio_name(size_of(output_at(opts.output_res))) == name) return opts.output_res;
    uint32_t sw = 0, sh = 0;
    screen_size(&sw, &sh);
    const int i = dm::pick(output_sizes(), name, {sw & ~7u, sh & ~7u});
    return i < 0 ? opts.output_res : output_ids()[i];
}
/// The picture an Output resolution choice makes: a size not 16:9 (the Aspect ratio row's 21:9, 16:10, 4:3...) takes its own
/// shape; a 16:9 one, at the monitor's own Aspect ratio, the screen's. Both keep at most hos_wide_max_px() pixels, matching
/// host/hos_main.c at startup (host/hos_wide_size.h); otherwise the 16:9 output. The game's own choice (0) as the game draws it,
/// its 2048x1152 widened the same way (2728x1152 at a 5120x2160 screen's 21:9). *native: the screen's own size
Out picture_for(int v, bool* native = nullptr) {
    v = output_choice(v);
    Out o = output_at(v);
    uint32_t sw = 0, sh = 0;
    if (native) *native = false;
    const bool own = hos_output_own_shape(o.w, o.h);
    screen_size(&sw, &sh);
    uint32_t hw = 0, hh = 0;
    const bool have_host = host_screen_size(&hw, &hh);
    if (!opts.handheld && (own || aspect_follows_host(opts.ultrawide))) {
        const double want = own ? (double)o.w / o.h : have_host ? (double)hw / hh : 0.0;   // (the host's screen: hos_main.c)
        const double game = 16.0 / 9.0;
        if (want > game * 1.01 || (want > 1.0 && want < game * 0.99)) {
            unsigned w = 0, h = 0;
            hos_wide_size(o.h, hos_wide_clamp(want), hos_wide_max_px(), &w, &h);
            o = Out{w, h};
        }
    }
    if (native && v && !opts.handheld) *native = sw && o.w == (sw & ~7u) && o.h == (sh & ~7u);
    return o;
}
Out shown_output() {
    return opts.handheld ? Out{1536, 864} : picture_for(opts.output_res);   // (the real picture)
}
// The size the game draws the 3D at for a fixed scale of its output, a twelfth of it: every twelfth asked came out exact at the three
// outputs (2048x1152: 0.58 drew 1195x672, 0.6667 1366x768). So the scale the game is given is the twelfth too: 0.67 drew 2615x1471 at
// 3840x2160, not the 2560x1440 of 8/12.
int twelfths(float scale) { return std::min(std::max((int)(scale * 12.0f + 0.5f), 1), 12); }
void game_size(float scale, uint32_t& w, uint32_t& h) {
    const Out o = shown_output();
    const int k = twelfths(scale);
    w = (o.w * k + 11) / 12, h = o.h * k / 12;
}
const char* tx_resolution(int v) {
    static char b[64];
    const int up = upscaler();
    // (each stop with the 3D's real size, the render input: a twelfth of the picture (game_size), Native
    // the picture itself)
    if (up == ur::DLAA || up == ur::FSR4_AA || up == ur::XESS_AA) {
        const Out o = shown_output();
        snprintf(b, sizeof b, "Native (%s, %ux%u)", up == ur::DLAA ? "DLAA" : up == ur::FSR4_AA ? "FSR 4" : "XeSS", o.w, o.h);
        return b;
    }
    v = ur::snap_render(up, v);   // (show the active engine's size without overwriting the player's saved scale)
    if (!ur::percent(v)) return "Auto (dynamic)";
    uint32_t w, h;
    game_size(ur::percent(v) / 100.0f, w, h);
    // (XeSS: the preset whose range holds the share, upscaler_rows.h xess_mode_name)
    if (const char* mode = up == ur::XESS ? ur::xess_mode_name(v) : ur::scales_by_mode(up) ? ur::dlss_mode_name(v) : nullptr) {
        snprintf(b, sizeof b, "%s %d%% (%ux%u)", mode, ur::percent(v), w, h);
        return b;
    }
    snprintf(b, sizeof b, "%d%% (%ux%u)", ur::percent(v), w, h);
    return b;
}
/// The Render resolution: the value chosen, for the Upscaler shown (every one: each value with each Upscaler)
const char* hn_resolution(int v, int variant) {
    const int up = variant < 0 ? std::clamp(upscaler(), 0, ur::kUpscalers - 1) : variant;
    if (up >= ur::kUpscalers) return nullptr;
    // (Native is the slider's top: the 3D at the picture's full size)
    if (up == ur::DLAA) return "DLAA: the 3D at the picture's full size, anti-aliased by DLSS. The sharpest, and the heaviest.";
    if (up == ur::FSR4_AA) return "FSR 4's native AA: the 3D at the picture's full size. The sharpest, and the heaviest.";
    if (up == ur::XESS_AA) return "XeSS's Native AA: the 3D at the picture's full size. The sharpest, and the heaviest.";
    const int p = ur::percent(ur::snap_render(up, v));
    if (up == ur::DLSS) {
        switch (p) {
        case 0: return "The game lowers it when the GPU is busy, and DLSS follows. Set Sharpness to around 80%.";
        case 92: case 83: case 75: return "Between Native and Quality: sharper than Quality, a little slower.";
        case 67: return "DLSS's Quality mode: its sharpest from a smaller 3D. Set Sharpness to around 80%.";
        case 58: return "Between Quality and Performance. Set Sharpness to around 80%.";
        case 50: return "Faster, and softer. Set Sharpness to around 80%.";
        case 42: return "Between Performance and Ultra Performance.";
        case 33: return "DLSS's fastest mode, and its softest. Set Sharpness to around 80%.";
        default: return nullptr;   // (not one of DLSS's steps: the row moves to one)
        }
    }
    if (up == ur::FSR3 || up == ur::FSR4) {   // (the same modes, AMD's ratios)
        switch (p) {
        case 0: return "The game lowers it when the GPU is busy, and FSR follows.";
        case 100: return "FSR 3.1's native AA: the 3D at the picture's full size, anti-aliased by FSR. The sharpest, and the heaviest.";
        case 92: case 83: case 75: return "Between native AA and Quality: sharper than Quality, a little slower.";
        case 67: return "FSR's Quality mode, 1.5x: the sharpest of AMD's upscaling modes.";
        case 58: return "FSR's Balanced mode, 1.7x.";
        case 50: return "FSR's Performance mode, 2x: faster, and softer.";
        case 33: return "FSR's Ultra Performance mode, 3x: its fastest, and its softest.";
        default: return nullptr;   // (not one of FSR's steps: the row moves to one)
        }
    }
    if (up == ur::XESS) {   // (each stop under the XeSS preset whose range holds it: xess_rules.h)
        switch (p) {
        case 0: return "The game lowers it when the GPU is busy, and XeSS follows.";
        case 92: case 83: return "XeSS's Ultra Quality Plus mode, 1.3x: sharper than Ultra Quality, a little slower.";
        case 75: return "Between Ultra Quality Plus and Ultra Quality, under XeSS's Ultra Quality mode.";
        case 67: return "XeSS's Ultra Quality mode, 1.5x.";
        case 58: return "Between XeSS's Quality and Balanced, under its Balanced mode.";
        case 50: return "XeSS's Balanced mode, 2x: faster, and softer.";
        case 33: return "XeSS's Ultra Performance mode, 3x: its fastest, and its softest.";
        default: return nullptr;   // (not one of the slider's stops: the row moves to one)
        }
    }
    if (up == ur::OFF) {   // (no upscaler: the 3D stretched to the output as it is drawn)
        if (!p) return "The game lowers it when the GPU is busy; the 3D is stretched from whatever size it draws.";
        if (p == 100) return "The 3D at the output's full size, not stretched: the sharpest, but its edges stay jagged.";
        return "A steady size, stretched to the output: lower is faster, and blurrier.";
    }
    if (!p) return "The game lowers it when the GPU is busy.";
    if (p == 100) return "The 3D at the output's full size: the sharpest, and the slowest.";
    return "A steady size: lower is faster, and softer.";
}
/// (hookshot) Whether the Frame generation by row offers DLSS FG: where DLSS-G can run in this process as far as is known
/// (vk_dlss.cpp dlss_fg_unavailable). Where it cannot, the row has FSR 3.1 FG (0, the default, and 2 the same) and Built-in
/// FG, and its line at FSR 3.1 FG says why not DLSS FG
bool framegen_by_dlss_offered() { return dlss_fg_unavailable() == FG_SKIP_NONE; }
/// Frame generation by with nothing to choose: RX_VK_DLSS_FG=1 chooses DLSS FG for the run (vk_dlss.cpp dlss_fg_forced)
bool framegen_by_fixed() { return dlss_fg_forced(); }
/// A row with nothing else to choose here: shown without its arrows, Left and Right leave it (and the saved value) alone
bool row_fixed(const int* value) {
    return (value == &opts.dlss && ur::upscaler_fixed(upscalers_available())) ||
           (value == &opts.resolution && ur::render_fixed(upscaler())) || (value == &opts.upscale && !filter_needed()) ||
           (value == &opts.dlss_model && ur::model_fixed(upscaler(), dlss_preset_env() != nullptr)) ||
           (value == &opts.framegen_by && framegen_by_fixed()) ||   // (its line says why)
           (value == &opts.astc_rgba8 && getenv("RX_VK_ASTC_RGBA8")) ||   // (set for the run: vk_texture.cpp reads it first)
           (value == &opts.hud_layout && getenv("HOS_WIDE_UI") && *getenv("HOS_WIDE_UI")) ||   // (host/hos_wide_ui.c's, first)
           (value == &opts.intel_compiles && getenv("RX_VK_NO_INTEL_SERIAL"));
}
const char* tx_output_res(int v) {
    static char b[40];
    v = output_choice(v);
    // (the picture this choice makes (picture_for: at the monitor's shape when the Aspect ratio takes it), "(native)"
    // when it is the screen's own size; the game's own reduced size (0, 80% of its 2560x1440: hos_output_parse) marked so,
    // not the default since a new install takes 2560x1440, host/hos_wide_size.h hos_output_default)
    bool native = false;
    const Out o = picture_for(v, &native);
    snprintf(b, sizeof b, "%ux%u%s", o.w, o.h, native ? " (native)" : v ? "" : " (reduced)");
    return b;
}
/// The Aspect ratio row (ultrawide=): the shapes of the sizes offered, narrowest first, the monitor's own named so
const char* tx_ultrawide(int v) {
    static char b[48];
    if (v == aspect_monitor_value()) return "Monitor's shape";   // (the monitor's own not known: as on main)
    // (printed from a format, so menu_i18n.h's "%s (monitor's)" translates it: vk_menu_i18n.cpp match_format)
    if (aspect_is_monitors(v)) snprintf(b, sizeof b, "%s (monitor's)", aspect_shape(v).c_str());
    else snprintf(b, sizeof b, "%s", aspect_shape(v).c_str());
    return b;
}
/// The Aspect ratio: the monitor's own shape, the game's 16:9, or another shape, wider or narrower than 16:9
const char* hn_ultrawide(int v, int variant) {
    static const char* const t[] = {
        "Your monitor's own shape: the picture fills it. The HUD keeps its 16:9 shape in the middle.",
        "The game's own shape.",
        "Wider than 16:9: the camera sees more at the sides. The HUD and menus keep the middle 16:9.",
        "Narrower than 16:9: the picture keeps its height, and the HUD fills its width."};
    if (variant >= 0) return variant < (int)std::size(t) ? t[variant] : nullptr;
    if (aspect_is_monitors(v)) return t[0];
    const std::vector<dm::Shape> shapes = output_shapes();
    const double r = shapes.empty() ? 16.0 / 9.0 : shapes[std::clamp(v, 0, (int)shapes.size() - 1)].r, game = 16.0 / 9.0;
    return r > game * 1.01 ? t[2] : r < game * 0.99 ? t[3] : t[1];
}
/// Anisotropic filtering: the game's own, or 2x to 16x (vk_draw.cpp aniso_override)
const char* tx_anisotropy(int v) {
    static const char* t[] = {"Game's", "2x", "4x", "8x", "16x"};
    return (unsigned)v < 5 ? t[v] : t[4];
}
const char* tx_speed(int v) { return v ? "Real time" : "Per frame"; }
const char* tx_text_speed(int v) {
    static const char* t[] = {"Normal", "2x", "4x", "Instant"};
    if ((unsigned)v >= sizeof t / sizeof t[0]) return t[0];
    return t[v];
}
const char* tx_fast_forward(int v) { return v == 1 ? "Hold" : v == 2 ? "Toggle" : "Off"; }   // (Mako: host/nn_vi.c)
const char* tx_text_size(int v) {
    static const char* t[] = {"Original", "110%", "125%", "150%", "175%"};
    if ((unsigned)v >= sizeof t / sizeof t[0]) return t[0];
    return t[v];
}
const char* tx_damage_taken(int v) {
    static const char* const names[] = {"Half", "Normal", "Double", "Quadruple"};
    return names[v >= 0 && v < 4 ? v : 1];
}
const char* tx_fov(int v) { return v == 100 ? "100% (original)" : tx_percent(v); }
// (hookshot) Walk mode: how the Walk key (the Controls page) makes Link walk with the movement keys (host/nn_hid.c walk_held)
const char* tx_walk_mode(int v) { return v == 1 ? "Toggle" : "Hold"; }
MENU_HINTS(hn_walk_mode, 0, "Link walks while the Walk key is held.", "One press of the Walk key walks, the next runs again.")
/// Shadow resolution: the sun's cascades at the game's own sizes (host/oot_shadow.c). Auto, the default, takes the size
/// for the card's memory (menu_shadow_res)
const char* tx_shadow_res(int v) {
    static const char* t[] = {"Auto", "Game's", "High", "Highest"};
    return (unsigned)v < 4 ? t[v] : t[0];
}
MENU_HINTS(hn_shadow_res, 0,
           "Chosen from the graphics card's memory: the game's size on 4 and 6 GB, High on 8 GB, Highest on 12 GB or "
           "more.",
           "1600 pixels a side, the console's. About 31 MB of video memory.",
           "2200 pixels a side. About 58 MB of video memory.",
           "3072 pixels a side, the game's own highest. About 113 MB of video memory.")
const char* tx_prompts(int v) {
    static const char* t[HOS_PROMPT_N + 1] = {"Auto", "Switch", "Xbox", "PlayStation 4", "PlayStation 5", "Steam Deck",
                                              "Steam Controller", "Keyboard"};
    return t[std::min(std::max(v, 0), (int)HOS_PROMPT_N)];
}
const char* tx_gpu(int v) {
    static char buf[300];
    const int idx = v - 1;
    if (v <= 0) snprintf(buf, sizeof buf, "Auto");
    else if (idx < (int)gpu_device_names.size()) snprintf(buf, sizeof buf, "%d: %s", idx, gpu_device_names[idx].c_str());
    else snprintf(buf, sizeof buf, "%d: Device %d", idx, idx);
    // (the whole name shows: the selected row slides through it, see marquee_pos)
    return buf;
}
const char* tx_pad_layout(int v);
std::vector<monitor_choice::Choice> fullscreen_monitors;
int monitor_pick = 0;
std::string monitor_want, monitor_saved_name;
bool monitor_missing = false;
bool can_monitors() { return host && host->monitor_count && host->monitor_info && host->monitor_select; }
const char* tx_fullscreen_monitor(int value) {
    static std::string text;
    if (value <= 0) return "Auto (current monitor)";
    if (monitor_missing && value == (int)fullscreen_monitors.size() + 1) {
        text = (monitor_saved_name.empty() ? std::string(i18n::tr("Selected monitor")) : monitor_saved_name) +
               i18n::tr(" (not connected)");
        return text.c_str();
    }
    if ((size_t)(value - 1) >= fullscreen_monitors.size()) return "Auto (current monitor)";
    const auto& choice = fullscreen_monitors[value - 1];
    text = choice.name + " (" + std::to_string(choice.width) + "x" + std::to_string(choice.height) + ")";
    int duplicates = 0;
    for (const auto& c : fullscreen_monitors) if (c.name == choice.name) duplicates++;
    if (duplicates > 1) text += " [" + std::to_string(value) + "]";
    return text.c_str();
}
const char* hn_fullscreen_monitor(int, int variant) {
    if (variant > 0) return nullptr;
    if (variant < 0) return "Choose the screen used by Fullscreen, F11 and Alt+Enter. Auto uses the window's current monitor.";
    if (monitor_missing) return "The selected monitor is unavailable. The current monitor is used temporarily; the saved choice is kept.";
    return "While windowed, this chooses the next fullscreen screen. While fullscreen, it moves the game now. Leaving fullscreen restores the window.";
}
// The playback row stores an endpoint ID, never its position or possibly duplicated display name.
// Menu state uses menu_mu, shared by menu_tick and the control bridge; the host mailbox has its own lock.
struct OutputChoice { std::string id, name; };
std::vector<OutputChoice> output_devices;
int output_pick = 0;
std::string output_want, output_saved_name;
bool output_missing = false;
bool can_outputs() {
    return host && host->audio_output_count && host->audio_output_info && host->audio_output_select && host->audio_output_state;
}
bool output_forced() { const char* e = getenv("HOS_AUDIO_DEVICE"); return e && *e; }
std::string output_id_key(const char* text) {
    std::string s(text ? text : "");
    while (!s.empty() && (s.back() == '\r' || s.back() == '\n')) s.pop_back();
    char valid[HOS_OUTPUT_ID_CAP];
    return audio_output_copy_id(valid, sizeof valid, s.c_str()) ? s : std::string();
}
std::string output_name_key(const char* text) {
    std::string s(text ? text : "");
    while (!s.empty() && (s.back() == '\r' || s.back() == '\n')) s.pop_back();
    for (char& c : s) if ((unsigned char)c < 0x20 || c == 0x7f) c = ' ';
    return s;
}
const char* tx_output_device(int v) {
    static std::string text;
    if (output_forced()) return "Overridden by HOS_AUDIO_DEVICE";
    if (v <= 0) return "Default";
    if (output_missing && v == (int)output_devices.size() + 1) {
        text = (output_saved_name.empty() ? std::string(i18n::tr("Selected output")) : output_saved_name) + i18n::tr(" (not connected)");
        return text.c_str();
    }
    if ((size_t)(v - 1) >= output_devices.size()) return "Default";
    text = output_devices[v - 1].name;
    int duplicates = 0;
    for (const auto& d : output_devices) if (d.name == text) duplicates++;
    if (duplicates > 1) text += " [" + std::to_string(v) + "]";
    return text.c_str();
}
const char* hn_output_device(int, int variant) {
    if (variant > 0) return nullptr;
    if (variant < 0) return "Where the game plays sound. A change briefly restarts only the audio stream.";
    if (output_forced()) return "HOS_AUDIO_DEVICE overrides this run. The saved device choice is kept.";
    const int state = can_outputs() ? host->audio_output_state() : 0;
    if (state & HOS_OUTPUT_UNAVAILABLE) return "No playback output could be opened. The game keeps trying.";
    if (output_missing || (state & HOS_OUTPUT_FALLBACK))
        return "Default is used temporarily. The selected output is remembered and retried when available.";
    return output_pick ? "This playback device. Speaker layout changes still require a game restart."
#ifdef _WIN32
                       : "Follow the Windows default playback device.";
#else
                       : "Follow the system default playback device.";
#endif
}

// (hookshot) the Microphone row: Off, the system's default, or one of the host's microphones (host/nn_audio_in.c: the
// ocarina's input streams), told to the host by its name (host->mic_select) whenever it changes. The chosen one is kept by
// its name, mic_want, also while it is unplugged: the row then has one more entry for it, "<name> (not connected)", the
// host lets the default stand in and opens it again once it is back, and the name stays in the ini. In the ini the name is
// cut to kMicNameKept bytes (at a character's start), so the line fits the 80-byte readers of the file (host/nn_hid.c,
// nn_applet.c, hos_main.c), and a name is matched by that much of it
constexpr int kMaxMics = 64;
constexpr size_t kMicNameKept = 60;
std::string mic_want;      // (the chosen microphone's name, cut to kMicNameKept; empty: Off or the default chosen)
bool mic_missing = false;  // (mic_want is not plugged in: the row's last entry, 2 + mic_listed, stands for it)
int mic_listed = 0;        // (the microphones as the host last listed them)
bool can_mic() { return host && host->mic_count && host->mic_name && host->mic_select; }
size_t text_char_start(const std::string& text, size_t at) {
    while (at > 0 && at < text.size() && ((unsigned char)text[at] & 0xc0) == 0x80) at--;
    return at;
}
std::string mic_key(const char* name) {
    std::string k(name ? name : "");
    for (char& c : k)   // (a device's name goes into hookshot_options.ini: a line break in it would add lines there)
        if ((unsigned char)c < 0x20 || c == 0x7f) c = ' ';
    if (k.size() > kMicNameKept) k = k.substr(0, text_char_start(k, kMicNameKept));
    // (and no spaces at the end: a saved line's end, made one above, and those an older build saved with the name)
    while (!k.empty() && k.back() == ' ') k.pop_back();
    return k;
}
/// buf cut back to whole UTF-8 characters (snprintf may have cut one)
void utf8_whole(char* buf) {
    size_t n = strlen(buf), i = n;
    while (i > 0 && ((unsigned char)buf[i - 1] & 0xC0) == 0x80) i--;   // (the last character's continuation bytes)
    if (i == 0) return;
    const unsigned char lead = (unsigned char)buf[i - 1];
    const size_t want = lead >= 0xF0 ? 4 : lead >= 0xE0 ? 3 : lead >= 0xC0 ? 2 : 1;
    if (n - (i - 1) < want) buf[i - 1] = 0;
}
const char* tx_mic(int v) {
    static char buf[160];
    if (v <= 0) return "Off";
    if (v == 1) return "Default";
    if (mic_missing && v == 2 + mic_listed) {
        const int room = (int)sizeof buf - (int)sizeof " (not connected)";
        snprintf(buf, (size_t)room + 1, "%s", mic_want.c_str());
        utf8_whole(buf);
        strcat(buf, " (not connected)");
        return buf;
    }
    const char* n = can_mic() ? host->mic_name(v - 2) : "";
    snprintf(buf, sizeof buf, "%s", n && *n ? n : "Microphone");
    utf8_whole(buf);
    return buf;
}
/// The Microphone row: Off, the default, a microphone of the list, or the chosen one while it is unplugged (variant 1)
const char* hn_mic(int v, int variant) {
    if (v <= 0) return variant <= 0 ? "The game hears silence." : nullptr;
    if (v == 1)
        return variant <= 0 ? "The system's default recording device. On Windows, desktop apps must be allowed to use the "
                              "microphone (Settings, Privacy & security)."
                            : nullptr;
    const bool missing = variant < 0 ? mic_missing && v == 2 + mic_listed : variant == 1;
    if (variant > 1) return nullptr;
    return missing ? "Not plugged in: Default stands in until it is back." : "This microphone, by its name. A change applies at once.";
}
const char* tx_rumble(int v) { return v ? tx_percent(v) : "Off"; }
// (hookshot) Menu size: how large the overlays are drawn (vk_ui.h unit), Medium unless the player chooses Small or Large. It
// was Auto by default, Large in fullscreen at 1080 lines and up while a controller opened the menu: the menu changed size with
// the input that opened it, and the version in its banner no longer fitted. An options file's menu_size=0 (that Auto): Medium
constexpr float kVersionMinPt = 10;   // (the banner's version at Small and Medium: shrunk to fit, no smaller than this, in points)
bool pad_last = false;   // (a controller was the menu's last input: its buttons in the prompts)
int pad_confirm = 0, pad_back = 1;   // (the face buttons that confirm and go back, HOS_PAD_*: menu_keys::confirm_back, each tick)
int pad_paste = 3;   // (hookshot: the one that pastes into a text field while it has the keyboard: menu_keys::paste)
int pad_junk = 2;    // (the randomizer's fork: the Tracker's Junk, where the Switch's Y is bound: menu_keys::extra)
const char* tx_menu_size(int v) {
    static const char* t[] = {"Small", "Medium", "Large"};
    return v >= 1 && v <= 3 ? t[v - 1] : t[1];
}
const char* tx_stick_dead_zone(int v) {
    static const char* t[] = {"Default (24%)", "5%", "10%", "15%", "20%", "30%"};
    return (unsigned)v < 6 ? t[v] : t[0];
}
// Audio output: layout read at startup (host/nn_audio.c au_menu_output); Mono averages stereo live.
const char* tx_audio_output(int v) {
    static const char* t[] = {"Auto", "Stereo", "5.1", "Mono"};
    return (unsigned)v < 4 ? t[v] : t[0];
}
// (hookshot) the motion's deadzone: the console's three zero-drift modes, the rate under which the pad counts as still
const char* tx_deadzone(int v) {
    static const char* t[] = {"Low", "Standard", "High"};
    return t[v < 0 ? 0 : v > 2 ? 2 : v];
}
const char* tx_robust(int v) {
    static const char* t[] = {"Auto", "Off", "On"};
    return (unsigned)v < 3 ? t[v] : t[0];
}
const char* tx_preset(int v) {
    static const char* t[] = {"Custom", "Minimum (4GB)", "Low (6GB)", "Balanced (8GB)", "High (12GB)", "Ultra (16GB+)",
                              "Auto (this PC)"};
    return t[std::min(std::max(v, 0), 6)];
}
// (Sharpness: tuned for the window pass's neighbours one picture pixel apart, each about the old setting's sharpening on a
// 3840 x 2160 window at that preset's picture, 2048 x 1152 or the handheld profile's 1536 x 864: same frame, mean |Laplacian|
// of the window and of the picture, on the slider's steps)
void env_release(const int* value);   // (below: a row the environment held, set by the menu from now on)
// (hookshot) the Quality preset "Auto (this PC)", kAutoPreset: the profile menu_auto_for_gpu chose for this PC (auto_settings.h)
::auto_settings::Choice auto_choice;   // (tier 0: no profile yet, before the card is known)
uint64_t auto_for = 0;               // (the fingerprint of the hardware the options' Auto settings were chosen for: auto_for=)
uint64_t auto_fp = 0;                // (this PC's, menu_auto_for_gpu)
uint64_t auto_tuned = 0;             // (the fingerprint the measured tuning in play finished for: auto_tuned=)
::auto_settings::Tuning auto_tuning;   // (the measured tuning in play, menu_auto_tune; its steps kept as auto_steps=)
std::string gpu_saved_card;           // (the GPU device row's card as the options file saved it, gpu_device_id=: gpu_choice.h)
bool gpu_card_missing = false;        // (that card is not among this run's GPUs: menu_set_gpu_count)
void apply_auto();   // (below: the Auto preset's rows)
void apply_preset(int p) {
    if (p == kAutoPreset) {
        apply_auto();   // (chosen on the row: all of its rows, as any preset)
        return;
    }
    // (the rows it sets are the preset's from now on, even at the value the environment forced: save writes them)
    if (p > 0)
        for (const int* v : {&opts.resolution, &opts.upscale, &opts.sharpness, &opts.pace, &opts.realtime, &opts.handheld})
            env_release(v);
    if (p > 0) opts.shadow_res = 0;   // (Shadow resolution back to Auto: the size for this preset's memory, menu_shadow_res)
    switch (p) {
    case 1: // Minimum (4GB VRAM / iGPU)
        opts.resolution = 4; opts.upscale = 2; opts.sharpness = 30;
        opts.pace = 1;    opts.realtime = 1; opts.handheld = 1;
        break;
    case 2: // Low (6GB VRAM)
        opts.resolution = 2; opts.upscale = 2; opts.sharpness = 30;
        opts.pace = 1;    opts.realtime = 1; opts.handheld = 1;
        break;
    case 3: // Balanced (8GB VRAM)
        opts.resolution = 1; opts.upscale = 1; opts.sharpness = 30;
        opts.pace = 1;    opts.realtime = 1; opts.handheld = 0;
        break;
    case 4: // High (12GB VRAM)
        opts.resolution = 1; opts.upscale = 2; opts.sharpness = 40;
        opts.pace = 1;    opts.realtime = 1; opts.handheld = 0;
        break;
    case 5: // Ultra (16GB+ VRAM)
        opts.resolution = 1; opts.upscale = 2; opts.sharpness = 50;
        opts.pace = 1;    opts.realtime = 1; opts.handheld = 0;
        break;
    default:
        break;
    }
    // (the Upscaler and Frame generation are the player's: a preset never turns DLSS or made frames on or off. With DLSS
    // its resolution is DLSS's nearest mode)
    if (p > 0) opts.resolution = ur::snap_render(upscaler(), opts.resolution);   // (a slider stop kept)
    opts.budget = p;   // (Custom chosen on this row: none, as before)
}
/// The Output resolution Auto never sets (auto_settings.h Choice: the game's own or the player's, read at boot), nor
/// Mesh shaders (RX_VK_MESH_SHADERS), and the fingerprint has the card's mesh shaders, not this run's mode
void apply_auto() {
    const ::auto_settings::Choice& c = auto_choice;
    if (c.tier < 1) return;
    env_release(&opts.dlss);
    opts.dlss = c.upscaler;   // (before the tier's rows: apply_preset snaps its Render resolution to this upscaler)
    apply_preset(c.tier);   // (the tier's scaling rows)
    if (c.tier == 1) opts.upscale = 0, opts.sharpness = 0;   // (the plain scale, as RX_VK_LOW_SPEC: the lightest)
    opts.handheld = 0;   // (docked: the handheld profile gave a GTX 1050 a black picture; the Render resolution lightens the card)
    if (c.resolution) opts.resolution = ur::snap_render(c.upscaler, c.resolution);
    auto_tuned = 0;   // (chosen again: measured again in play)
    auto_tuning = {};
    opts.preset = kAutoPreset;   // (apply_preset set the tier's number)
    auto_for = auto_fp;          // (chosen for this PC, whether at a start or on the menu's row)
}

MENU_HINTS(hn_preset, 0, "Each row as you set it. Changing most rows yourself comes back to Custom.",
           "Resolution 50% (with DLSS its nearest mode), Lanczos, Sharpness 30%, the Handheld Profile.",
           "Resolution 75% (with DLSS its nearest mode), Lanczos, Sharpness 30%, the Handheld Profile.",
           "Resolution 100% (with DLSS its nearest mode), Catmull-Rom, Sharpness 30%.",
           "Resolution 100% (with DLSS its nearest mode), Lanczos, Sharpness 40%.",
           "Resolution 100% (with DLSS its nearest mode), Lanczos, Sharpness 50%.",
           "Chosen for this PC from its graphics card, video memory and screen, and chosen again when they change. The log's "
           "\"Auto (this PC)\" line says why.")
MENU_HINTS(hn_gpu, 0, "The best dedicated GPU.")
/// Frame generation: how many frames are made for each of the game's
const char* hn_framegen(int v, int variant) {
    // (2x: by AMD FSR 3.1 where it runs, from the scene's depth and motion: vk_framegen.cpp. Variant 1 is that text)
    if (v == 2 && (variant < 0 ? fsr3fi::frames_wanted() != 0 : variant == 1))
        return "One made frame between each two of the game's, by AMD FSR 3.1 from the scene's depth and motion.";
    if (variant > 0) return nullptr;
    if (v <= 0) return "Only the game's own frames: no added delay.";
    if (v == 1) return "A frame for each of the display's refreshes: none made when the game keeps up. Frame pacing does not apply.";
    static char b[9][96];
    snprintf(b[v], sizeof b[v], "%s between each two of the game's.", v == 2 ? "One made frame" : v == 3 ? "Two made frames" : v == 4 ? "Three made frames"
             : v == 5 ? "Four made frames" : v == 6 ? "Five made frames" : v == 7 ? "Six made frames" : "Seven made frames");
    return b[std::clamp(v, 2, 8)];
}
MENU_HINTS(hn_pace, 0, "As soon as it is ready.", "At an even interval: less stutter, at up to one frame of delay.")
/// (hookshot) Who made the made frames lately (vk_framegen.cpp framegen_maker), with Frame generation on; nullptr: none made.
/// One name each, "<engine> FG", on the Frame generation by row and the FPS counter alike; "DLSS FG paused" where DLSS FG
/// showed the game's frames alone (the game's own menus: vk_dlss.cpp dlss_fg_holds)
const char* framegen_maker_name() {
    if (opts.framegen < 1) return nullptr;
    switch (framegen_maker()) {
    case FgMaker::Dlss: return "DLSS FG";
    case FgMaker::Fsr3: return "FSR 3.1 FG";
    case FgMaker::BuiltIn: return "Built-in FG";
    case FgMaker::DlssPaused: return "DLSS FG paused";
    default: return nullptr;
    }
}
/// Frame generation by: the choice, DLSS FG (0), Built-in FG (1) or FSR 3.1 FG (2); where DLSS FG cannot run, 0 is FSR 3.1
/// FG (AMD FSR 3.1's frame interpolation, vk_fsr3fi.cpp asked); DLSS FG with RX_VK_DLSS_FG=1.
/// Who makes the frames now (the game's own menus give DLSS-G nothing to make them from) is the row's line and the FPS
/// counter's (framegen_maker_name), not the choice's name
const char* tx_framegen_by(int v) {
    if (framegen_by_dlss_offered() && (v == 0 || dlss_fg_forced())) return "DLSS FG";
    return v == 2 ? "FSR 3.1 FG" : "Built-in FG";   // (Mako 4.2: 0 is the built-in one where DLSS FG cannot run)
}
/// Why DLSS-G does not make the frames now (vk_dlss.h FgSkip, and the Auto multiplier's FG_SKIP_COUNT), the row's line after
/// "Not DLSS FG now: ". most: its runtime's most made frames, for FG_SKIP_TOO_MANY
const char* framegen_skip_text(int why, unsigned most) {
    switch (why) {
    case FG_SKIP_OFF: return "DLSS Frame Generation is turned off for this run (RX_VK_DLSS_FG=0).";
    case FG_SKIP_DEVICE: return "NVIDIA DLSS does not run on this GPU.";
    case FG_SKIP_START:
        return "NVIDIA's runtime did not start DLSS Frame Generation: it needs an RTX 40 or newer, and nvngx_dlssg.dll in the "
               "game's ngx folder (the builder's NVIDIA DLSS tick).";
    case FG_SKIP_TOO_MANY: {
        static char b[160];
        snprintf(b, sizeof b, "Its runtime makes %u made frames at most: a lower Frame generation, or a newer nvngx_dlssg.dll.",
                 most ? most : 1u);
        return b;
    }
    case FG_SKIP_INPUTS:
        return "No picture from a temporal Upscaler to make them from: NVIDIA DLSS or DLAA, or AMD FSR, on the Upscaler row. "
               "The game's own menus have none.";
    case FG_SKIP_REFUSED: return "NGX refused its frames.";
    case FG_SKIP_NOT_BUILT: return "This build has no NVIDIA DLSS (the builder's NVIDIA DLSS tick).";
    case FG_SKIP_COUNT: return "DLSS Frame Generation makes a fixed 2x to 8x, not Frame generation's Auto.";
    default: return nullptr;
    }
}
/// Its line: the choice's. Where DLSS FG cannot run in this run, why, whatever is saved ("DLSS FG cannot run: " and
/// framegen_skip_text, or for DLSS itself dlss_why_text: the log has NGX's own answer); with RX_VK_DLSS_FG=1, that it chooses.
/// At DLSS FG with the game's frames alone now (its own menus, movies and loading screens draw no 3D to make frames from:
/// vk_dlss.cpp dlss_fg_holds), that it is paused; with another making the frames now, why ("Not DLSS FG now: "). Variants
/// (every one): the choice's; at DLSS FG "Not DLSS FG now: " with each reason, and the paused line; the switch's line; then
/// "DLSS FG cannot run: " with each of its reasons
const char* hn_framegen_by(int v, int variant) {
    if (v == 0 && !framegen_by_dlss_offered()) v = 1;   // (Mako 4.2: Built-in FG)
    static const char* const t[] = {
        "NVIDIA DLSS Frame Generation (RTX 40 and newer), made from the Upscaler's depth and motion.",
        "The renderer's own: made from the finished picture alone.",
        "AMD FSR 3.1 frame interpolation, made from the scene's depth and motion: any GPU.",
    };
    static const char* const paused = "DLSS FG paused: the game's own menus, movies and loading screens draw no 3D to make "
                                      "frames from, so only the game's own frames show.";
    // (dlss_fg_unavailable's reasons, each for the whole run; FG_SKIP_DEVICE with each of DLSS's own, dlss_why)
    struct Cannot { int why, dlss; };
    static const Cannot cannot[] = {{FG_SKIP_OFF, 0},
                                    {FG_SKIP_DEVICE, DLSS_ENV_OFF},
                                    {FG_SKIP_DEVICE, DLSS_NEEDS_RTX},
                                    {FG_SKIP_DEVICE, DLSS_NEEDS_DRIVER},
                                    {FG_SKIP_DEVICE, DLSS_NO_RUNTIME},
                                    {FG_SKIP_DEVICE, DLSS_RUNTIME_NOT_ASCII},
                                    {FG_SKIP_START, 0},
                                    {FG_SKIP_REFUSED, 0},
                                    {FG_SKIP_NOT_BUILT, 0}};
    constexpr int kCannot = (int)(sizeof cannot / sizeof cannot[0]);
    // (at DLSS FG: 1 .. FG_SKIP_COUNT each reason, FG_SKIP_COUNT the Auto multiplier's; then the paused line)
    const int nows = v == 0 ? (int)FG_SKIP_COUNT + 1 : 0;
    const int forced_at = nows + 1;   // (the switch's line; the reasons it cannot run after it)
    static char b[FG_SKIP_COUNT + kCannot + 4][400];
    int why = FG_SKIP_NONE, dlss = (int)DLSS_OK;
    unsigned most = 0;
    bool off = false;      // (DLSS FG cannot run: not offered)
    bool forced = false;   // (RX_VK_DLSS_FG=1 chooses)
    if (variant >= 0) {
        if (variant == 0) return t[std::clamp(v, 0, 2)];
        if (variant < nows) why = variant;
        else if (variant == nows) return paused;
        else if (variant > forced_at && variant - forced_at <= kCannot) {
            const Cannot& c = cannot[variant - forced_at - 1];
            why = c.why, dlss = c.dlss, off = true;
        } else if (variant == forced_at) {
            forced = true;
        } else {
            return nullptr;
        }
    } else if (v == 1 && !dlss_fg_forced()) {
        return t[1];   // (Built-in FG, chosen)
    } else if ((why = dlss_fg_unavailable()) != FG_SKIP_NONE) {   // (FSR 3.1 FG makes them: why not DLSS FG)
        off = true, dlss = (int)dlss_why();
    } else if (dlss_fg_forced()) {
        forced = true;
    } else {
        if (v != 0) return t[v == 2 ? 2 : 1];
        const FgMaker m = opts.framegen >= 1 ? framegen_maker() : FgMaker::None;
        if (m == FgMaker::DlssPaused) return paused;
        if (m != FgMaker::BuiltIn && m != FgMaker::Fsr3) return t[0];
        why = opts.framegen == 1 ? (int)FG_SKIP_COUNT : dlss_fg_skip(&most);
    }
    char* out = b[variant >= 0 ? variant : FG_SKIP_COUNT + kCannot + 3];
    if (forced) {   // (as the V-Sync row's switches)
        snprintf(out, sizeof b[0], "%s is set: it chooses for this run.", "RX_VK_DLSS_FG=1");
        return out;
    }
    const char* text = off && why == FG_SKIP_DEVICE && dlss_why_text(dlss) ? dlss_why_text(dlss)
                                                                          : framegen_skip_text(why, most);
    if (!text) return t[off || v == 2 ? 2 : v == 1 ? 1 : 0];
    snprintf(out, sizeof b[0], off ? "DLSS FG cannot run: %s" : "Not DLSS FG now: %s", text);
    return out;
}
const char* tx_vsync(int v) {
    static const char* const t[] = {"Auto", "On", "Off"};
    return t[std::clamp(v, 0, 2)];
}
/// (the environment's switch for this run, over the row: menu_vsync)
const char* vsync_env() {
    if (env_on("RX_VK_FIFO")) return "RX_VK_FIFO";
    if (env_on("RX_VK_IMMEDIATE")) return "RX_VK_IMMEDIATE";
    return nullptr;
}
const char* hn_vsync(int v, int variant) {
    static const char* const t[] = {
        "No tearing and no wait where the driver allows it (mailbox); otherwise as On, or on Windows as Off.",
        "Each frame waits for the display's refresh: no tearing, at most the display's rate.",
        "Each frame is shown at once: the least delay, and it can tear. Where the driver cannot, as Auto."};
    if (variant == 1 || (variant < 0 && vsync_env())) {
        static char b[96];
        snprintf(b, sizeof b, "%s is set: it chooses for this run.", vsync_env() ? vsync_env() : "RX_VK_FIFO or RX_VK_IMMEDIATE");
        return b;
    }
    return variant <= 0 ? t[std::clamp(v, 0, 2)] : nullptr;
}
/// (the environment's switch for this run, over the Threaded rendering row: RX_VK_ASYNC chooses the render thread, and
/// RX_VK_RECORDER the recorder, each for its own half; with both set the first is named)
const char* threaded_env() {
    if (getenv("RX_VK_ASYNC")) return "RX_VK_ASYNC";
    if (getenv("RX_VK_RECORDER")) return "RX_VK_RECORDER";
    return nullptr;
}
/// (Auto's line says what Auto is: the CPU's rule with threaded::kAutoEnabled on, Off everywhere were it off)
const char* hn_threaded(int v, int variant) {
    static const char* const t[] = {
        threaded::kAutoEnabled
            ? "On where the processor has 12 or more threads for the game, and nothing rules it out; otherwise Off."
            : "The same as Off, on every PC.",
        "The picture is drawn on threads of its own while the game goes on to its next frame. Still being tested: it "
        "can show flashes.",
        "The picture is drawn on the game's own thread, as before."};
    if (variant == 1 || (variant < 0 && threaded_env())) {
        static char b[96];
        snprintf(b, sizeof b, "%s is set: it chooses for this run.", threaded_env() ? threaded_env() : "RX_VK_ASYNC or RX_VK_RECORDER");
        return b;
    }
    return variant <= 0 ? t[std::clamp(v, 0, 2)] : nullptr;
}
/// The Output resolution: the game's own reduced size, the player's own, or one of the screen's sizes as it compares with the
/// screen (its own, larger, smaller; nothing where the screen's size is not known)
const char* hn_output_res(int v, int variant) {
    static const char* const t[] = {
        "The game's own reduced size, 80% of its 2560x1440: lighter on the GPU.",
        "Your screen's own size: the HUD and text pixel for pixel, nothing to scale to the window.",
        "Larger than your screen: drawn bigger, then scaled down to the window. Sharper, and slower. The game's render "
        "targets get a bigger GPU pool, so a full-size 3D fits.",
        "Smaller than your screen: faster, and scaled up to the window.",
        "Your own size, from Custom output size below."};
    if (variant >= 0) return variant < (int)std::size(t) ? t[variant] : nullptr;
    v = output_choice(v);
    if (!v) return t[0];
    if (v == custom_index()) return t[4];
    uint32_t sw = 0, sh = 0;
    if (!screen_size(&sw, &sh)) return nullptr;
    bool native = false;
    const Out o = picture_for(v, &native);
    return native ? t[1] : (uint64_t)o.w * o.h > (uint64_t)sw * sh ? t[2] : t[3];
}
/// The Window scaling filter: its filter, or that none is needed at this window's size
const char* hn_filter(int v, int variant) {
    static const char* const t[] = {"The plain copy.", "Sharper.", "Sharper still; can ring on edges."};
    static const char* const none = "The window is the Output resolution's size: nothing to scale. The choice is kept for "
                                    "another size.";
    if (variant < 0) return filter_needed() ? t[std::clamp(v, 0, 2)] : none;
    return variant == 0 ? t[std::clamp(v, 0, 2)] : variant == 1 ? none : nullptr;
}
const char* hn_crt_filter(int v, int variant) {
    static const char* const t[] = {
        "Off: no extra CRT passes or image allocations.",
        "Timothy Lottes' crt-lottes: flat aperture grille, a PVM-style look, not a calibrated Sony model.",
        "Timothy Lottes' crt-lottes: curved consumer TV with a shadow mask and beam bloom.",
        "Hyllian's crt-hyllian-fast: cubic reconstruction, scanlines and a magenta/green mask.",
        "Greg Hogan's zfast CRT: softer scanlines and a monochrome aperture mask."};
    if (variant < 0)
        variant = v > 0 && (unsigned)v < std::size(t) && present_native_pq.load(std::memory_order_relaxed) ? 1 : 0;
    if (variant == 1)
        return "Bypassed: the game is presenting Native HDR (PQ). The saved CRT choice is kept; SDR and Expanded HDR can use it.";
    return hint_in(t, (int)std::size(t), 0, v, variant);
}
MENU_HINTS(hn_crt_lines, 0, "240 virtual lines: a coarser raster and wider scanline spacing.",
           "480 virtual lines: a finer raster, reduced when the destination is too small.",
           "720 virtual lines: the finest raster, reduced when the destination is too small.")
/// Sharpness: with DLSS or DLAA, the amount that suits them
const char* hn_sharpness(int v, int variant) {
    static const char* const dlss = "DLSS and DLAA look softer than the game's own upscaler: around 80% suits them.";
    const bool with_dlss = variant < 0 ? upscaler() == ur::DLSS || upscaler() == ur::DLAA : variant == 1;
    if (variant > 1) return nullptr;
    return with_dlss ? dlss : v == 0 ? "Off: the picture as it is." : nullptr;
}
MENU_HINTS(hn_handheld, 0, "As on a TV: the game at the Output resolution's size.",
           "As in the hands: the game at the console's handheld size (1536x864), lighter on the GPU.")
const char* tx_wide_menus(int v) {
    static const char* t[] = {"Full width", "Centred, blurred sides", "Centred, black bars"};
    return t[std::min(std::max(v, 0), 2)];
}
MENU_HINTS(hn_wide_menus, 0, "The menus stretched over the whole screen, as before.",
           "The menus in the middle 16:9; beside them, what the game draws there, out of focus.",
           "The menus in the middle 16:9; black beside them.")
/// (the HUD layout row, HOS_OPT_HUD_LAYOUT: host/hos_wide_ui.c places the HUD by it at each present, #1133)
const char* tx_hud_layout(int v) { return v ? "Middle 16:9" : "Screen's edges"; }
const char* hn_hud_layout(int v, int variant) {
    static const char* const t[] = {"The hearts, the buttons and the minimap at the screen's own edges and corners.",
                                    "The HUD where it is at 16:9, in the middle (fitted to the width on a narrower screen)."};
    static const char* const held = "Set by HOS_WIDE_UI (hookshot_env.txt or the environment): remove that line to choose here.";
    const char* env = getenv("HOS_WIDE_UI");
    if (variant < 0) return env && *env ? held : t[v ? 1 : 0];
    return variant == 0 ? t[v ? 1 : 0] : variant == 1 && env && *env ? held : nullptr;
}
/// (the ASTC as RGBA8 row's line while RX_VK_ASTC_RGBA8 holds it: the old readme's way, still in some hookshot_env.txt files)
const char* hn_astc_rgba8(int, int variant) {
    return variant <= 0 && getenv("RX_VK_ASTC_RGBA8") ? "Set by RX_VK_ASTC_RGBA8 (hookshot_env.txt or the environment): remove that line to choose here."
                                       : nullptr;
}
const char* tx_intel_compiles(int v) { return v == 1 ? "Side by side" : v == 2 ? "One at a time" : "Auto"; }
/// (the Intel shader compiles row's line: RX_VK_NO_INTEL_SERIAL holds it, as RX_VK_ASTC_RGBA8 the ASTC row)
const char* hn_intel_compiles(int v, int variant) {
    if (variant <= 0 && getenv("RX_VK_NO_INTEL_SERIAL"))
        return "Set by RX_VK_NO_INTEL_SERIAL: the launcher's build settings (Intel shader compiles), hookshot_env.txt or the "
               "environment. Change it there to choose here.";
    static const char* const t[] = {"Side by side on the Arc B-series (driver 101.9154 or newer), where it was measured; one at "
                                    "a time on other Intel graphics.",
                                    "Shaders are built faster on a CPU with many cores, but Intel's driver can crash the game "
                                    "while it builds them.",
                                    "The safe choice, and the best on a CPU with 4 cores or fewer: a shader Intel's compiler "
                                    "faults on is left out instead of closing the game."};
    return hint_in(t, 3, 0, v, variant);
}
MENU_HINTS(hn_robust, 0, "On, on every card.", "Can be faster on some NVIDIA cards.", "Always on.")
MENU_HINTS(hn_fps, 0, nullptr, "The frame rate. With frame generation on, the game's own rate too.",
           "And the game's frame time, with its 1% low: the mean time of its slowest 1% of frames over the last 10 seconds.",
           "And a graph of the last 4 seconds' frame times, with a line at the Game frame rate cap's.",
           "And where each frame's time goes, as colours in the graph: the game, the renderer, its waits on the render thread "
           "and the GPU, pacing (frame rate cap, vsync); with threaded rendering, a lane for the render thread's time; the "
           "GPU's own time; red marks where shaders were built or draws left out.",
           "And, for debugging, the version, the CPU, GPU and driver, and the renderer's own numbers: video memory, textures, draws, "
           "dispatches and render passes a frame, draws skipped, texture uploads and pipelines built.")
MENU_HINTS(hn_menu_size, 1, "Smaller, for a desk.", "The usual size.", "Larger, for a TV across the room.")
MENU_HINTS(hn_speed, 0, "A step each frame: the game slows down whenever it runs below 60 fps.",
           "Normal speed down to 15 fps, by taking longer steps.")
MENU_HINTS(hn_text_speed, 0, "The game's own pace, with its pauses.", "Twice as fast.", "Four times as fast.",
           "Each page at once, as pressing A does.")
MENU_HINTS(hn_fast_forward, 0, nullptr, "Only while held.", "One press turns it on, the next one off.")
MENU_HINTS(hn_audio_output, 0, "5.1 when the selected/default output has 5.1 or more speakers at startup, else stereo.",
           "Stereo, whatever the device has.", "5.1, whatever the device has. Mixed down on stereo speakers.",
           "The stereo average in both ears. Changes live on stereo output; restart from 5.1.")
MENU_HINTS(hn_text_size, 0, "The game's original size.", "A little larger.", "Larger.", "Much larger.", "Largest.")
MENU_HINTS(hn_background, 0, "Only while the game's window has the focus.",
           "Also behind other windows, for streaming or other apps. The keyboard and mouse still need the game's window.")
MENU_HINTS(hn_mousecam, 0, "The mouse stands in for the right stick, with its curve and top speed.",
           "The mouse turns the camera itself, one to one, as in a PC game.",
           "The mouse plays no part: a click in the window doesn't capture it. For a controller or the keyboard alone.")
MENU_HINTS(hn_mouse_invert, 0, nullptr, "Moving the mouse forward tilts the camera down.")
MENU_HINTS(hn_gyro, 0, "The sticks alone aim.",
           "Switch Pro controllers and pads in Switch mode, DualSense and DualShock 4. The value says whether the "
           "connected pad has a gyroscope.")
MENU_HINTS(hn_pad_layout, 0, "The Switch's order: A on the right, B at the bottom, X at the top, Y on the left.",
           "A at the bottom (action and talk), B on the right, X on the left, Y at the top.",
           "A at the bottom, B on the right; X and Y as on the Switch.",
           "Bindings of your own, from the Controls page.")
MENU_HINTS(hn_prompts, 0,
           "Those of the first controller, from its name (SDL's). With none, the keyboard's (the Switch's with XInput "
           "alone).",
           "The Switch's buttons.", "An Xbox controller's.", "A PlayStation 4 controller's.", "A PlayStation 5 controller's.",
           "A Steam Deck's.", "The keys and mouse buttons your controls put each action on.")

// ---- (hookshot) text fields: rows whose value is typed (MkwVkHost.take_text: WM_CHAR on Windows, SDL's text input on Linux;
// RX_VK_MENU_SCRIPT's TYPE). A field holds printable ASCII alone, as the menu's glyphs are baked for it (vk_imgui.cpp
// bake_some): full-width digits and x are folded to ASCII, other characters are left out, and allow() can take fewer.
// While editing (menu_tick), keys type into the field only: Left, Right, Home and End move the caret, Backspace and
// Delete remove a character, Ctrl+V and Shift+Insert paste the clipboard's first line (the host does: take_text), Enter sets
// the text (the field's apply, which can refuse it and say why), Esc puts the text back as it was. A controller's confirm and
// back are Enter and Esc, its D-pad moves the caret and cycles characters, its shoulders add and remove a character,
// its paste button (menu_keys::paste) pastes; a click elsewhere is Enter, a right click Esc; closing the menu is Esc too ----
struct TextField {
    char text[64];                     // (NUL-terminated)
    int len = 0, caret = 0;            // (in bytes, a character each: ASCII)
    int max = 63;                      // (the most it holds, below sizeof text)
    bool (*allow)(char c) = nullptr;   // (of the printable ASCII, what it takes; nullptr all of it)
    const char* (*pad_chars)(const TextField&) = nullptr;   // (characters offered at the caret, in cycling order)
};
enum { kTextGoOn, kTextDone, kTextCancel };
/// One input to a field: a character typed (a Unicode code point) or HOS_TEXT_KEY | an editing key (vk_api.h). The text and its
/// caret changed; kTextDone for Enter, kTextCancel for Esc, else kTextGoOn
int text_edit(TextField& f, uint32_t in) {
    f.len = std::clamp(f.len, 0, (int)sizeof f.text - 1), f.caret = std::clamp(f.caret, 0, f.len);
    if (in & HOS_TEXT_KEY) {
        switch (in & ~(uint32_t)HOS_TEXT_KEY) {
        case VK_RETURN: return kTextDone;
        case VK_ESCAPE: return kTextCancel;
        case VK_LEFT: f.caret = std::max(f.caret - 1, 0); break;
        case VK_RIGHT: f.caret = std::min(f.caret + 1, f.len); break;
        case VK_HOME: f.caret = 0; break;
        case VK_END: f.caret = f.len; break;
        case VK_BACK:
            if (f.caret > 0) memmove(f.text + f.caret - 1, f.text + f.caret, (size_t)(f.len - f.caret + 1)), f.caret--, f.len--;
            break;
        case VK_DELETE:
            if (f.caret < f.len) memmove(f.text + f.caret, f.text + f.caret + 1, (size_t)(f.len - f.caret)), f.len--;
            break;
        case VK_UP:
        case VK_DOWN:
        case VK_INSERT: {
            if (!f.pad_chars) break;
            const char* chars = f.pad_chars(f);
            const int n = (int)strlen(chars), key = (int)(in & ~(uint32_t)HOS_TEXT_KEY);
            if (!n) break;
            const char c = f.caret < f.len ? f.text[f.caret] : 0;
            const char* at = c ? strchr(chars, c == 'X' ? 'x' : c) : nullptr;
            const int next = key == VK_INSERT ? 0 : at ? ((int)(at - chars) + (key == VK_UP ? 1 : n - 1)) % n
                                                                      : key == VK_UP ? 0 : n - 1;
            if (key == VK_INSERT || f.caret == f.len) {
                const int caret = f.caret;
                text_edit(f, (uint32_t)chars[next]);
                f.caret = caret;   // (the new character is the one to cycle)
            } else if (!f.allow || f.allow(chars[next])) f.text[f.caret] = chars[next];
            break;
        }
        }
        return kTextGoOn;
    }
    if (in >= 0xff10 && in <= 0xff19) in = '0' + in - 0xff10;
    else if (in == 0xff58) in = 'x';
    if (in < 0x20 || in > 0x7e || f.len >= std::min(f.max, (int)sizeof f.text - 1) || (f.allow && !f.allow((char)in)))
        return kTextGoOn;   // (not printable ASCII, not this field's, or no room: left out)
    memmove(f.text + f.caret + 1, f.text + f.caret, (size_t)(f.len - f.caret + 1));
    f.text[f.caret++] = (char)in;
    f.len++;
    return kTextGoOn;
}
/// A field's text set whole, cut to what it holds, the caret at its end
void text_set(TextField& f, const char* t) {
    snprintf(f.text, sizeof f.text, "%.*s", std::clamp(f.max, 0, (int)sizeof f.text - 1), t ? t : "");
    f.len = f.caret = (int)strlen(f.text);
}

const char* const kFpsDevLineHelp = "Whether the FPS counter's Dev level shows this line.";   // (the details page's rows)
Row rows[] = {
    // Graphics, in sections: a heading row is a section's title (draw_options draws it, the selection steps over it). The
    // Quality preset first, as it sets rows in every section. (Reflex, Anti-Lag 2, the Upscaler and the DLSS model only where
    // they run here; HDR's paper white and peak brightness only with HDR on: row_shown)
    {TAB_GRAPHICS, "Quality preset", &opts.preset, 0, 6, 1, tx_preset,
     "Sets the scaling rows and Shadow resolution for a GPU with that much memory. The Upscaler and Frame "
     "generation stay yours.",
     hn_preset},
    // (the picture's way, top to bottom: the output's size, what fills it from the 3D, the 3D's size, its sharpening; then
    // the frames, and the window it is shown in)
    {TAB_GRAPHICS, "Resolution and upscaling", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    // (the shape, then its sizes: the screen's display modes, display_modes.h; outputs_sync sets both rows' ends at the start)
    {TAB_GRAPHICS, "Aspect ratio", &opts.ultrawide, 0, 1, 1, tx_ultrawide,
     "The picture's shape: your monitor's own (the default: wider on an ultrawide, narrower on 4:3 or 16:10), the game's "
     "16:9, or another your screen has. The Output resolution lists that shape's sizes. Applies after a restart.", hn_ultrawide,
     true, true},
    {TAB_GRAPHICS, "Output resolution", &opts.output_res, 0, 0, 1, tx_output_res,
     "The game's whole frame, HUD included, before it is scaled to the window. Docked only. Applies after a restart.",
     hn_output_res, true, true},
    {TAB_GRAPHICS, "Custom output size", nullptr, 0, 0, 0, nullptr,   // (hookshot: a text field, field_rows)
     "An Output resolution of your own, typed as width x height: your monitor's size, such as 3440x1440, 2560x1080 or "
     "2560x1600. Each side is rounded down to a multiple of 8; a size the Output resolution offers is chosen there. Empty: "
     "none. Docked only. Applies after a restart."},
    {TAB_GRAPHICS, "Profile", &opts.handheld, 0, 1, 1, tx_profile,
     "Runs the game as the console docked or handheld. Applies after a restart.", hn_handheld, true},
    {TAB_GRAPHICS, "Upscaler", &opts.dlss, 0, ur::kUpscalers - 1, 1, tx_upscaler, "What scales the 3D up to the Output resolution.",
     hn_upscaler},
    {TAB_GRAPHICS, "DLSS model", &opts.dlss_model, 0, ur::kModels - 1, 1, tx_dlss_model,
     "Which of NVIDIA's DLSS networks draws the picture.", hn_dlss_model, false, true},
    {TAB_GRAPHICS, "Render resolution", &opts.resolution, 0, ur::kValues - 1, 1, tx_resolution,
     "The share of the output the 3D is drawn at; the Upscaler fills in the rest.", hn_resolution},
    {TAB_GRAPHICS, "Sharpness", &opts.sharpness, 0, 100, 10, tx_percent,
     "Sharpens the picture as it goes to the window, with any filter. Too much shows halos around edges.", hn_sharpness},
    {TAB_GRAPHICS, "Frame generation and latency", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    {TAB_GRAPHICS, "Frame generation", &opts.framegen, 0, 8, 1, tx_framegen,
     "Makes frames between the game's own, for smoother motion, at a little input delay. Fast motion or camera cuts can "
     "show artifacts.", hn_framegen, false, true},
    {TAB_GRAPHICS, "Frame generation by", &opts.framegen_by, 0, 2, 1, tx_framegen_by,
     "Who makes the frames at 2x and up. NVIDIA DLSS Frame Generation needs a temporal Upscaler (DLSS, DLAA or FSR) for "
     "the scene's depth and motion. Changes at once.", hn_framegen_by, false, true},
    {TAB_GRAPHICS, "Game frame rate cap", &opts.fps_cap, -1, 6, 1, tx_fps_cap,
     "Limits frames rendered by the game. Generated frames are additional. Changes at once. "
     "Past 60 is experimental: the game keeps real time, but some cutscenes and bosses can misbehave (Gohma, the intro's "
     "narration). 60 is the safe choice. Uncapped: as fast as the PC can, still at real time; with V-Sync on, the display's "
     "refresh rate is the limit. 30 FPS always uses real-time game speed, even when Game speed is Per frame.",
     nullptr, false, true},
    {TAB_GRAPHICS, "NVIDIA Reflex", &opts.reflex, 0, 2, 1, tx_reflex,
     "NVIDIA GPUs: each frame starts as late as it can, for less input delay. With frame generation too: it paces the "
     "game's frames.", hn_reflex, false, true},
    {TAB_GRAPHICS, "AMD Anti-Lag 2", &opts.antilag, 0, 1, 1, tx_antilag,
     "AMD GPUs: each frame starts as late as it can, for less input delay. With frame generation too: it paces "
     "the game's frames.", hn_antilag, false, true},
    {TAB_GRAPHICS, "Screen", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    {TAB_GRAPHICS, "Fullscreen", &opts.fullscreen, 0, 1, 1, tx_onoff,
     "Fills the whole screen with the game, without the window's border. The same as F11.", nullptr, false, true},
    {TAB_GRAPHICS, "Fullscreen monitor", &monitor_pick, 0, 0, 1, tx_fullscreen_monitor,
     "Choose the screen used by Fullscreen, F11 and Alt+Enter. Auto uses the window's current monitor.", hn_fullscreen_monitor, false, true},
    {TAB_GRAPHICS, "V-Sync", &opts.vsync, 0, 2, 1, tx_vsync,
     "Whether a frame waits for the display's refresh before it is shown. Changes at once.", hn_vsync, false, true},
    {TAB_GRAPHICS, "Window scaling filter", &opts.upscale, 0, 2, 1, tx_filter,
     "How the finished picture is scaled to the window, when its size differs from the Output resolution.", hn_filter},
    {TAB_GRAPHICS, "CRT filter", &opts.crt_filter, 0, 4, 1, tx_crt_filter,
     "Filters the finished picture, including the game's HUD, after window effects. Hookshot's menu and overlays stay "
     "clean. Changes at once; quality presets leave it alone.", hn_crt_filter, false, true},
    {TAB_GRAPHICS, "CRT lines", &opts.crt_lines, 0, 2, 1, tx_crt_lines,
     "Virtual CRT raster, not Render resolution. Capped at half the destination height (at least one line); width follows "
     "its aspect. Non-integer scaling can cause moire.", hn_crt_lines, false, true},
    {TAB_GRAPHICS, "Ultrawide menus", &opts.wide_menus, 0, 2, 1, tx_wide_menus,
     "With the Aspect ratio at the monitor's shape: the pause, item and map menus, and what shows beside them. Loading "
     "screens and pre-rendered movies, which draw no world either, get the same sides. Changes at once.", hn_wide_menus, false, true},
    {TAB_GRAPHICS, "HUD layout", &opts.hud_layout, 0, 1, 1, tx_hud_layout,
     "On a screen that is not 16:9: where the hearts, buttons and minimap sit. Ultrawide menus places the menus; this, the "
     "HUD in play. At 16:9 both are the same. Changes at once.", hn_hud_layout, false, true},
    {TAB_GRAPHICS, "HDR", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    {TAB_GRAPHICS, "HDR", &opts.hdr, 0, 2, 1, tx_hdr,
     "HDR10 out on an HDR display (Windows: Use HDR on in the display settings). Expanded: the game's SDR picture, its white at "
     "the paper white and its highlights up to the peak. Native: the game's own HDR, told the display's peak and paper white.",
     nullptr, false, true},
    {TAB_GRAPHICS, "HDR paper white", &opts.hdr_white, 80, 400, 10, tx_nits,
     "How bright the picture's white is with HDR on. Around 200 for a normal room; higher in a bright one.", nullptr, false, true},
    {TAB_GRAPHICS, "HDR peak brightness", &opts.hdr_peak, 400, 4000, 100, tx_nits,
     "The brightest highlights with HDR on: set it to your display's peak brightness.", nullptr, false, true},
    {TAB_GRAPHICS, "HDR contrast", &opts.hdr_contrast, 50, 200, 5, tx_percent,
     "The HDR picture's contrast around mid grey, as the RenoDX HDR mods grade it: above 100% deeper shadows and brighter "
     "highlights, which ease into the peak brightness; below it flatter. With Native the game's own HDR picture is graded too, "
     "under the peak brightness the game is told.",
     nullptr, false, true},
    {TAB_GRAPHICS, "HDR tone mapper", &opts.hdr_tonemap, 0, 1, 1, tx_tonemap,
     "With Native, how the game's scene meets the peak brightness. Vanilla: the game's own curve. PsychoV35: RenoDX's "
     "tone mapper, the same mid grey with highlights that roll off into the peak and keep their colour.",
     nullptr, false, true},
    {TAB_GRAPHICS, "Detail", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    {TAB_GRAPHICS, "Anisotropic filtering", &opts.anisotropy, 0, 4, 1, tx_anisotropy,
     "Keeps textures sharp on surfaces seen at a slant, such as the ground ahead: higher is sharper in the distance, for a "
     "little GPU time. Game's is the console's own (1x or 2x).", nullptr, false, true},
    {TAB_GRAPHICS, "Shadow resolution", &opts.shadow_res, 0, 3, 1, tx_shadow_res,
     "The size of the sun's shadow maps: higher keeps the shadows of thin things near you, such as chains, fences and "
     "leaves, smooth instead of stair-stepped, for more video memory and a little GPU time. Applies at once.",
     hn_shadow_res},
    // (the rows to change when something is wrong, or on a card short of memory: last)
    {TAB_GRAPHICS, "GPU and memory", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    {TAB_GRAPHICS, "GPU device", &opts.gpu_device, 0, 8, 1, tx_gpu,
     "Which graphics card the game runs on. Applies after a restart.", hn_gpu, true, true},
    // (no Mesh shaders row: changing it translated every shader again at the next start, for nothing a player gains. A launch
    // switch now, RX_VK_MESH_SHADERS: gpu/vk/mesh_mode.h)

    // Audio
    {TAB_AUDIO, "Volume", &opts.volume, 0, 100, 5, tx_percent,
     "How loud the game plays. The game's own sound settings and Windows' volume still apply.", nullptr, false, true},
    {TAB_AUDIO, "Mute in background", &opts.mute_background, 0, 1, 1, tx_onoff,
     "Silences the game while another window has the focus. The sound comes back when you switch to the game.", nullptr,
     false, true},
    {TAB_AUDIO, "Output device", &output_pick, 0, 0, 1, tx_output_device,
     "Where the game plays sound. Changes apply without restarting the game.", hn_output_device, false, true},
    {TAB_AUDIO, "Speaker layout", &opts.audio_output, 0, 3, 1, tx_audio_output,
     "The speakers the game mixes for. Mono/Stereo changes live on stereo output; channel layout changes need a restart.", hn_audio_output, true, true},
    {TAB_AUDIO, "Microphone", &opts.mic, 0, 2 + kMaxMics, 1, tx_mic,
     "What the ocarina hears when the game's microphone option is on (playing an instrument, or humming).", hn_mic, false,
     true},
    {TAB_AUDIO, "Microphone gain", &opts.microphone_gain, 0, 400, 10, tx_percent,
     "Adjust capture for Hookshot only; system volume is unchanged. Use the microphone test to see live levels while adjusting gain. "
     "Changes apply to new samples.", nullptr, false, true},
    {TAB_AUDIO, "Test microphone", nullptr, 0, 0, 0, nullptr,
     "Start or stop microphone capture. No playback or audio files. You can adjust Microphone gain while testing. "
     "Leaving Audio, closing the menu or selecting Off stops the test; the game can still use the mic."},

    // Gameplay
    {TAB_GAMEPLAY, "FPS counter", &opts.show_fps, 0, fps_stats::kLevels - 1, 1, tx_fps_level,
     "Frames per second in the top right corner, and as much more as you choose.", hn_fps, false, true},
    {TAB_GAMEPLAY, "FPS counter position", &opts.fps_corner, 0, 3, 1, tx_fps_corner,
     "The corner the FPS counter shows in. While this menu is open it shows at the top right.", nullptr, false, true},
    {TAB_GAMEPLAY, "Performance monitor", &opts.resource_monitor, 0, 1, 1, tx_onoff,
     "CPU, frame time, VRAM, GPU time, RAM and FPS in panels on the left of the screen.", nullptr, false, true},
    {TAB_GAMEPLAY, "FPS counter size", &opts.fps_size, 0, 3, 1, tx_fps_size,
     "How large the FPS counter is drawn. Auto grows with the window, as the menu does; Small, Medium and Large keep one size "
     "whatever the window, the size Auto has in a 720p, 1080p and 1440p window.", nullptr, false, true},
    {TAB_GAMEPLAY, "FPS counter details", nullptr, 0, 0, 0, nullptr,   // (hookshot: opens its page, the TAB_FPS_DEV rows)
     "Which lines the FPS counter's Dev level shows, and whether the version and hardware show at every level."},
    // (hookshot) the FPS counter details page: the version at every level, then each of the Dev level's lines (opts.fps_dev_show:
    // fps_stats.h's DevLine order, then the CPU, GPU and driver)
    {TAB_FPS_DEV, "Version and hardware at every level", &opts.fps_version_always, 0, 1, 1, tx_onoff,
     "The version, as this menu's banner shows it, and the CPU, the GPU and its driver at the foot of the FPS counter at every "
     "level, not only at Dev: for screenshots and recordings. The CPU and GPU lines row below still turns those off.", nullptr,
     false, true},
    {TAB_FPS_DEV, "VRAM line", &opts.fps_dev_show[0], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Textures line", &opts.fps_dev_show[1], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Draws line", &opts.fps_dev_show[2], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Dispatches line", &opts.fps_dev_show[3], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Render passes line", &opts.fps_dev_show[4], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Draws skipped line", &opts.fps_dev_show[5], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Texture uploads line", &opts.fps_dev_show[6], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Pipelines built line", &opts.fps_dev_show[7], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "GPU slot waits line", &opts.fps_dev_show[8], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Queue submits line", &opts.fps_dev_show[9], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "Write-backs line", &opts.fps_dev_show[10], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_FPS_DEV, "CPU and GPU lines", &opts.fps_dev_show[11], 0, 1, 1, tx_onoff, kFpsDevLineHelp, nullptr, false, true},
    {TAB_GAMEPLAY, "Menu size", &opts.menu_size, 1, 3, 1, tx_menu_size,
     "How large this menu, the FPS counter and the start-up screen are drawn.", hn_menu_size, false, true},
    {TAB_GAMEPLAY, "Game speed", &opts.realtime, 0, 1, 1, tx_speed, "How the game keeps time when it runs below 60 fps. 30 FPS always uses real-time game speed, even when Game speed is Per frame.",
     hn_speed},
    {TAB_GAMEPLAY, "Field of view", &opts.fov, 50, 150, 5, tx_fov,
     "How much of the world you see: 100% is the original view. Higher is wider, lower is closer. Changes apply at once "
     "during gameplay. Cutscenes keep their own view.", nullptr, false, true},
    {TAB_GAMEPLAY, "Text speed", &opts.text_speed, 0, 3, 1, tx_text_speed,
     "How fast the letters of dialogue and other messages appear.", hn_text_speed, false, true},
    // (Mako) not part of the Quality preset: a change leaves it alone
    {TAB_GAMEPLAY, "Fast forward", &opts.fast_forward, 0, 2, 1, tx_fast_forward,
     "The ` key (under Esc), or both sticks clicked in together, makes the game run four times as fast: made for sitting "
     "through cutscenes.", hn_fast_forward, false, true},
    {TAB_GAMEPLAY, "Text size", &opts.text_size, 0, 4, 1, tx_text_size,
     "How large the text of dialogue, Navi and signs is drawn.", hn_text_size, false, true},
    {TAB_GAMEPLAY, "Skip title screen", &opts.skip_title, 0, 1, 1, tx_onoff,
     "Starts a launch with the most recent saved game: presses through the title screen and its file list. Does nothing "
     "until the game has a save. Applies after a restart.", nullptr, true, true},
    {TAB_GAMEPLAY, "Game language", &opts.game_lang, 0, i18n::game_lang_count() - 1, 1, tx_game_lang,
     "The game's own language, its text. Applies after a restart.", nullptr, true, true},
    {TAB_GAMEPLAY, "Menu language", &opts.menu_lang, 0, i18n::lang_count(), 1, tx_menu_lang, "The language of this menu.",
     hn_menu_lang, false, true},
    {TAB_GAMEPLAY, "Discord status", &opts.discord, 0, 1, 1, tx_onoff,
     "Shows \"Playing Hookshot\" and the time played in your Discord status, while Discord runs on this PC.", nullptr, false,
     true},
    {TAB_GAMEPLAY, "Skip opening", &opts.skip_opening, 0, 1, 1, tx_onoff,
     "Skips the new-game opening (the story movie and Navi waking Link) and leaves later cutscenes, the Deku Tree "
     "meeting, and the title screen alone.", nullptr, false, true},

    // Controls (17 rows; Motion opens the 6 TAB_MOTION rows, Controls its page with the 2 TAB_PAGE rows)
    {TAB_CONTROLS, "Controller in background", &opts.pad_background, 0, 1, 1, tx_onoff,
     "Whether the controller plays the game while another window has the focus.", hn_background, false, true},
    {TAB_CONTROLS, "Mouse camera", &opts.mouse_native, 0, 2, 1, tx_mousecam, "How the captured mouse turns the camera.",
     hn_mousecam, false, true},
    {TAB_CONTROLS, "Disable camera centering", &opts.disable_camera_centering, 0, 1, 1, tx_onoff,
     "Stops the camera gradually turning toward the direction you move, useful with native mouse look. Off keeps the "
     "game's standard behavior. Manual camera controls and recentering still work.", nullptr, false, true},
    {TAB_CONTROLS, "Mouse sensitivity", &opts.mouse_sens, 10, 500, 10, tx_sens,
     "How far the camera turns for a mouse movement, with either Mouse camera: at 1.00 native look turns 0.1 degree a "
     "count. The - and = keys change it in game too.", nullptr, false, true},
    {TAB_CONTROLS, "Invert mouse vertical", &opts.mouse_invert, 0, 1, 1, tx_onoff, "Swaps up and down for the mouse.",
     hn_mouse_invert, false, true},
    // (with Mouse camera on Native the game's own camera inversion, which turns the right stick around, never reaches
    // the mouse: this row is how its left and right are swapped, in both modes. No line about which way the camera
    // then turns: As the stick turns it as the game turns it for the right stick, which need not be Native's way)
    {TAB_CONTROLS, "Invert mouse horizontal", &opts.mouse_invert_x, 0, 1, 1, tx_onoff,
     "Swaps left and right for the mouse.", nullptr, false, true},
    {TAB_CONTROLS, "Invert camera X", &opts.invert_cam_x, 0, 1, 1, tx_onoff,
     "Inverts horizontal look (left/right) on the right analog stick.", nullptr, false, true},
    {TAB_CONTROLS, "Invert camera Y", &opts.invert_cam_y, 0, 1, 1, tx_onoff,
     "Inverts vertical look (up/down) on the right analog stick.", nullptr, false, true},
    {TAB_CONTROLS, "Camera speed", &opts.camera_speed, 50, 400, 25, tx_percent,
     "How fast the right stick turns the camera, in percent of the game's own speed; the camera keys too, and the mouse "
     "with Mouse camera As the stick. The game's own camera speed setting still applies.", nullptr, false, true},
    {TAB_CONTROLS, "Stick dead zone", &opts.stick_dead_zone, 0, 5, 1, tx_stick_dead_zone,
     "How far a stick moves from center in any direction before the game sees it. "
     "Lower for a precise stick, higher for one that drifts. "
     "The game's own dead zone still follows.", nullptr, false, true},
    {TAB_CONTROLS, "Rumble strength", &opts.rumble, 0, 150, 25, tx_rumble,
     "How strongly the controller rumbles, in percent of the game's rumble. Off turns it off.", nullptr, false, true},
    {TAB_MOTION, "Motion controls", &opts.gyro, 0, 1, 1, tx_gyro,
     "Aims and looks with the controller's gyroscope where the game uses motion, as on the Switch. Works with Switch Pro "
     "controllers and pads in Switch mode, DualSense and DualShock 4. Shown beside it: whether the connected pad has one.", hn_gyro,
     false, true},
    {TAB_MOTION, "Motion sensitivity X", &opts.gyro_sens_x, 10, 600, 10, tx_percent,
     "How far the aim moves left and right for a given turn of the controller. 100% is the console's own.", nullptr, false,
     true},
    {TAB_MOTION, "Motion sensitivity Y", &opts.gyro_sens_y, 10, 300, 10, tx_percent,
     "How far the aim moves up and down for a given tilt of the controller. 100% is the console's own.", nullptr, false,
     true},
    {TAB_MOTION, "Invert motion X", &opts.gyro_inv_x, 0, 1, 1, tx_onoff, "Turns the motion aim's left and right around.",
     nullptr, false, true},
    {TAB_MOTION, "Invert motion Y", &opts.gyro_inv_y, 0, 1, 1, tx_onoff, "Turns the motion aim's up and down around.",
     nullptr, false, true},
    {TAB_MOTION, "Motion deadzone", &opts.gyro_deadzone, 0, 2, 1, tx_deadzone,
     "How slow a turn counts as none, the console's three settings: Standard is its own. High steadies a pad that jitters "
     "when held still; Low keeps the smallest movements.", nullptr, false, true},
    {TAB_CONTROLS, "Motion", nullptr, 0, 0, 0, nullptr,   // (hookshot: opens the Motion page, the TAB_MOTION rows)
     "Motion controls: aiming with the controller's gyroscope, its sensitivity and its inverts."},
    // (hookshot) the Controls page's own rows, above its grid (TAB_PAGE: no tab shows them)
    {TAB_PAGE, "Layout preset", &opts.pad_layout, 0, 3, 1, tx_pad_layout,
     "Which face button is which. Binding one yourself on the Controls page makes it Custom.", hn_pad_layout, false, true},
    {TAB_PAGE, "Button prompts", &opts.prompts, 0, HOS_PROMPT_N, 1, tx_prompts,
     "The button icons the game shows, in its texts and menus: those of this controller, for the buttons your controls "
     "put each action on.", hn_prompts, true, true},
    {TAB_CONTROLS, "Walk mode", &opts.walk_mode, 0, 1, 1, tx_walk_mode,
     "How the Walk key makes Link walk with the movement keys: while it is held, or from one press to the next. It is Caps "
     "Lock unless the Controls page changes it.", hn_walk_mode, false, true},
    {TAB_CONTROLS, "Walk speed", &opts.walk_speed, 15, 90, 5, tx_percent,
     "How far the movement keys tilt the stick while Link walks, in percent of the whole way. Controllers, the mouse and "
     "the camera keys are not changed.", nullptr, false, true},
    {TAB_CONTROLS, "Controls", nullptr, 0, 0, 0, nullptr,   // (hookshot: opens its page)
     "The layout preset, the button prompts, and which gamepad button and which keys press each of the Switch's "
     "buttons."},
    {TAB_CONTROLS, "Menu shortcut", &opts.menu_shortcut, 0, 2, 1, tx_menu_shortcut,
     "Which keys open and close this menu. F1 always does; F1 only leaves Insert free for an overlay. With Esc, Esc opens it "
     "too, as a PC game's pause menu (open, Esc still goes back a page or closes it).",
     nullptr, false, true},
    {TAB_CONTROLS, "Compact menu key", &opts.compact_menu_key, 0, 1, 1, tx_compact_menu_key,
     "Which key switches between the full menu and the compact bar (or opens directly to the compact bar when held "
     "with the menu shortcut).",
     nullptr, false, true},
    // Debug: the tools' switch, the tools themselves below it while they are on (cheat: menu_tick does what they do), then the
    // developer's rows
    {TAB_DEBUG, "Debug tools", &opts.debug_tools, 0, 1, 1, tx_onoff,
     "Testing tools: no-clip flight, a free camera, teleport, Link's age, the inventory, the clock, heart protection and "
     "movement speed. Off puts flight, the free camera and heart protection away and Link back to his own speed and damage.", nullptr, false, true},
    {TAB_DEBUG, "Heart protection", nullptr, 0, 0, 0, nullptr,
     "Protects Link's hearts. Hits can still knock him back.", nullptr, false, true, 0},
    {TAB_DEBUG, "Autosave:", &opts.transition_autosave, 0, 1, 1, tx_onoff,
     "Works with Debug tools off. Turning it off skips supported autosaves. You can still save manually.", nullptr, false, true},
    {TAB_DEBUG, "Damage taken", &opts.damage_taken, 0, 3, 1, tx_damage_taken,
     "How much health Link loses from a hit. Normal is unchanged. Half rounds up to the next quarter heart. "
     "Changes apply at once; healing is unchanged. Heart protection takes priority. Debug tools Off makes it Normal "
     "until they are on again.", nullptr, false, true},
    {TAB_DEBUG, "No-clip flight", nullptr, 0, 0, 0, nullptr,
     "Enable double-tap Jump for takeoff and landing. Hold Jump to climb or L to descend.", nullptr, false, true, 1},
    {TAB_DEBUG, "Mark position", nullptr, 0, 0, 0, nullptr,
     "Remember Link's position for this loaded scene.", nullptr, false, true, 2},
    {TAB_DEBUG, "Return to mark", nullptr, 0, 0, 0, nullptr,
     "Teleport Link to the marked position in the current scene.", nullptr, false, true, 3},
    {TAB_DEBUG, "Set time", nullptr, 0, 0, 0, nullptr,
     "Choose an hour with Left or Right. Enter sets the world clock.", nullptr, false, true, 4},
    {TAB_DEBUG, "Inventory item", nullptr, 0, 0, 0, nullptr,
     "Choose a consumable with Left or Right.", nullptr, false, true, 5},
    {TAB_DEBUG, "Change quantity", nullptr, 0, 0, 0, nullptr,
     "Choose how many to add or remove. Enter applies the change.", nullptr, false, true, 6},
    {TAB_DEBUG, "Free camera", nullptr, 0, 0, 0, nullptr,
     "Move and look with your usual controls. Page Up / Page Down or R / L changes height.", nullptr, false, true, 7},
    {TAB_DEBUG, "Teleport", nullptr, 0, 0, 0, nullptr,
     "Opens the map list. Link travels through the game's own map change, in his current age.", nullptr, false, true, 8},
    {TAB_DEBUG, "Switch age", nullptr, 0, 0, 0, nullptr,
     "Swaps Link between child and adult and reloads this map in the other age (the Market when this map has no match).", nullptr, false, true, 9},
    {TAB_DEBUG, "Inventory", nullptr, 0, 0, 0, nullptr,
     "Enter opens the inventory editor: unlock or relock equipment, items, upgrades and quest items, and change amounts.", nullptr, false, true, 10},
    {TAB_DEBUG, "Movement speed", nullptr, 0, 0, 0, nullptr,
     "How fast Link walks, runs and swims, as a multiple of his own speed. Choose with Left or Right.", nullptr, false, true, 11},
    {TAB_DEBUG, "Developer", nullptr, 0, 0, 0, nullptr, nullptr, nullptr, false, true, -1, true},
    // (hookshot, first under the heading: debug_rows lists only those) the zip for the "Submit your pipelines" issue: share_pipeline_list, pipeline_share.h
    {TAB_DEBUG, "Save my pipeline list", nullptr, 0, 0, 0, nullptr,
     "Helps remove first-load stutter for everyone: saves the pipelines your play built (shader hashes and draw state, no game "
     "data) with a filled-in report as a zip in Downloads, copies the report and opens the \"Submit your pipelines\" issue. "
     "Attach the zip there and paste the report. Nothing is uploaded for you."},
    // (hookshot) for testing, not a player's choice: when each made frame is shown (vk_framegen.cpp)
    {TAB_DEBUG, "Frame pacing", &opts.pace, 0, 1, 1, tx_onoff, "When each frame is shown.", hn_pace},
    // (hookshot, threaded_rendering.h: the render thread and the recorder thread together, one row. Auto, On, Off as V-Sync's,
    // so its text is tx_vsync's. Read once, at the start: menu_threaded_rendering)
    {TAB_DEBUG, "Threaded rendering", &opts.threaded_rendering, 0, 2, 1, tx_vsync,
     "Draws the picture on threads of its own, beside the game's, on a processor with threads to spare. Applies after a "
     "restart.", hn_threaded, true, true},
    {TAB_DEBUG, "Descriptor reuse", &opts.descriptor_reuse, 0, 1, 1, tx_onoff,
     "A draw keeps its descriptors while the texture slots it samples are unchanged, so streaming elsewhere in the game no longer "
     "rebuilds every set each frame. Changes at once.", nullptr, false, true},
    {TAB_DEBUG, "Sampler cache", &opts.sampler_cache, 0, 1, 1, tx_onoff,
     "What a sampler holds is kept beside it on the replay thread, so resolving a sampler that was not registered anew takes no "
     "lock. Helps while the game streams textures. Changes at once.", nullptr, false, true},
    {TAB_DEBUG, "Robust buffers", &opts.robust, 0, 2, 1, tx_robust,
     "Bounds-checked buffer reads: a read past a buffer's end is dropped instead of stopping the GPU. Applies after a "
     "restart.", hn_robust, true, true},
    {TAB_DEBUG, "ASTC as RGBA8", &opts.astc_rgba8, 0, 1, 1, tx_onoff,
     "Big ASTC textures kept as decoded RGBA8 instead of re-encoded to BC3: a workaround for texture artifacts seen on some AMD "
     "cards (issues 57 and 1006). Takes far more video memory. Applies after restart.", hn_astc_rgba8, true, true},
    // (hookshot, Intel graphics on Windows only: row_shown) IntelDriverGate, vk_internal.h
    {TAB_DEBUG, "Intel shader compiles", &opts.intel_compiles, 0, 2, 1, tx_intel_compiles,
     "Intel graphics: how many shaders Intel's compiler is given at once. Applies after a restart.", hn_intel_compiles, true, true},
    // Tracker: a row for each line of the seed's tracker file (tracker_load), named and valued by it
#define TRACKER_ROW(i) {TAB_TRACKER, tracker_name[i], nullptr, 0, 0, 0, nullptr, kTrackerHelp, nullptr, false, true, -1, false, i},
    TRACKER_ROW(0)
    TRACKER_ROW(1)
    TRACKER_ROW(2)
    TRACKER_ROW(3)
    TRACKER_ROW(4)
    TRACKER_ROW(5)
    TRACKER_ROW(6)
    TRACKER_ROW(7)
    TRACKER_ROW(8)
    TRACKER_ROW(9)
    TRACKER_ROW(10)
    TRACKER_ROW(11)
    TRACKER_ROW(12)
    TRACKER_ROW(13)
    TRACKER_ROW(14)
    TRACKER_ROW(15)
    TRACKER_ROW(16)
    TRACKER_ROW(17)
    TRACKER_ROW(18)
    TRACKER_ROW(19)
    TRACKER_ROW(20)
    TRACKER_ROW(21)
    TRACKER_ROW(22)
    TRACKER_ROW(23)
    TRACKER_ROW(24)
    TRACKER_ROW(25)
    TRACKER_ROW(26)
    TRACKER_ROW(27)
    TRACKER_ROW(28)
    TRACKER_ROW(29)
    TRACKER_ROW(30)
    TRACKER_ROW(31)
    TRACKER_ROW(32)
    TRACKER_ROW(33)
    TRACKER_ROW(34)
    TRACKER_ROW(35)
    TRACKER_ROW(36)
    TRACKER_ROW(37)
    TRACKER_ROW(38)
    TRACKER_ROW(39)
    TRACKER_ROW(40)
    TRACKER_ROW(41)
    TRACKER_ROW(42)
    TRACKER_ROW(43)
    TRACKER_ROW(44)
    TRACKER_ROW(45)
    TRACKER_ROW(46)
    TRACKER_ROW(47)
#undef TRACKER_ROW
    // (hookshot, Intel graphics on Windows only: row_shown) vk_draw.cpp compute_optimize
    {TAB_DEBUG, "Intel quick compute builds", &opts.intel_quick, 0, 1, 1, tx_onoff,
     "Intel graphics, shaders one at a time: a pass over the scene (its light, its exposure) is built first without the "
     "compiler's optimizer, in seconds instead of minutes, and drawn with until the optimized one is ready. Changes at once.",
     nullptr, false, true},
    // (hookshot, integrated graphics only: row_shown) weak_laptop_apply
    {TAB_DEBUG, "Set up for a weak laptop", nullptr, 0, 0, 0, nullptr,
     "For integrated graphics with 4 CPU threads or fewer (an i3 laptop's UHD Graphics): Render resolution 33% with the game's own "
     "upscaler, the plain window scale without sharpening, the handheld profile, smaller textures, Intel's shaders "
     "one at a time and quick compute builds. The handheld profile applies after a restart."},
    // (hookshot) the Gameplay tab's Bug report (vk_bug_report.h): A or Enter writes the report's folder; the help says what is in it
    {TAB_GAMEPLAY, "Bug report", nullptr, 0, 0, 0, nullptr,
     "Saves what an issue needs in a new folder, bug-reports in the game folder: report.txt with the issue form's answers (this "
     "version, where you are, your graphics card and driver, CPU, RAM and system, the options and switches you changed), the logs "
     "of this run and the last one, and a picture of the game. Your user name and home folder are taken out of them. No saves "
     "or game files go in, and nothing is sent."},
    // (Restart and Quit stay the table's last two: kRestartRow and kQuitRow count back from its end; Bug report is before them)
    {TAB_GAMEPLAY, "Restart", nullptr, 0, 0, 0, nullptr,
     "Starts the game again. Save your progress first. Press Enter or A twice to restart. Esc or B "
     "cancels."},
    {TAB_GAMEPLAY, "Quit", nullptr, 0, 0, 0, nullptr,
     "Save your progress first. Press Enter or A twice to quit. Esc or B cancels."},
};
constexpr int kQuitRow = sizeof rows / sizeof rows[0] - 1;
constexpr int kRestartRow = kQuitRow - 1;
constexpr int kBugReportRow = kRestartRow - 1;
const Row* pending = nullptr;   // (Restart or Quit: shows Confirm until its second press)
bool cheats_env = false;   // (HOS_OOT_CHEATS=1: on whatever the Debug tab says)
/// The debug tools: the Debug tab's row, or HOS_OOT_CHEATS=1
bool cheats_on() { return cheats_env || opts.debug_tools; }
std::atomic<bool> transition_autosave_enabled{true};
void sync_transition_autosave() {
    transition_autosave_enabled.store(opts.transition_autosave != 0, std::memory_order_relaxed);
}
std::atomic<int> protect_hearts{-1};
// -1 disables the shortcut, 0 enables it on the ground, and 1 means flying.
std::atomic<int> player_flight{-1};
std::atomic<int> free_camera{0};
std::atomic<int> cheat_action{0};
std::atomic<int> link_age{-1};
// (Movement speed: the choice, an index of link_speeds; the game side reads it in percent, HOS_OPT_CHEAT_SPEED)
constexpr int link_speeds[] = {100, 125, 150, 200, 300};
constexpr const char* link_speed_names[] = {"1x", "1.25x", "1.5x", "2x", "3x"};
constexpr int kLinkSpeeds = sizeof link_speeds / sizeof link_speeds[0];
std::atomic<int> link_speed{0};   // (the game side's report, OOT_CHEAT_AGE_ID: 0 child, 1 adult, -1 no save loaded)
int clock_hour = 12;
int pouch_item = 0;
int pouch_delta = 1;
constexpr const char* pouch_items[] = {"Deku Seeds", "Deku Nuts", "Deku Sticks", "Bombs", "Arrows"};
constexpr int kPouchItems = sizeof pouch_items / sizeof pouch_items[0];
// (teleport list: generated by work/oot-teleport-tools/write_destinations.py)
// (the order of oot_destinations in host/hos_main.c; Enter sends 1000 + the index)
constexpr const char* teleport_names[] = {
    "Kokiri Forest",
    "Hyrule Field",
    "Kakariko Village",
    "Market",
    "Hyrule Castle",
    "Lost Woods",
    "Sacred Forest Meadow",
    "Lake Hylia",
    "Graveyard",
    "Death Mountain Trail",
    "Death Mountain Crater",
    "Goron City",
    "Zora's River",
    "Zora's Domain",
    "Zora's Fountain",
    "Gerudo Valley",
    "Gerudo Fortress",
    "Haunted Wasteland",
    "Desert Colossus",
    "Inside the Deku Tree",
    "Dodongo's Cavern",
    "Jabu-Jabu's Belly",
    "Forest Temple",
    "Fire Temple",
    "Water Temple",
    "Shadow Temple",
    "Spirit Temple",
    "Bottom of the Well",
    "Ice Cavern",
    "Gerudo Training Ground",
    "Ganon's Castle",
    // (the randomizer's fork: the bosses' rooms, oot_boss_rooms in host/hos_main.c, in its order after the places)
    "Gohma",
    "King Dodongo",
    "Barinade",
    "Phantom Ganon",
    "Volvagia",
    "Morpha",
    "Bongo Bongo",
    "Twinrova",
    "Ganondorf"};
constexpr const char* teleport_notes[] = {nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "adult only", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,
    "Deku Tree", "Dodongo's Cavern", "Jabu-Jabu's Belly", "Forest Temple", "Fire Temple", "Water Temple", "Shadow Temple", "Spirit Temple", "Ganon's Castle"};
struct TeleportSection { const char* name; int first; };
constexpr TeleportSection teleport_sections[] = {{"Overworld", 0}, {"Dungeons", 19}, {"Bosses", 31}};
constexpr int kTeleportSections = sizeof teleport_sections / sizeof teleport_sections[0];
// (end of the generated teleport list)
constexpr int kTeleports = sizeof teleport_names / sizeof teleport_names[0];
static_assert(sizeof teleport_notes / sizeof teleport_notes[0] == kTeleports, "a teleport card without its note");
int teleport_choice = 0;
int teleport_columns = 1, teleport_page_rows = 1;   // (as last drawn: the cards in a row, the rows that fit: Page Up / Down)
float teleport_scroll_px = 0, teleport_want_px = 0;   // (the cards' scroll, eased toward teleport_want_px)
bool teleport_follow = true;   // (the scroll follows the choice; the wheel lets go of it until the choice moves)
int teleport_wheel = 0;        // (the wheel's notches since the last drawing: it scrolls by them)
int teleport_section_of(int i) {
    int section = 0;
    while (section + 1 < kTeleportSections && i >= teleport_sections[section + 1].first) ++section;
    return section;
}
int teleport_section_end(int section) {
    return section + 1 < kTeleportSections ? teleport_sections[section + 1].first : kTeleports;
}
/// The destination rows rows down (up when negative) from i, in the grid the Teleport page draws: each section's cards
/// teleport_columns to a row, under the section's heading; the column kept where the next row has it
int teleport_step_rows(int i, int rows) {
    const int cols = std::max(1, teleport_columns);
    for (; rows > 0; --rows) {
        const int section = teleport_section_of(i), first = teleport_sections[section].first, end = teleport_section_end(section);
        const int p = i - first;
        if (p + cols < end - first) i += cols;
        else if (p / cols < (end - first - 1) / cols) i = end - 1;   // (the section's last row, a short one)
        else if (section + 1 < kTeleportSections) i = std::min(end + p % cols, teleport_section_end(section + 1) - 1);
        else break;
    }
    for (; rows < 0; ++rows) {
        const int section = teleport_section_of(i), first = teleport_sections[section].first, p = i - first;
        if (p >= cols) i -= cols;
        else if (section > 0) {
            const int prev = teleport_sections[section - 1].first, n = first - prev;
            i = std::min(prev + (n - 1) / cols * cols + p, first - 1);
        } else break;
    }
    return i;
}
// the Inventory page (gpu/vk/oot_cheat_items.h): items and their section headings, counts from the game side
#define OOT_MENU_ITEM_LABEL(label, name, kind) label,
#define OOT_MENU_ITEM_KIND(label, name, kind) kind,
#define OOT_MENU_NO_SECTION(name)
constexpr const char* item_names[] = {OOT_CHEAT_ITEMS(OOT_MENU_NO_SECTION, OOT_MENU_ITEM_LABEL)};
constexpr unsigned char item_kinds[] = {OOT_CHEAT_ITEMS(OOT_MENU_NO_SECTION, OOT_MENU_ITEM_KIND)};
constexpr int kItems = sizeof item_names / sizeof item_names[0];
// (each section's first item: a counter that a section heading reads and an item bumps)
constexpr int item_section_count() {
    int n = 0;
#define OOT_MENU_COUNT_SECTION(title) n++;
#define OOT_MENU_SKIP_ITEM(label, name, kind)
    OOT_CHEAT_ITEMS(OOT_MENU_COUNT_SECTION, OOT_MENU_SKIP_ITEM)
    return n;
}
constexpr int kItemSections = item_section_count();
struct ItemSections { TeleportSection s[kItemSections]; };
constexpr ItemSections make_item_sections() {
    ItemSections r{};
    int section = 0, item = 0;
#define OOT_MENU_ADD_SECTION(title) r.s[section].name = title, r.s[section].first = item, section++;
#define OOT_MENU_ADD_ITEM(label, name, kind) item++;
    OOT_CHEAT_ITEMS(OOT_MENU_ADD_SECTION, OOT_MENU_ADD_ITEM)
    return r;
}
constexpr ItemSections item_sections = make_item_sections();
std::atomic<int> item_counts[kItems];   // (-1 until the game side reports: OOT_CHEAT_ITEM_BASE + i)
// (the randomizer) The gating items of the seed's rules (tools/rando/rando_seed.py CHECK_CODES: the same letters, in its
// order), each with the Inventory page's rows that stand for it: a bigger bag, the stronger gauntlets and the deeper
// scale do what the one asked for does.
struct LogicItem {
    const char *code, *name, *rows[3];
};
constexpr LogicItem kLogicItems[] = {
    {"KS", "Kokiri Sword", {"Kokiri Sword"}},
    {"SL", "Fairy Slingshot", {"Fairy Slingshot"}},
    {"BB", "Bomb Bag", {"Bomb Bag", "Big Bomb Bag", "Biggest Bomb Bag"}},
    {"BM", "Boomerang", {"Boomerang"}},
    {"LT", "Lens of Truth", {"Lens of Truth"}},
    {"BW", "Fairy Bow", {"Fairy Bow"}},
    {"HM", "Megaton Hammer", {"Megaton Hammer"}},
    {"IB", "Iron Boots", {"Iron Boots"}},
    {"HB", "Hover Boots", {"Hover Boots"}},
    {"LS", "Longshot", {"Longshot"}},
    {"SG", "Silver Gauntlets", {"Silver Gauntlets", "Golden Gauntlets"}},
    {"MS", "Mirror Shield", {"Mirror Shield"}},
    {"GG", "Golden Gauntlets", {"Golden Gauntlets"}},
    {"GB", "Goron's Bracelet", {"Goron's Bracelet", "Silver Gauntlets", "Golden Gauntlets"}},
    {"SS", "Silver Scale", {"Silver Scale", "Golden Scale"}},
    {"AW", "Adult's Wallet", {"Adult's Wallet", "Giant's Wallet"}},
    {"GW", "Giant's Wallet", {"Giant's Wallet"}},
    // (Songs: the seven that gate the game. tools/rando/rando_seed.py SONG_GATES)
    {"ZL", "Zelda's Lullaby", {"Zelda's Lullaby"}},
    {"EP", "Epona's Song", {"Epona's Song"}},
    {"SR", "Saria's Song", {"Saria's Song"}},
    {"ST", "Song of Time", {"Song of Time"}},
    {"SO", "Song of Storms", {"Song of Storms"}},
    {"RQ", "Requiem of Spirit", {"Requiem of Spirit"}},
    {"NC", "Nocturne of Shadow", {"Nocturne of Shadow"}},
    // (The tunics, placement 12: tools/rando/rando_seed.py TUNICS)
    {"GT", "Goron Tunic", {"Goron Tunic"}},
    {"ZT", "Zora Tunic", {"Zora Tunic"}},
    // (a bottle, placement 13: a bean-soil Gold Skulltula's bugs. tools/rando/rando_seed.py BOTTLE, bug 84)
    {"BO", "a bottle", {"Empty Bottle"}},
};
// (a rule's "T<N>": N Gold Skulltula tokens, by the Inventory page's count of them. tools/rando/rando_seed.py token_codes,
// placement 12: the Skulltula house's rewards)
constexpr const char* kTokenRow = "Gold Skulltula Tokens";
int tracker_in_logic(const TrackerCheck& k, std::string* missing) {
    if (k.needs[0] == '?' || item_counts[0].load(std::memory_order_relaxed) < 0) return -1;
    // (a rule's ways, apart by "/": in logic when one of them is held; missing is said of the way with the fewest)
    std::string best;
    int best_left = -1;
    for (const char* way = k.needs; *way; way += strcspn(way, "/"), way += *way == '/') {
        std::string left;
        const int held = tracker_way_held(way, strcspn(way, "/"), &left);
        if (held) return 1;
        const int count = (int)std::count(left.begin(), left.end(), ',') + 1;
        if (best_left < 0 || count < best_left) best_left = count, best = left;
    }
    if (missing) *missing = best;
    return 0;
}
/// One way of a rule (its letters with commas, `len` of them; "-" nothing): 1 when Link carries all of it, else 0 and
/// what he has not, by name, in missing
int tracker_way_held(const char* way, size_t len, std::string* missing) {
    int in = 1;
    const char* end = way + len;
    for (const char* p = way; p < end && *p != '-'; p += strcspn(p, ",/"), p += p < end && *p == ',') {
        const size_t n = std::min((size_t)(end - p), strcspn(p, ",/"));
        bool known = false, has = false;
        const char* name = "an item this menu does not know";
        if (n >= 2 && p[0] == 'T' && strspn(p + 1, "0123456789") >= n - 1) {   // ("T<N>": N Gold Skulltula tokens, the Skulltula house's rewards)
            const int want = atoi(p + 1);
            for (int i = 0; i < kItems; i++)
                if (!strcmp(item_names[i], kTokenRow) && item_counts[i].load(std::memory_order_relaxed) >= want) has = true;
            if (has) continue;
            in = 0;
            if (missing) *missing += (missing->empty() ? "" : ", ") + std::to_string(want) + " Gold Skulltula tokens";
            continue;
        }
        for (const LogicItem& item : kLogicItems) {
            if (strlen(item.code) != n || strncmp(item.code, p, n)) continue;
            known = true, name = item.name;
            for (const char* row : item.rows)
                for (int i = 0; row && i < kItems; i++)
                    if (!strcmp(item_names[i], row) && item_counts[i].load(std::memory_order_relaxed) > 0) has = true;
        }
        if (known && has) continue;
        in = 0;
        if (missing) *missing += (missing->empty() ? "" : ", ") + std::string(name);
    }
    return in;
}
int item_choice = 0;
int inventory_columns = 1, inventory_capacity = 1;   // (as last drawn: the cards in a row, on a page)
int inventory_filter = 0;   // (All, then the item sections)
int inventory_page = 0;     // (the page shown: the choice's, or another the wheel turned to)
bool inventory_amount = false;   // (Left and Right change the chosen item's amount)
int inventory_begin() { return inventory_filter ? item_sections.s[inventory_filter - 1].first : 0; }
int inventory_end() { return inventory_filter && inventory_filter < kItemSections ? item_sections.s[inventory_filter].first : kItems; }
void inventory_reveal() { inventory_page = (item_choice - inventory_begin()) / std::max(1, inventory_capacity); }
void choose_inventory_filter(int filter) {
    inventory_filter = filter;
    item_choice = inventory_begin();
    inventory_amount = false;
    inventory_reveal();
}
constexpr int kCheatRows = 12;   // (the debug tools' rows: Row::cheat 0 to 11)
/// A debug tool's value as its row shows it ("" an action: confirm does it)
std::string cheat_value(int i) {
    char t[16];
    switch (i) {
    case 0: return tx_onoff(protect_hearts.load() == 1);
    case 1: return tx_onoff(player_flight.load() >= 0);
    case 4: return snprintf(t, sizeof t, "%02d:00", clock_hour), t;
    case 5: return pouch_items[pouch_item];
    case 6: return snprintf(t, sizeof t, "%+d", pouch_delta), t;
    case 7: return tx_onoff(free_camera.load());
    case 11: return link_speed_names[std::clamp(link_speed.load(), 0, kLinkSpeeds - 1)];
    default: return "";
    }
}
/// The tools that choose with Left and Right (arrows at their value's ends): Set time, Inventory item, Change quantity,
/// Movement speed
bool cheat_chooses(int i) { return i == 4 || i == 5 || i == 6 || i == 11; }
/// Switch age as Kid | Adult, Link's age lit: once the game side has said it (a save loaded)
bool age_shown(int i) { return i == 9 && link_age.load(std::memory_order_relaxed) >= 0; }
/// What confirm does on a tool's row, for its prompt (nullptr: nothing)
const char* cheat_confirm(int i) {
    static const char* const says[kCheatRows] = {"Toggle", "Toggle", "Apply", "Apply", "Set", nullptr, "Apply", "Toggle", "Open list",
                                                 "Switch", "Open", nullptr};
    return i >= 0 && i < kCheatRows ? says[i] : nullptr;
}
/// The button label on an action tool's row ("": not a button action)
const char* cheat_button_text(int i) {
    static const char* const buttons[kCheatRows] = {"", "", "Mark", "Return", "", "", "", "", "Choose map", "Switch", "Edit items", ""};
    return i >= 0 && i < kCheatRows ? buttons[i] : "";
}
constexpr int kRows = sizeof rows / sizeof rows[0];

int ultrawide_read = 1;   // (ultrawide= as read: saved again while HOS_OUTPUT_RES holds the Output resolution and the row is as it was)
/// (hookshot) The Aspect ratio and Output resolution rows' ends from the screen's sizes and the player's own (known once the
/// options and HOS_OUTPUT_RES are read), and the Aspect ratio of the size chosen: a size of a shape of its own is that shape,
/// a 16:9 one is the monitor's shape or 16:9, as ultrawide= says (menu_init, before restart_init: what the run starts with)
void outputs_sync() {
    const std::vector<dm::Shape> shapes = output_shapes();
    for (Row& r : rows) {
        if (r.value == &opts.output_res) r.hi = last_choice();
        if (r.value == &opts.ultrawide) r.hi = aspect_last();
    }
    ultrawide_read = std::clamp(opts.ultrawide, 0, 1);
    opts.ultrawide = aspect_started = aspect_of_choice(opts.output_res, ultrawide_read);
    output_started = opts.output_res;
    std::string list;
    for (const dm::Shape& s : shapes) list += (list.empty() ? "" : ", ") + s.name;
    logf("vk: the Output resolution's sizes: %d (%s, with the common sizes of their shapes, and the game's own)%s; shapes %s",
         custom_index(), getenv("HOS_DISPLAY_MODES") ? "HOS_DISPLAY_MODES" : "the screen's modes",
         custom_output.w ? ", and one of the player's own" : "", list.c_str());
}

int cur_tab = TAB_GRAPHICS;
int tab_selected[TAB_FPS_DEV + 1] = {};   // (and the pages' a row opens: Motion, the FPS counter's details)
bool is_motion_row(const Row& r) { return r.tab == TAB_CONTROLS && !r.value && !strcmp(r.name, "Motion"); }
bool is_fps_dev_row(const Row& r) { return r.tab == TAB_GAMEPLAY && !r.value && !strcmp(r.name, "FPS counter details"); }

// ---- the rows that take a restart: their values at the start (menu_init, the GPU's at menu_set_gpu_count) ----
namespace mr = menu_restart;
mr::State restart_state;
int restart_slot[kRows];             // (a row's slot in restart_state, -1 none)
const char* restart_names[mr::kMax];
/// (hookshot) A row's value as a restart compares it: the Output resolution's size itself, so another size of the player's own
/// (Custom output size), on the same choice, is a change too. Mono and Stereo share a channel layout and change live.
int row_restart_value(const Row& r) {
    if (r.value == &opts.audio_output && *r.value == 3) return 1;
    if (r.value != &opts.output_res) return *r.value;
    const Out o = output_at(*r.value);
    return (int)(o.w << 16 | o.h);
}
void restart_init() {
    static bool done = false;
    if (done) return;
    done = true;
    opts.game_lang = i18n::game_lang_index();   // (language.txt's, the language the game started in)
    for (int i = 0; i < kRows; i++) {
        restart_slot[i] = rows[i].restart && rows[i].value ? restart_state.add(row_restart_value(rows[i])) : -1;
        if (restart_slot[i] >= 0) restart_names[restart_slot[i]] = rows[i].name;
    }
}
int restart_slot_of(const Row& r) { return restart_slot[&r - rows]; }
/// A row that takes a restart, changed from what the game started with (a row past menu_restart.h's kMax has no slot: never)
bool restart_changed(const Row& r) {
    const int slot = restart_slot_of(r);
    return r.value && r.restart && slot >= 0 && row_restart_value(r) != restart_state.start[slot];
}
void restart_values(int* now) {
    for (int i = 0; i < kRows; i++)
        if (restart_slot[i] >= 0) now[restart_slot[i]] = row_restart_value(rows[i]);
}
/// The rows whose value is not the one the game runs with (a bit a slot)
unsigned restart_pending() {
    int now[mr::kMax];
    restart_values(now);
    return restart_state.pending(now);
}
/// Whether closing the menu now asks to restart: something pending, not declined with Later, and a window to close
bool restart_ask() {
    int now[mr::kMax];
    restart_values(now);
    return app_window() && restart_state.ask(now);
}
/// The rows' names in the menu's language, for the restart line and question
const char* const* tr_names() {
    static const char* t[mr::kMax];
    for (int i = 0; i < restart_state.n; i++) t[i] = i18n::tr(restart_names[i]);
    return t;
}
std::string restart_list(const char* last) {
    return mr::names(tr_names(), restart_state.n, restart_pending(), ", ", last);
}
int ask_sel = 0;   // (the restart question's choice: 0 Later, 1 Restart now)

/// A row on its tab: the debug tools only with them on; a row for what this PC cannot run not at all (Reflex and Anti-Lag 2
/// only where the driver has them, the Upscaler only where more than the game's own runs, the DLSS model only where DLSS
/// runs); HDR's paper white, peak brightness and contrast only with HDR on. A row that comes or goes moves those after it: the
/// selection is a place on its tab (tab_selected), so a row hidden after the selected one leaves the selection where it is,
/// and menu_tick brings back one past the end
/// (hookshot) The Intel shader compiles row: Intel graphics on Windows, the only place IntelDriverGate holds the compiler
bool intel_compiler_row() {
#ifdef _WIN32
    return dev.props.vendorID == 0x8086;
#else
    return false;
#endif
}
bool laptop_row() { return dev.props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU; }   // (Set up for a weak laptop)
bool is_laptop_row(const Row& r) { return !r.value && r.tab == TAB_DEBUG && !strcmp(r.name, "Set up for a weak laptop"); }
bool is_share_row(const Row& r);
bool row_shown(int i) {
    const int* v = rows[i].value;
    // (Mako 4.2: Longshot's Bug report and Save my pipeline list are not shown: Mako's reports go through the launcher's
    // Send logs)
    if (i == kBugReportRow || is_share_row(rows[i])) return false;
    return ((rows[i].cheat < 0 && v != &opts.damage_taken) || cheats_on()) && rows[i].tracker < tracker_count &&
           !(rows[i].tracker > 0 && tracker_row_hidden(rows[i].tracker)) && (v != &opts.reflex || reflex_available()) &&
           (v != &opts.antilag || antilag_available()) && (v != &opts.intel_compiles || intel_compiler_row()) &&
           (v != &opts.intel_quick || intel_compiler_row()) &&
           (!is_laptop_row(rows[i]) || laptop_row()) &&
           (v != &opts.dlss || ur::upscaler_shown(upscalers_available())) &&
           (v != &opts.dlss_model || ur::model_shown(dlss_why() == DLSS_OK)) &&
           ((v != &opts.hdr_white && v != &opts.hdr_peak && v != &opts.hdr_contrast) || opts.hdr != 0) &&
           (v != &opts.hdr_tonemap || opts.hdr == 2) &&
           // (hookshot) who makes the frames only with Frame generation on; the CRT raster only with a CRT filter
           (v != &opts.framegen_by || opts.framegen != 0) && (v != &opts.crt_lines || opts.crt_filter != 0);
}
int tab_row_count(int t) {
    if (t == TAB_TRACKER) tracker_load();   // (the seed's file, read again at most once a second)
    int c = 0;
    for (int i = 0; i < kRows; i++) if (rows[i].tab == (MenuTab)t && row_shown(i)) c++;
    return c;
}

int tab_row_to_global(int t, int local_idx) {
    int count = 0;
    for (int i = 0; i < kRows; i++) {
        if (rows[i].tab == (MenuTab)t && row_shown(i)) {
            if (count == local_idx) return i;
            count++;
        }
    }
    return 0;
}

std::atomic<bool> open_now{false};
bool tune_mode = false;
bool quick_debug = false;
bool menu_refresh = false;
// (a value too long for its row, a GPU's name: the selected row's slides through it, a character a step, resting at
// each end; the other rows end it with "...". The drawing (fit) says how far it can slide, menu_tick moves it)
int marquee_pos = 0, marquee_max = 0;
int64_t marquee_next = 0;
constexpr int64_t kMarqueeStep = 150000000LL, kMarqueeRest = 1200000000LL;   // (ns)
// (hookshot) the mouse (menu_tick): the tab strip's part under the cursor (a tab 0 to TAB_COUNT - 1, TAB_COUNT the previous,
// TAB_COUNT + 1 the next; -1 none); the slider held with the left button (its row in the tab, -1 none)
int hover_tab = -1;
int drag_row = -1;
bool mouse_read = false;   // (the menu has read the mouse since it opened)
bool is_slider(const Row& r) { return !strcmp(r.name, "Microphone gain") || r.value == &opts.sharpness || r.value == &opts.mouse_sens || r.value == &opts.gyro_sens_x || r.value == &opts.gyro_sens_y || r.value == &opts.volume || r.value == &opts.camera_speed || r.value == &opts.fov; }
/// (a scale: the arrows and a click stop at its ends; Rumble strength would go from Off to its strongest)
bool stops_at_ends(const Row& r) { return !strcmp(r.name, "Microphone gain") || r.value == &opts.ultrawide || r.value == &opts.mouse_sens || r.value == &opts.rumble || r.value == &opts.gyro_sens_x || r.value == &opts.gyro_sens_y || r.value == &opts.volume || r.value == &opts.camera_speed || r.value == &opts.fov; }
/// (the ini's Rumble strength on the menu's steps: 0 to 150, the nearest 25)
int rumble_step(int v) { return (std::min(std::max(v, 0), 150) + 12) / 25 * 25; }
// (hookshot) A run's environment over a saved row (RX_VK_PACE=1, HOS_OUTPUT_RES=...): for that run only. save() writes the
// player's own value while the row still holds the environment's; once the player changes the row, theirs is kept. (These
// were copied into the row and the next save wrote them into hookshot_options.ini, so a test run's switch stayed for good)
struct EnvOverride {
    int* value;
    int saved, forced;
};
EnvOverride env_overrides[16];
int env_override_count = 0;
void env_override(int* value, int v) {
    for (int i = 0; i < env_override_count; i++)
        if (env_overrides[i].value == value) {   // (the same row twice: the player's value is the first one)
            *value = env_overrides[i].forced = v;
            return;
        }
    if (env_override_count < (int)(sizeof env_overrides / sizeof env_overrides[0]))
        env_overrides[env_override_count++] = {value, *value, v};
    *value = v;
}
/// The value save() writes for a row: the player's, not the environment's
int saved_value(int* value) {
    for (int i = 0; i < env_override_count; i++) {
        EnvOverride& o = env_overrides[i];
        if (o.value != value) continue;
        if (*value == o.forced) return o.saved;
        o.value = nullptr;   // (changed in the menu: the player's choice from now on)
    }
    return *value;
}
/// The menu set the row (the player or a preset): its value is saved from now on, even where it is the
/// one the environment forced
void env_release(const int* value) {
    for (int i = 0; i < env_override_count; i++)
        if (env_overrides[i].value == value) env_overrides[i].value = nullptr;
}
/// Whether the environment still holds the row (saved_value has not seen the player change it)
bool env_holds(const int* value) {
    for (int i = 0; i < env_override_count; i++)
        if (env_overrides[i].value == value) return true;
    return false;
}
Out player_custom_output{0, 0};   // (the player's own Output resolution size when HOS_OUTPUT_RES names another of its own)
std::string ini_path() { return options_path(); }   // (the user folder's when --user names one: vk_paths.h)
/// The Tracker tab's rows from the seed's file, or one row saying there is none; read again at most once a second
void tracker_load() {
    static ULONGLONG last = 0, called = 0;
    static std::vector<std::string> order;   // (the areas' rows as they were last put in order)
    static bool sort = true;
    const ULONGLONG now = GetTickCount64();
    // (the tab was not on screen for a while: its areas are put in order anew when it is again. Not while it is, where a
    //  row would move under the selection)
    if (!called || now - called > 1500) sort = true;
    called = now;
    if (last && now - last < 1000) return;
    last = now;
    std::string path = game_folder_path() + "mods\\rando-seed\\tracker.txt";   // (the game folder's, wherever the options are)
    int n = 0;
    // (a seed's files stay in the folder for the next game with the randomizer on: in the normal game and in Master Quest
    //  they are not read, and the tab says the randomizer is off)
    const bool on = tracker_on.load(std::memory_order_relaxed) != 0;
    if (FILE* f = on ? fopen(path.c_str(), "r") : nullptr) {
        char line[256];
        while (n < kTrackerRows && fgets(line, sizeof line, f)) {
            char* bar = strchr(line, '|');
            if (line[0] == '#' || !bar) continue;
            *bar = 0;
            bar[1 + strcspn(bar + 1, "\r\n")] = 0;
            snprintf(tracker_name[n], sizeof tracker_name[n], "%s", line);
            snprintf(tracker_value[n], sizeof tracker_value[n], "%s", bar + 1);
            n++;
        }
        fclose(f);
    }
    if (!n) {
        snprintf(tracker_name[0], sizeof tracker_name[0], "No seed");
        snprintf(tracker_value[0], sizeof tracker_value[0], "The randomizer is off");
        n = 1;
    }
    const bool seed = on && n > 0 && strcmp(tracker_name[0], "No seed");
    if (seed) {   // (the second and third rows are the tab's own: what it lists, and the way home. The areas follow them)
        n = std::min(n + 2, kTrackerRows);
        for (int i = n - 1; i > kTrackerHomeRow; i--)
            memcpy(tracker_name[i], tracker_name[i - 2], sizeof tracker_name[i]), memcpy(tracker_value[i], tracker_value[i - 2], sizeof tracker_value[i]);
        snprintf(tracker_name[kTrackerShowRow], sizeof tracker_name[0], "Show");
        tracker_value[kTrackerShowRow][0] = 0;
        snprintf(tracker_name[kTrackerHomeRow], sizeof tracker_name[0], "Return home");
        tracker_value[kTrackerHomeRow][0] = 0;
    }
    tracker_count = n;
    int checks = 0;
    path = path.substr(0, path.find_last_of("\\/") + 1) + "checks.txt";
    if (FILE* f = on ? fopen(path.c_str(), "r") : nullptr) {
        char line[256];
        while (checks < kTrackerChecks && fgets(line, sizeof line, f)) {
            TrackerCheck& k = tracker_checks[checks];
            k.needs[0] = '?', k.needs[1] = 0;   // (a file written before the rules were in it)
            char hash[32], gives[64];   // (the game side's: host/hos_main.c oot_tracker_load)
            const int got = line[0] == '#' ? 0 : sscanf(line, "%47[^|]|%79[^|]|%39[^|]|%3[^|]|%f %f %f|%191[A-Z0-9,/-]|%31[^|]|%63[^|]|%f %f %f", k.area, k.kind,
                                                        k.folder, k.ages, &k.pos[0], &k.pos[1], &k.pos[2], k.needs, hash, gives, &k.stand[0], &k.stand[1],
                                                        &k.stand[2]);
            if (got >= 7) {
                snprintf(k.hash, sizeof k.hash, "%s", got >= 9 ? hash : "");
                snprintf(k.gives, sizeof k.gives, "%s", got >= 10 && strcmp(gives, "-") ? gives : "");
                k.gives[strcspn(k.gives, "\r\n")] = 0;
                if (got < 13) memcpy(k.stand, k.pos, sizeof k.stand);
                checks++;
            }
        }
        fclose(f);
    }
    tracker_check_count = checks;
    {   // (the junk marks, read again when the seed is another: tracker_junk. Kept as they are in between, written at each change)
        static std::string junk_seen = "-";
        const std::string stamp = on && checks ? tracker_seed_stamp() : std::string();
        const std::string seen = stamp + "|" + std::to_string(checks);
        if (seen != junk_seen) {
            junk_seen = seen;
            tracker_junk_stamp = stamp;
            if (checks) tracker_junk_read(tracker_junk_path(), stamp, checks);
            else for (bool& junk : tracker_junk) junk = false;
        }
    }
    {   // (the checks' ways, read again when the file changes: a new seed)
        static std::string ways_seen;
        const std::string ways_path = path.substr(0, path.find_last_of("\\/") + 1) + "check_ways.txt";
        std::string stamp;
        std::error_code ec;
        const auto when = std::filesystem::last_write_time(ways_path, ec);
        if (!ec && on) stamp = std::to_string((long long)when.time_since_epoch().count()) + ":" + std::to_string((unsigned long long)std::filesystem::file_size(ways_path, ec));
        if (stamp != ways_seen) {
            ways_seen = stamp;
            tracker_ways.clear();
            if (FILE* f = stamp.empty() ? nullptr : fopen(ways_path.c_str(), "r")) {
                char way[2048];
                while (fgets(way, sizeof way, f)) {
                    char* bar = strchr(way, '|');
                    if (!bar || way[0] == '#') continue;
                    *bar = 0;
                    bar[1 + strcspn(bar + 1, "\r\n")] = 0;
                    tracker_ways[way] = bar + 1;
                }
                fclose(f);
            }
        }
    }
    if (seed && n > kTrackerFirstArea) {
        // The areas' order: the one Link is in, then the ones with a check in logic, then the ones with a check left, then
        // the rest; within each as the file has them (by name). Made when the tab comes on screen and kept while it is.
        const auto name_at = [](int i) { return std::string(tracker_name[i]); };
        if (sort) {
            // (the areas in alphabetical order, asked for 2026-11-18: before, the area Link was in came first, then those
            //  with a check in logic, then those with checks left, each group alphabetical, and the owner found the order
            //  hard to follow. A row's own words still say how many are left and in logic)
            std::vector<int> rows_now;
            for (int i = kTrackerFirstArea; i < n; i++) rows_now.push_back(i);
            std::stable_sort(rows_now.begin(), rows_now.end(), [&](int a, int b) { return _stricmp(tracker_name[a], tracker_name[b]) < 0; });
            std::vector<std::string> next;
            for (int i : rows_now) next.push_back(name_at(i));
            if (next != order) {   // (rows changed places: each row's own words again)
                order = next;
                for (int r = kTrackerFirstArea; r < kTrackerRows; r++) tracker_pick[r] = 0;
            }
            sort = false;
        }
        // (the file's rows put in that order: a name the order has not, an area new to the seed, after them)
        std::vector<std::pair<std::string, std::string>> have;
        for (int i = kTrackerFirstArea; i < n; i++) have.push_back({tracker_name[i], tracker_value[i]});
        std::vector<std::pair<std::string, std::string>> placed;
        for (const std::string& name : order)
            for (auto& h : have)
                if (h.first == name) placed.push_back(h), h.first.clear();
        for (const auto& h : have)
            if (!h.first.empty()) placed.push_back(h);
        for (int i = kTrackerFirstArea; i < n && i - kTrackerFirstArea < (int)placed.size(); i++) {
            snprintf(tracker_name[i], sizeof tracker_name[i], "%s", placed[i - kTrackerFirstArea].first.c_str());
            snprintf(tracker_value[i], sizeof tracker_value[i], "%s", placed[i - kTrackerFirstArea].second.c_str());
        }
    }
    for (int row = 0; row < kTrackerRows; row++)   // (a seed made anew: a row stepped past its area's checks is its own words again)
        if (row >= n || tracker_pick[row] > tracker_row_checks(row)) tracker_pick[row] = 0;
}
const char* ini_key(const Row& r) {
    if (r.value == &monitor_pick) return "fullscreen_monitor";
    if (r.value == &opts.output_res) return "output_res";   // (host/nn_applet.c reads it at the start)
    if (r.value == &opts.vsync) return "vsync";
    // (rows renamed since their values were first saved keep their keys: an options file from before still loads)
    if (r.value == &opts.audio_output) return "audio_output";
    if (r.value == &opts.resolution) return "resolution";
    if (r.value == &opts.fps_cap) return "frame_rate_cap";   // (host/nn_vi.c reads it at the start, then HOS_OPT_FPS_CAP)
    if (r.value == &opts.upscale) return "upscaling";
    if (r.value == &opts.dlss) return "dlss";   // (as opts.dlss and RX_VK_DLSS)
    if (r.value == &opts.handheld) return "handheld_profile";   // (the Profile row; host/nn_applet.c reads it at the start)
    if (r.value == &opts.ultrawide) return "ultrawide";   // (the Aspect ratio row; host/hos_main.c reads it at the start)
    static char k[48];
    size_t n = 0;
    for (const char* p = r.name; *p && n + 1 < sizeof k; p++) k[n++] = *p == ' ' ? '_' : (char)tolower(*p);
    k[n] = 0;
    return k;
}
// (hookshot) the controls, kept by the host (host/nn_hid.c reads them back from here): pad_<button>, key_<button>
const char* const bind_names[HOS_KEY_N] = {"a", "b", "x", "y", "ls", "rs", "l", "r", "zl", "zr", "plus", "minus",
                                           "left", "up", "right", "down", "move_up", "move_down", "move_left",
                                           "move_right", "cam_up", "cam_down", "cam_left", "cam_right",
                                           "note_l", "note_r", "note_a", "note_y", "note_x", "walk"};
bool can_bind() { return host && host->binding && host->bind && host->pad_raw; }
const char* tx_pad_layout(int v) {
    static const char* t[] = {"Nintendo (Def)", "Xbox / PC", "Swap Face", "Custom"};
    return t[std::min(std::max(v, 0), 3)];
}
void apply_pad_layout(int layout) {
    if (!can_bind() || layout < 0 || layout > 2) return;
    static const int face[4] = {HOS_SW_A, HOS_SW_B, HOS_SW_X, HOS_SW_Y};
    static const int want[3][4] = {
        {HOS_PAD_EAST, HOS_PAD_SOUTH, HOS_PAD_NORTH, HOS_PAD_WEST},   // Nintendo (Default: Bottom=B, Right=A, Top=X, Left=Y)
        {HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_WEST, HOS_PAD_NORTH},   // Xbox / PC Standard (Bottom=A, Right=B, Left=X, Top=Y)
        {HOS_PAD_SOUTH, HOS_PAD_EAST, HOS_PAD_NORTH, HOS_PAD_WEST},   // Swap Face Buttons (Bottom=A, Right=B, Top=X, Left=Y)
    };
    // (again while a face button is not the preset's: the host leaves an empty Input 1 as it is when the input asked for is
    // another button's only one (hos_bind), and that button may take its own new input later in the same pass)
    for (int pass = 0; pass < 4; pass++) {
        bool done = true;
        for (int i = 0; i < 4; i++)
            if (host->binding(HOS_BIND_PAD, face[i], 0) != want[layout][i]) {
                host->bind(HOS_BIND_PAD, face[i], 0, want[layout][i]);
                done = false;
            }
        if (done) break;
    }
}
int detect_pad_layout() {
    if (!can_bind()) return opts.pad_layout;
    const int a = host->binding(HOS_BIND_PAD, HOS_SW_A, 0);
    const int b = host->binding(HOS_BIND_PAD, HOS_SW_B, 0);
    const int x = host->binding(HOS_BIND_PAD, HOS_SW_X, 0);
    const int y = host->binding(HOS_BIND_PAD, HOS_SW_Y, 0);
    if (a == HOS_PAD_EAST && b == HOS_PAD_SOUTH && x == HOS_PAD_NORTH && y == HOS_PAD_WEST) return 0;
    if (a == HOS_PAD_SOUTH && b == HOS_PAD_EAST && x == HOS_PAD_WEST && y == HOS_PAD_NORTH) return 1;
    if (a == HOS_PAD_SOUTH && b == HOS_PAD_EAST && x == HOS_PAD_NORTH && y == HOS_PAD_WEST) return 2;
    return 3;
}
// (hookshot) the row's choice to the host: off, the default, or a microphone by its name (and its place in the host's list,
// -1 while it is unplugged: of two with one name, the one chosen). Unplugged, the name is the kept one, cut: the host takes
// a name that starts with it
void refresh_monitors() {
    const int old_count = (int)fullscreen_monitors.size(), old_pick = monitor_pick;
    const bool old_missing = monitor_missing;
    const std::string old_name = monitor_saved_name;
    fullscreen_monitors.clear();
    if (can_monitors()) {
        const int count = std::min(64, std::max(0, host->monitor_count()));
        for (int i = 0; i < count; i++) {
            MkwVkMonitor monitor{};
            if (!host->monitor_info(i, &monitor)) continue;
            monitor.id[sizeof monitor.id - 1] = monitor.name[sizeof monitor.name - 1] = 0;
            const std::string id = monitor_choice::id_key(monitor.id);
            if (!id.empty()) fullscreen_monitors.push_back({id, output_name_key(monitor.name), monitor.width, monitor.height, monitor.flags});
        }
    }
    monitor_pick = monitor_choice::pick(fullscreen_monitors, monitor_want);
    monitor_missing = monitor_pick > (int)fullscreen_monitors.size();
    if (monitor_pick > 0 && !monitor_missing) monitor_saved_name = fullscreen_monitors[monitor_pick - 1].name;
    for (Row& r : rows) if (r.value == &monitor_pick) r.hi = (int)fullscreen_monitors.size() + (monitor_missing ? 1 : 0);
    if (old_count != (int)fullscreen_monitors.size() || old_pick != monitor_pick ||
        old_missing != monitor_missing || old_name != monitor_saved_name) menu_refresh = true;
}
void monitor_chosen() {
    if (!can_monitors()) return;
    if (monitor_pick <= 0) monitor_want.clear(), monitor_saved_name.clear();
    else if ((size_t)(monitor_pick - 1) < fullscreen_monitors.size()) {
        monitor_want = fullscreen_monitors[monitor_pick - 1].id;
        monitor_saved_name = fullscreen_monitors[monitor_pick - 1].name;
    }
    host->monitor_select(monitor_want.c_str());
    refresh_monitors();
}
void refresh_outputs() {
    output_devices.clear();
    if (can_outputs()) {
        const int count = std::max(0, host->audio_output_count());
        for (int i = 0; i < count && i < 0x7ffffffd; i++) {
            char id[HOS_OUTPUT_ID_CAP], name[HOS_OUTPUT_NAME_CAP];
            if (host->audio_output_info(i, id, sizeof id, name, sizeof name)) output_devices.push_back({id, name});
        }
    }
    output_pick = 0;
    for (size_t i = 0; i < output_devices.size(); i++)
        if (output_devices[i].id == output_want) output_pick = (int)i + 1, output_saved_name = output_devices[i].name;
    output_missing = !output_want.empty() && !output_pick;
    if (output_missing) output_pick = (int)output_devices.size() + 1;
    for (Row& r : rows) if (r.value == &output_pick) r.hi = (int)output_devices.size() + (output_missing ? 1 : 0);
}
void output_chosen() {
    if (output_forced() || !can_outputs()) return;
    if (output_pick <= 0) output_want.clear(), output_saved_name.clear();
    else if ((size_t)(output_pick - 1) < output_devices.size()) {
        output_want = output_devices[output_pick - 1].id;
        output_saved_name = output_devices[output_pick - 1].name;
    }
    host->audio_output_select(output_want.c_str());
    refresh_outputs();
}
void mic_tell_host() {
    if (!can_mic()) return;
    if (opts.mic <= 1) host->mic_select(opts.mic <= 0 ? 0 : 1, "", -1);
    else if (mic_missing && opts.mic == 2 + mic_listed) host->mic_select(2, mic_want.c_str(), -1);   // (the kept name, cut)
    else host->mic_select(2, host->mic_name(opts.mic - 2), opts.mic - 2);   // (its whole name: the ini's cut is only the ini's)
}
void mic_row_ends() {
    for (Row& r : rows)
        if (r.value == &opts.mic) r.hi = 1 + mic_listed + (mic_missing ? 1 : 0);
}
// (hookshot) the microphones listed again (one plugged in since shows up), the row on mic_want's: the one at the row's place
// when it still has that name (two microphones of one name: the second stays chosen), else the first of that name, else
// its "(not connected)" entry while it is unplugged
void refresh_mics() {
    if (!can_mic()) {
        if (opts.mic >= 2) opts.mic = 1;
        return;
    }
    mic_listed = std::min(host->mic_count(), kMaxMics);
    int at = -1;
    if (!mic_want.empty()) {
        if (opts.mic >= 2 && opts.mic - 2 < mic_listed && mic_key(host->mic_name(opts.mic - 2)) == mic_want) at = opts.mic - 2;
        for (int i = 0; i < mic_listed && at < 0; i++)
            if (mic_key(host->mic_name(i)) == mic_want) at = i;
        opts.mic = at >= 0 ? at + 2 : 2 + mic_listed;
    } else if (opts.mic >= 2) {
        opts.mic = 1;
    }
    mic_missing = !mic_want.empty() && at < 0;
    mic_row_ends();
    mic_tell_host();
}
// (the row changed by the player: the choice is now this one, by its name; the "(not connected)" entry is kept only while
// it is the one chosen)
void mic_chosen() {
    if (opts.mic >= 2 && !(mic_missing && opts.mic == 2 + mic_listed)) {
        mic_want = mic_key(host->mic_name(opts.mic - 2)), mic_missing = false;
    } else if (opts.mic < 2) {
        mic_want.clear(), mic_missing = false;
    }
    mic_row_ends();
    mic_tell_host();
}
void save() {
    // (one writer at a time: the present's thread, the game's (menu_option_set) and the control bridge's, menu_setting_set)
    static std::mutex save_mu;
    std::lock_guard lk(save_mu);
    // (hookshot) the lines that are not the menu's are kept: the controls, pad_ and key_ (host/nn_hid.c), and their toggle_ flags
    // (and every other line the menu does not write, such as discord_app_id=: they were dropped at the next save)
    std::string kept, others;
    if (FILE* f = fopen(ini_path().c_str(), "r")) {
        char line[4096];
        while (fgets(line, sizeof line, f)) {
            if (!strchr(line, '\n') && !feof(f)) {
                int c; while ((c = fgetc(f)) != '\n' && c != EOF) {}
                continue;
            }
            if (!strncmp(line, "pad_", 4) || !strncmp(line, "key_", 4) || !strncmp(line, "toggle_", 7)) {
                kept += line;
                continue;
            }
            const char* eq = strchr(line, '=');
            if (!eq || eq == line) continue;
            const std::string key(line, (size_t)(eq - line));
            // (memory_budget and auto_for too: save() writes them, and the file's old line, kept after it, won at the next start;
            // auto_output, the Output resolution Auto once set, is no longer written: its old line is dropped)
            bool mine = key == "audio_output_device_id" || key == "audio_output_device_name" || key == "output_device" ||
                        key == "microphone_device" || key == "options_version" || key == "memory_budget" || key == "auto_for" ||
                        key == "auto_tuned" || key == "auto_output" || key == "auto_steps";
            mine |= key == "fullscreen_monitor_id";
            mine |= key == "fullscreen_monitor_name";
            // (and the Mesh shaders row's line, no longer read (gpu/vk/mesh_mode.h): dropped, not kept for nothing)
            mine |= key == "mesh_shaders";
            // (and the VRAM budget row's, removed: one rule by the card, texture_budget.h and mirror_budget.h)
            mine |= key == "vram_budget";
            mine |= key == "gpu_device_id";   // (the GPU device row's card: written below)
            for (const Row& r : rows)
                if (!mine && r.value && key == ini_key(r)) mine = true;
            if (!mine) others += line, others += others.back() == '\n' ? "" : "\n";
        }
        fclose(f);
    }
    const auto write_lines = [&](FILE* f) {
        for (const Row& r : rows) {
            if (r.value == &opts.output_res) {   // (the size itself: host/nn_applet.c reads it)
                const int v = saved_value(r.value);
                const Out o = v == custom_index() && player_custom_output.w && env_holds(r.value) ? player_custom_output : output_at(v);
                fprintf(f, "%s=%ux%u\n", ini_key(r), o.w, o.h);
            } else if (r.value == &opts.ultrawide) {   // (the Aspect ratio: 1 the monitor's own shape, else 0; output_res holds the rest)
                // (a run whose Output resolution HOS_OUTPUT_RES holds took the row from the environment's size: the player's own
                // ultrawide= is kept, unless the row was changed in the menu)
                const int v = saved_value(r.value);
                fprintf(f, "%s=%d\n", ini_key(r), env_holds(&opts.output_res) && v == aspect_started ? ultrawide_read : aspect_follows_host(v) ? 1 : 0);
            } else if (r.value && r.value != &opts.game_lang && r.value != &output_pick && r.value != &monitor_pick) { // Device choices are saved by ID below.
                fprintf(f, "%s=%d\n", ini_key(r), saved_value(r.value));
            }
        }
        if (!mic_want.empty()) fprintf(f, "microphone_device=%s\n", mic_want.c_str());   // (hookshot: also while it is unplugged)
        if (!output_want.empty()) {
            fprintf(f, "audio_output_device_id=%s\n", output_want.c_str());
            fprintf(f, "audio_output_device_name=%s\n", output_saved_name.c_str());
        }
        if (!monitor_want.empty()) {
            fprintf(f, "fullscreen_monitor_id=%s\n", monitor_want.c_str());
            fprintf(f, "fullscreen_monitor_name=%s\n", monitor_saved_name.c_str());
        }
        // (not a row: the preset Custom came from, whose mip trimming it keeps: opts.budget)
        fprintf(f, "memory_budget=%d\n", opts.budget);
        // (the GPU device row's card itself, not only its place in the list: gpu_choice.h. A saved card not here this run, the
        // row still at the Auto it started on, stays saved for when it is back)
        const std::string card = opts.gpu_device > 0 ? gpu_choice::card_id(gpu_device_cards, opts.gpu_device - 1)
                                 : opts.gpu_device == 0 && gpu_card_missing ? gpu_saved_card : std::string();
        if (!card.empty()) fprintf(f, "gpu_device_id=%s\n", card.c_str());
        if (auto_for) fprintf(f, "auto_for=%016llx\n", (unsigned long long)auto_for);   // (the hardware Auto (this PC) chose for)
        if (auto_tuned) fprintf(f, "auto_tuned=%016llx\n", (unsigned long long)auto_tuned);   // (and measured in play for)
        // (the tuning's steps so far and whether one went down: the no-seesaw rule and the two steps hold across restarts)
        if (auto_for && auto_tuning.steps) fprintf(f, "auto_steps=%d,%d\n", auto_tuning.steps, auto_tuning.went_down ? 1 : 0);
        // (2: game_speed below 2 was only ever the old default, see menu_init; 3: the mouse's buttons are bindings, see
        // host/nn_hid.c binds_load; 4: Descriptor reuse on by default, see menu_init and vk_draw.cpp desc_slotgen_on; 5: the
        // Menu shortcut "Insert, F1 or Esc" by default, see menu_init; 6: the Aspect ratio's 16:9 from before moves on a
        // screen narrower than 16:9, see menu_init and host/hos_wide_size.h)
        fprintf(f, "options_version=6\n");
        fputs(others.c_str(), f);
        if (!can_bind()) fputs(kept.c_str(), f);
        for (int i = 0; i < HOS_KEY_N && can_bind(); i++) {   // (the stick's and camera's rows, HOS_KEY_MOVE_*/CAM_*, have no pad_ line; the ocarina note rows do)
            if (i < HOS_SW_N || (i >= HOS_KEY_OC_NOTE_L && i <= HOS_KEY_OC_NOTE_X)) {
                const int alternate = host->binding(HOS_BIND_PAD, i, 1);
                fprintf(f, "pad_%s=%d", bind_names[i], host->binding(HOS_BIND_PAD, i, 0));
                if (alternate >= 0) fprintf(f, ",%d", alternate);
                fputc('\n', f);
            }
            if (i < HOS_SW_N) fprintf(f, "toggle_%s=%d\n", bind_names[i], (opts.hold_toggle >> i) & 1);
            fprintf(f, "key_%s=%d,%d\n", bind_names[i], host->binding(HOS_BIND_KEY, i, 0), host->binding(HOS_BIND_KEY, i, 1));
        }
    };
    // (written beside its target, a link followed so that a synced file stays linked, as <name>.new, and moved over it once
    // whole: written in place, a full disk or a close mid-write left it cut short, and the next start took the defaults past
    // the cut, or, cut to nothing, chose Auto (this PC) over the player's preset. Where nothing can be made beside it or moved
    // over it (a folder that is not writable, the file held open by another program), in place as before. A read-only
    // file is kept. Each failure is logged once a run, with the file's whole path (the launcher's user folder's, --user, or the
    // game folder's: options_path): a save comes with every arrow press. No file this run (options_path empty, logged at the
    // start by host/options_path.c): nothing saved, and nothing made in the folder the game runs in)
    std::string path = ini_path();
    if (path.empty()) return;
    static bool told[5];
    const auto say_once = [](int k, const std::string& what) {
        if (!told[k]) told[k] = true, logf("menu: %s", what.c_str());
    };
#ifdef _WIN32
    const auto why = [] { return "Windows error " + std::to_string(GetLastError()); };
#else
    const auto why = [] { return std::string(strerror(errno)); };
#endif
    bool in_place = false;
#ifdef _WIN32
    const DWORD attrs = GetFileAttributesA(path.c_str());
    if (attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_READONLY)) {
        say_once(0, path + " is read-only: the settings are not saved");
        return;
    }
    in_place = attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_REPARSE_POINT);   // (a link: written through it)
#else
    if (char* real = realpath(path.c_str(), nullptr)) path = real, free(real);
    struct stat st{};
    const bool exists = stat(path.c_str(), &st) == 0;
    if (exists && access(path.c_str(), W_OK) != 0) {
        const std::string e = why();   // (taken before the text is put together: that may touch errno)
        say_once(0, path + " cannot be written (" + e + "): the settings are not saved");
        return;
    }
#endif
    const std::string part = path + ".new";
    if (!in_place) {
        FILE* f = fopen(part.c_str(), "w");
        if (!f) {
            const std::string e = why();
            say_once(1, part + " cannot be made beside it (" + e + "): " + path + " is written in place");
            in_place = true;
        } else {
#ifndef _WIN32
            if (exists) (void)fchmod(fileno(f), st.st_mode & 07777);   // (its permissions, not the umask's)
#endif
            write_lines(f);
            const bool whole = fflush(f) == 0 && !ferror(f);
            std::string failed = whole ? std::string() : why();
            if (fclose(f) != 0 && failed.empty()) failed = why();
            if (!failed.empty()) {   // (not whole: the old file stays as it was)
                remove(part.c_str());
                say_once(2, part + " could not be written whole (" + failed + "): " + path + " is kept as it was");
                return;
            }
#ifdef _WIN32
            if (MoveFileExA(part.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING)) return;
#else
            if (rename(part.c_str(), path.c_str()) == 0) return;
#endif
            const std::string moved = why();
            remove(part.c_str());
            say_once(3, part + " could not be moved over it (" + moved + "): " + path + " is written in place");
            in_place = true;
        }
    }
    FILE* f = fopen(path.c_str(), "w");
    if (!f) {
        const std::string e = why();
        say_once(4, path + " could not be opened to write (" + e + "): the settings are not saved");
        return;
    }
    write_lines(f);
    const bool whole = fflush(f) == 0 && !ferror(f);
    std::string failed = whole ? std::string() : why();
    if (fclose(f) != 0 && failed.empty()) failed = why();
    if (!failed.empty()) say_once(4, path + " could not be written in place (" + failed + ")");
}

/// (hookshot) The Button prompts row: a new face shows at once where the game has every part of the prompts from
/// host/prompts.c, nothing to restart for then; else, as the other restart rows, at the next start
void prompts_at_once(const Row& r) {
    if (r.value == &opts.prompts && host && host->prompts_live &&
        (host->prompts_live() & HOS_PROMPTS_LIVE_ALL) == HOS_PROMPTS_LIVE_ALL)
        restart_state.restart_value(restart_slot_of(r), *r.value);
}


// ---- (hookshot) Save my pipeline list (the Debug tab, under Developer): hookshot_pipeline_states.bin and the "Submit your pipelines" issue's
// template, filled in from this run, zipped into the Downloads folder (pipeline_share.h; the builders do the same with
// nx2/pipeline_share.py). Then the report on the clipboard, the folder shown and the issue opened in the browser, where the platform
// has them; never with HOS_HEADLESS (no screen to show them on). Nothing is uploaded: the player attaches the zip ----
namespace ps = pipeline_share;
std::string share_said;    // (the help box's line after a save: where the zip went and what to do, or why there is none)
std::string share_value;   // (the row's value after a save: Saved, or Not saved)
constexpr const char* kShareSaidLongest = "Saved hookshot-pipelines-2026-12-31.zip (123456 pipelines) in Downloads. The report "
    "is in the zip. Open github.com/Shakoquo/Mako/issues and attach the zip to a comment, then paste the report and say "
    "where you played.";   // (measure_help: the help box's room)
std::string share_saved;   // (the first sentence: the zip's name, its pipelines and its folder)
std::atomic<bool> share_busy{false};   // (the worker is copying and opening: presses wait for it)
std::atomic<int> share_result{-1};     // (the worker's answer: 1 copied, 2 the issue opened; -1 none waiting)
/// (menu_tick, each frame) the worker's answer into the help box's line
void share_finish() {
    const int r = share_result.exchange(-1);
    if (r < 0) return;
    share_said = share_saved + ((r & 1) ? "The report is copied. " : "The report is in the zip. ") +
                 ((r & 2) ? "Issue 14 is open in your browser: attach" : "Open github.com/Shakoquo/Mako/issues and attach") +
                 " the zip to a comment, then paste the report and say where you played.";
    share_busy.store(false);
    menu_refresh = true;
}
bool is_share_row(const Row& r) { return !r.value && r.tab == TAB_DEBUG && !strcmp(r.name, "Save my pipeline list"); }
// (hookshot) Set up for a weak laptop (the Debug tab, integrated graphics: row_shown): Minimum's rows and mip trimming, then
// lighter still. An i3-1115G4's UHD Graphics (2 cores, 4 threads, 16 GB shared) ran Kokiri Forest and the Deku Tree at 3-6 fps
// with 120-200 ms of GPU time a frame on the game's own dynamic resolution, docked at 2048 x 1152
bool laptop_applied = false;
void weak_laptop_apply() {
    apply_preset(1);   // (Minimum: its scaling rows, the handheld profile, its mip trimming on a small or shared GPU)
    env_release(&opts.dlss);
    opts.dlss = 0;   // (the game's own upscaler: no DLSS or FSR on these GPUs, and the lightest)
    opts.resolution = ur::snap_render(upscaler(), 6);   // (33%: auto_settings.h RES_ULTRA_PERFORMANCE)
    opts.upscale = 0, opts.sharpness = 0;   // (the plain window scale: as Auto's lightest tier, RX_VK_LOW_SPEC)
    for (int* v : {&opts.framegen, &opts.intel_compiles, &opts.intel_quick}) env_release(v);
    opts.framegen = 0;
    opts.intel_compiles = 2, opts.intel_quick = 1;   // (2: one at a time, whatever the row's Auto is on this GPU)
    opts.preset = 0;   // (Custom, Minimum's mip trimming kept: opts.budget)
    samplers_changed();   // (the upscalers' texture LOD bias follows the 3D's share)
    laptop_applied = true;
    menu_refresh = true;
    {   // (the handheld profile and Intel's shader compiles take a restart: asked at the next close, as for a row set by hand)
        int now[mr::kMax];
        restart_values(now);
        restart_state.note(now);
    }
    save();
    logf("menu: Set up for a weak laptop: Render resolution %d%%, the game's own upscaler, plain scale, handheld profile (after a "
         "restart), Minimum's mip trimming", ur::percent(opts.resolution));
}
std::string game_folder() {
    char exe[MAX_PATH];
    const DWORD n = game_module_path(exe, MAX_PATH);
    std::string dir(exe, n);
    return dir.substr(0, dir.find_last_of("\\/") + 1);
}
bool is_dir(const std::string& p) {
    const DWORD a = GetFileAttributesA(p.c_str());
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}
/// The mods the game loaded, by host/mods.c's rule: under the game folder's mods (or HOS_MODS), a folder holding romfs or exefs,
/// up to four folders deep; names starting with '-' or '_' are off
void share_find_mods(const std::string& dir, const std::string& name, int depth, std::vector<std::string>& out) {
    if (depth > 0 && (is_dir(dir + "/romfs") || is_dir(dir + "/exefs"))) {
        out.push_back(name);
        return;
    }
    if (depth >= 4) return;
    WIN32_FIND_DATAA fd;
    HANDLE f = FindFirstFileA((dir + "/*").c_str(), &fd);
    if (f == INVALID_HANDLE_VALUE) return;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || fd.cFileName[0] == '.' || fd.cFileName[0] == '-' ||
            fd.cFileName[0] == '_')
            continue;
        share_find_mods(dir + "/" + fd.cFileName, name.empty() ? fd.cFileName : name + "/" + fd.cFileName, depth + 1, out);
    } while (FindNextFileA(f, &fd));
    FindClose(f);
}
std::string share_os() {
#ifdef _WIN32
    using RtlGetVersionFn = LONG(WINAPI*)(OSVERSIONINFOEXW*);
    OSVERSIONINFOEXW v{};
    v.dwOSVersionInfoSize = sizeof v;
    const auto get = (RtlGetVersionFn)(void*)GetProcAddress(GetModuleHandleA("ntdll.dll"), "RtlGetVersion");
    if (!get || get(&v) != 0) return "Windows";
    // (Windows 11 is still 10.0, from build 22000; a server says so instead: wProductType VER_NT_WORKSTATION is 1)
    const char* name = v.wProductType != 1 ? "Windows Server" : v.dwMajorVersion == 10 && v.dwBuildNumber >= 22000 ? "Windows 11"
                       : v.dwMajorVersion == 10 ? "Windows 10" : "Windows";
    char b[80];
    snprintf(b, sizeof b, "%s (%lu.%lu.%lu)", name, v.dwMajorVersion, v.dwMinorVersion, v.dwBuildNumber);
    return b;
#else
    std::string pretty;
    for (const char* path : {"/etc/os-release", "/usr/lib/os-release"}) {
        FILE* f = fopen(path, "r");
        if (!f) continue;
        char line[256];
        while (fgets(line, sizeof line, f))
            if (!strncmp(line, "PRETTY_NAME=", 12)) {
                pretty = line + 12;
                while (!pretty.empty() && (pretty.back() == '\n' || pretty.back() == '"' || pretty.back() == '\r')) pretty.pop_back();
                if (!pretty.empty() && pretty[0] == '"') pretty.erase(0, 1);
            }
        fclose(f);
        break;
    }
    utsname u{};
    uname(&u);
    return std::string(u.sysname) + " (" + (pretty.empty() ? "" : pretty + ", ") + "kernel " + u.release + ")";
#endif
}
#ifdef _WIN32
/// A function of shell32 or ole32, loaded at its first use: hookshot_vk.dll imports only kernel32, user32, gdi32, advapi32 and the
/// UCRT (the DLSS workflow's import check), and these two are needed only here
FARPROC share_proc(const wchar_t* dll, const char* name) {
    HMODULE m = LoadLibraryExW(dll, nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    return m ? GetProcAddress(m, name) : nullptr;
}
#endif
/// The Downloads folder (where a browser's file picker opens), else the home folder, else the game folder. *words: how the menu
/// names it: the folder's own name for Downloads, never the home folder's (that is the user's name)
std::string share_downloads(std::string* words) {
    *words = "";
#ifdef _WIN32
    using KnownFolderFn = HRESULT(WINAPI*)(const GUID&, DWORD, HANDLE, wchar_t**);
    using FreeFn = void(WINAPI*)(void*);
    static const auto known = (KnownFolderFn)(void*)share_proc(L"shell32.dll", "SHGetKnownFolderPath");
    static const auto free_mem = (FreeFn)(void*)share_proc(L"ole32.dll", "CoTaskMemFree");
    wchar_t* w = nullptr;
    std::string out;
    static const GUID downloads = {0x374DE290, 0x123F, 0x4565, {0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B}};   // (FOLDERID_Downloads)
    if (known && SUCCEEDED(known(downloads, 0, nullptr, &w)) && w) {
        char b[MAX_PATH * 4];
        if (WideCharToMultiByte(CP_UTF8, 0, w, -1, b, sizeof b, nullptr, nullptr) > 0) out = b;
    }
    if (w && free_mem) free_mem(w);
    if (!out.empty() && is_dir(out)) return out;
    if (const char* home = getenv("USERPROFILE"); home && is_dir(home)) return *words = "your home folder", home;
#else
    const char* home = getenv("HOME");
    if (home && *home) {
        const char* conf = getenv("XDG_CONFIG_HOME");
        const std::string path = (conf && *conf ? std::string(conf) : std::string(home) + "/.config") + "/user-dirs.dirs";
        std::string text;
        if (FILE* f = fopen(path.c_str(), "r")) {
            char b[4096];
            text.assign(b, fread(b, 1, sizeof b, f));
            fclose(f);
        }
        const std::string d = ps::xdg_download_dir(text, home);
        if (!d.empty() && is_dir(d)) return d;
        if (is_dir(std::string(home) + "/Downloads")) return std::string(home) + "/Downloads";
        if (is_dir(home)) return *words = "your home folder", home;
    }
#endif
    *words = "the game folder";
    return game_folder();
}
#ifndef _WIN32
/// A program of the desktop's (xdg-open, wl-copy, ...), not waited for: false when it cannot start. input: its standard input
bool share_spawn(std::vector<std::string> argv, const std::string* input = nullptr) {
    int fds[2] = {-1, -1};
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    if (input) {
        if (pipe2(fds, O_CLOEXEC)) return posix_spawn_file_actions_destroy(&fa), false;   // (no other child holds it open)
        posix_spawn_file_actions_adddup2(&fa, fds[0], 0);
        posix_spawn_file_actions_addclose(&fa, fds[1]);
    } else {
        posix_spawn_file_actions_addopen(&fa, 0, "/dev/null", O_RDONLY, 0);
    }
    posix_spawn_file_actions_addopen(&fa, 1, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&fa, 2, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addclosefrom_np(&fa, 3);   // (a browser or file manager keeps none of the game's files, nor a clipboard pipe)
    std::vector<char*> args;
    for (std::string& a : argv) args.push_back(a.data());
    args.push_back(nullptr);
    pid_t pid = 0;
    const int err = posix_spawnp(&pid, args[0], &fa, nullptr, args.data(), environ);
    posix_spawn_file_actions_destroy(&fa);
    if (input) close(fds[0]);
    if (err) {
        if (input) close(fds[1]);
        return false;
    }
    if (!input) {   // (xdg-open: reaped whenever it ends)
        std::thread([pid] {
            int status = 0;
            waitpid(pid, &status, 0);
        }).detach();
        return true;
    }
    // (the clipboard's programs: given the text, and their exit waited for (they fork to keep the clipboard, the parent ends at once),
    // so one that fails (wl-copy with a stale WAYLAND_DISPLAY) counts as failed and the next is tried. On the share worker. SIGPIPE
    // is blocked on this thread while it writes: a program that exits before reading would otherwise end the game; the write
    // then fails with EPIPE, and the signal it left pending is taken before the mask is put back)
    sigset_t pipe_set, old;
    sigemptyset(&pipe_set);
    sigaddset(&pipe_set, SIGPIPE);
    pthread_sigmask(SIG_BLOCK, &pipe_set, &old);
    bool wrote = true;
    for (size_t at = 0; at < input->size();) {
        const ssize_t n = write(fds[1], input->data() + at, input->size() - at);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) {
            wrote = false;
            break;
        }
        at += (size_t)n;
    }
    close(fds[1]);
    const timespec now{0, 0};
    while (sigtimedwait(&pipe_set, nullptr, &now) == SIGPIPE) {}
    pthread_sigmask(SIG_SETMASK, &old, nullptr);
    int status = 0;
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
    return wrote && WIFEXITED(status) && WEXITSTATUS(status) == 0;
}
#endif
bool share_clipboard(const std::string& text) {
#ifdef _WIN32
    const int n = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
    bool open = false;   // (another program can hold the clipboard a moment: a few tries)
    for (int i = 0; n > 0 && !open && i < 5; i++) open = OpenClipboard(app_window()) || (Sleep(20), false);
    if (!open) return false;
    EmptyClipboard();
    bool ok = false;
    if (HGLOBAL g = GlobalAlloc(GMEM_MOVEABLE, (size_t)n * sizeof(wchar_t))) {
        if (auto* w = (wchar_t*)GlobalLock(g)) {
            MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, w, n);
            GlobalUnlock(g);
            ok = SetClipboardData(CF_UNICODETEXT, g) != nullptr;
        }
        if (!ok) GlobalFree(g);
    }
    CloseClipboard();
    return ok;
#else
    const char* wl = getenv("WAYLAND_DISPLAY");
    const char* x = getenv("DISPLAY");
    if (wl && *wl && share_spawn({"wl-copy"}, &text)) return true;
    return x && *x && (share_spawn({"xclip", "-selection", "clipboard"}, &text) || share_spawn({"xsel", "-ib"}, &text));
#endif
}
bool share_open(const std::string& what, bool select = false) {
#ifdef _WIN32
    std::wstring w(MultiByteToWideChar(CP_UTF8, 0, what.c_str(), -1, nullptr, 0), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, what.c_str(), -1, w.data(), (int)w.size());
    w.resize(wcslen(w.c_str()));
    using ShellExecuteFn = HINSTANCE(WINAPI*)(HWND, const wchar_t*, const wchar_t*, const wchar_t*, const wchar_t*, INT);
    static const auto shell_execute = (ShellExecuteFn)(void*)share_proc(L"shell32.dll", "ShellExecuteW");
    if (!shell_execute) return false;
    if (select)   // (the folder, the zip chosen in it)
    {
        wchar_t windir[MAX_PATH];   // (%WINDIR%\explorer.exe, not whichever explorer.exe the search path finds first)
        const DWORD n = GetEnvironmentVariableW(L"WINDIR", windir, MAX_PATH);
        const std::wstring explorer = n && n < MAX_PATH ? std::wstring(windir) + L"\\explorer.exe" : L"explorer.exe";
        return (INT_PTR)shell_execute(nullptr, L"open", explorer.c_str(), (L"/select,\"" + w + L"\"").c_str(), nullptr, SW_SHOWNORMAL) > 32;
    }
    return (INT_PTR)shell_execute(nullptr, L"open", w.c_str(), nullptr, nullptr, SW_SHOWNORMAL) > 32;
#else
    (void)select;
    return share_spawn({"xdg-open", what});
#endif
}
/// The zip at path, through <path>.new made fresh (never one that was there, nor a link's target) and moved over what was there
bool share_write(const std::string& path, const std::string& data) {
    const std::string part = path + ".new";
#ifdef _WIN32
    auto wide = [](const std::string& u) {
        std::wstring w(MultiByteToWideChar(CP_UTF8, 0, u.c_str(), -1, nullptr, 0), L'\0');
        MultiByteToWideChar(CP_UTF8, 0, u.c_str(), -1, w.data(), (int)w.size());
        w.resize(wcslen(w.c_str()));
        return w;
    };
    const std::wstring wpart = wide(part), wpath = wide(path);
    DeleteFileW(wpart.c_str());   // (a run that stopped halfway)
    HANDLE h = CreateFileW(wpart.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD done = 0;
    bool ok = WriteFile(h, data.data(), (DWORD)data.size(), &done, nullptr) && done == data.size();
    ok = CloseHandle(h) && ok;
    ok = ok && MoveFileExW(wpart.c_str(), wpath.c_str(), MOVEFILE_REPLACE_EXISTING);
#else
    unlink(part.c_str());   // (a run that stopped halfway; a link is removed, not followed)
    const int fd = open(part.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0644);
    if (fd < 0) return false;
    bool ok = true;
    for (size_t at = 0; ok && at < data.size();) {
        const ssize_t n = write(fd, data.data() + at, data.size() - at);
        ok = n > 0, at += ok ? (size_t)n : 0;
    }
    ok = close(fd) == 0 && ok;
    ok = ok && rename(part.c_str(), path.c_str()) == 0;
#endif
    if (!ok) {
#ifdef _WIN32
        DeleteFileW(wpart.c_str());
#else
        unlink(part.c_str());
#endif
    }
    return ok;
}
/// The template's values from this run: the version, the OS, the GPU and its driver, the output, the upscaler and the 3D's size,
/// frame generation and HDR as the menu has them now, and the mods
std::vector<std::string> share_values(long long pipelines, bool v2, long long computes) {
    std::vector<std::string> v(ps::kFieldCount);
    v[0] = HOOKSHOT_VERSION;
    v[1] = share_os() + "; " + dev.props.deviceName + ", driver " + driver_text();
    const Out o = shown_output();
    v[2] = ps::output_text(o.w, o.h, opts.handheld != 0, output_choice(opts.output_res) == 0, aspect_follows_host(opts.ultrawide));
    v[3] = std::string(tx_upscaler(opts.dlss)) + ", " + tx_resolution(opts.resolution);
    v[4] = std::string(tx_framegen(std::clamp(opts.framegen, 0, 8))) + " / " + tx_hdr(opts.hdr);
    std::vector<std::string> mods;
    const char* env = getenv("HOS_MODS");
    share_find_mods(env && *env ? std::string(env) : game_folder() + "mods", "", 0, mods);
    std::sort(mods.begin(), mods.end(), [](const std::string& a, const std::string& b) {   // (case-insensitive, as the builders sort)
        return std::lexicographical_compare(a.begin(), a.end(), b.begin(), b.end(),
                                            [](char x, char y) { return tolower((unsigned char)x) < tolower((unsigned char)y); });
    });
    v[5] = ps::mods_text(mods);
    v[7] = ps::pipelines_text(pipelines, v2, computes);
    return v;
}
/// Save my pipeline list: the zip, then the clipboard, the folder and the issue (share_said says what happened)
void share_pipeline_list() {
    if (share_busy.load()) return;   // (the last press is still opening things)
    bool present = false;
    const std::string list = state_list_snapshot(&present);
    std::string why;
    const long long n = ps::check_list(list, present, &why);
    if (n < 0) {
        share_said = why, share_value = "Not saved";
        logf("menu: Save my pipeline list: %s", why.c_str());
        return;
    }
    const std::string lines = ps::template_lines(share_values(n, !list.compare(0, 8, "HKSTATE2"), ps::compute_count(list)));
    const time_t now = time(nullptr);
    tm t{};
#ifdef _WIN32
    localtime_s(&t, &now);
#else
    localtime_r(&now, &t);
#endif
    const std::string zip = ps::share_zip(list, lines, (uint16_t)((t.tm_year - 80) << 9 | (t.tm_mon + 1) << 5 | t.tm_mday),
                                          (uint16_t)(t.tm_hour << 11 | t.tm_min << 5 | t.tm_sec / 2));
    std::string where;
    const std::string dir = share_downloads(&where), name = ps::zip_name(t.tm_year + 1900, t.tm_mon + 1, t.tm_mday);
#ifdef _WIN32
    const char* sep = "\\";   // (Explorer's /select takes back slashes only)
#else
    const char* sep = "/";
#endif
    const std::string path = dir + (dir.back() == '/' || dir.back() == '\\' ? "" : sep) + name;
    const bool written = share_write(path, zip);
    std::string folder = dir;   // (its name alone: no user name on screen)
    while (folder.size() > 1 && (folder.back() == '/' || folder.back() == '\\')) folder.pop_back();
    folder = folder.substr(folder.find_last_of("\\/") + 1);
    if (!where.empty()) folder = where;
    if (!written) {
        share_said = "The zip could not be written in " + folder + ".", share_value = "Not saved";
        logf("menu: Save my pipeline list: %s could not be written", name.c_str());
        return;
    }
    share_value = "Saved";
    share_saved = "Saved " + name + " (" + std::to_string(n) + " pipelines) in " + folder + ". ";
    logf("menu: Save my pipeline list: %s, %lld pipelines, in %s", name.c_str(), n, folder.c_str());
    if (env_on("HOS_HEADLESS")) {   // (a run without a window: nothing to show the browser or the folder on)
        share_result.store(0);
        share_finish();
        return;
    }
    // (the clipboard, the folder and the browser on a worker of their own: ShellExecuteW and xdg-open can take hundreds of ms, and
    // this is the present thread. Presses are ignored until it is done: share_busy)
    share_busy.store(true);
    share_said = share_saved + "Opening the issue...";
    try {
        std::thread([lines, path, dir] {
#ifdef _WIN32
            using CoInitFn = HRESULT(WINAPI*)(void*, DWORD);
            using CoUninitFn = void(WINAPI*)();
            static const auto co_init = (CoInitFn)(void*)share_proc(L"ole32.dll", "CoInitializeEx");
            static const auto co_uninit = (CoUninitFn)(void*)share_proc(L"ole32.dll", "CoUninitialize");
            // (ShellExecute wants COM on its thread: apartment-threaded, no OLE1 DDE)
            const bool com = co_init && co_uninit && SUCCEEDED(co_init(nullptr, 0x2 /*COINIT_APARTMENTTHREADED*/ | 0x4 /*COINIT_DISABLE_OLE1DDE*/));
#endif
            const bool copied = share_clipboard(lines);
#ifdef _WIN32
            share_open(path, true);
#else
            (void)path;
            share_open(dir);
#endif
            const bool opened = share_open(ps::kIssueUrl);
#ifdef _WIN32
            if (com) co_uninit();
#endif
            share_result.store((copied ? 1 : 0) | (opened ? 2 : 0));
        }).detach();
    } catch (const std::system_error&) {   // (no thread to be had: the zip is saved; say so, and the next press works)
        share_result.store(0);
        share_finish();
    }
}

/// A row's new value v, as the arrows set it (dir: 1 up, -1 down, for the rows that skip or wrap), saved unless !keep
/// (a slider's drag: saved once it is let go)
bool debug_warning = false;
int debug_warning_choice = 0;

void set_row(Row& r, int v, int dir, bool keep = true) {
    if (r.value == &opts.debug_tools && !opts.debug_tools && v > 0) {
        debug_warning = true;
        debug_warning_choice = 0;
        menu_refresh = true;
        return;
    }
    if (r.value == &output_pick && output_forced()) return;
    // (nothing else to choose: no change, no save. A saved choice that cannot run here is kept)
    if (row_fixed(r.value)) return;
    // (the scaling rows: only what can run here; the Render resolution row through the Upscaler's own steps)
    // (the Upscaler by engine; the Render resolution's Native is the engine's full-size form: upscaler_rows.h)
    if (r.value == &opts.dlss) v = ur::step_engine(upscaler(), dir, upscalers_available());
    if (r.value == &opts.resolution) {
        int up = upscaler(), res = *r.value;
        ur::step_render(upscaler(), ur::snap_render(upscaler(), *r.value), dir, &up, &res);
        if (up != upscaler()) opts.dlss = up;   // (Native in or out: DLAA / DLSS, FSR 4's native AA / FSR 4, XeSS's / XeSS)
        v = ur::full_scale(up) ? *r.value : res;   // (Native changes the mode, not the saved numeric scale)
    }
    if (r.value == &opts.output_res) {   // (smallest to largest: step_output_choice)
        v = step_output_choice(*r.value, dir);
        if (v == *r.value) return;
    }
    // (Mako 4.2) Frame generation by where DLSS FG cannot run: Built-in FG (1; a 0 is the same) and FSR 3.1 FG (2), one or the other
    if (r.value == &opts.framegen_by && !framegen_by_dlss_offered()) v = *r.value == 2 ? 1 : 2;
    if (stops_at_ends(r)) v = std::min(std::max(v, r.lo), r.hi);   // (a scale: it stops at its ends)
    if (r.value == &opts.pad_layout) {
        if (v > 2) v = dir > 0 ? 0 : 2;
        if (v < 0) v = 2;
        *r.value = v;
        apply_pad_layout(*r.value);
        *r.value = detect_pad_layout();   // (Custom when the preset could not be had whole)
    } else if (r.value == &opts.preset) {
        *r.value = v > r.hi ? r.lo : v < r.lo ? r.hi : v;
        apply_preset(*r.value);
    } else {
        *r.value = v > r.hi ? r.lo : v < r.lo ? r.hi : v;   // (Game language: written when the row is left, game_lang_tick)
        // (another shape: the Output resolution moves to one of its sizes, the screen's own when it has that shape)
        if (r.value == &opts.ultrawide) {
            const int out = output_for_aspect(*r.value);
            if (out != opts.output_res) opts.output_res = out, env_release(&opts.output_res);
        }
        if (!r.preset_exempt) {   // (rows no preset sets: the controls, the window, the counter...)
            // (Custom, still the preset it came from in opts.budget: Minimum's mip trimming on a small card stays with it)
            opts.preset = 0; // Custom
        }
    }
    if (r.value == &opts.transition_autosave) sync_transition_autosave();
    if (r.value == &opts.mic && can_mic()) mic_chosen();   // (hookshot)
    if (r.value == &output_pick) output_chosen();
    if (r.value == &monitor_pick) monitor_chosen();
    // (hookshot: the samplers made again, at once: their anisotropy, and the upscalers' LOD bias, vk_draw.cpp upscale_lod_bias)
    if (r.value == &opts.anisotropy || r.value == &opts.dlss || r.value == &opts.resolution || r.value == &opts.preset)
        samplers_changed();
    if (r.value == &opts.dlss || r.value == &opts.resolution || r.value == &opts.dlss_model)
        temporal_reset_failure();
    if (r.value == &opts.descriptor_reuse || r.value == &opts.sampler_cache)   // (hookshot: in play, vk_draw.cpp)
        menu_debug_rows(opts.descriptor_reuse, opts.sampler_cache);
    prompts_at_once(r);   // (hookshot)
    {   // (a row that takes a restart, or a preset that sets one: asked again at the next close)
        int now[mr::kMax];
        restart_values(now);
        restart_state.note(now);
    }
    if (keep) save();
}

// ---- (hookshot) the rows that are text fields (text_edit): their fields, what Enter on each sets, the one being edited ----
/// Custom output size: the Output resolution's size of the player's own (custom_output), typed, as output_res= in
/// hookshot_options.ini sets it (parse_output: the same rules)
bool output_size_char(char c) { return (c >= '0' && c <= '9') || c == 'x' || c == 'X'; }
const char* output_pad_chars(const TextField& f) {
    // (one separator, after 1 to 5 width digits; partial text is fine until Done)
    if (f.caret < 1 || f.caret > 5 || f.len - f.caret - (f.caret < f.len) > 5) return "0123456789";
    for (int i = 0; i < f.len; i++)
        if (i != f.caret && (f.text[i] == 'x' || f.text[i] == 'X')) return "0123456789";
    return "0123456789x";
}
TextField output_field{{}, 0, 0, 11, output_size_char, output_pad_chars};
/// The field as the setting is: the size of the player's own, or empty
void output_field_show() {
    char t[24] = "";
    if (custom_output.w) snprintf(t, sizeof t, "%ux%u", custom_output.w, custom_output.h);
    text_set(output_field, t);
}
/// "<width>x<height>", each side 1 to 5 digits, nothing else: into *w, *h
bool size_text(const char* t, unsigned* w, unsigned* h) {
    unsigned* side[2] = {w, h};
    for (int k = 0; k < 2; k++) {
        int digits = 0;
        for (*side[k] = 0; *t >= '0' && *t <= '9'; t++, digits++) *side[k] = *side[k] * 10 + (unsigned)(*t - '0');
        const bool end = k ? *t == 0 : *t == 'x' || *t == 'X';   // (the width ends at the x, the height at the text's end)
        if (digits < 1 || digits > 5 || !end) return false;
        t += !k;
    }
    return true;
}
/// Enter on Custom output size: the Output resolution row on the size typed (one it offers, or the player's own), or, emptied,
/// none of the player's own; saved. nullptr when taken, else why not
const char* output_field_apply() {
    unsigned w = 0, h = 0;
    if (output_field.len) {
        if (!size_text(output_field.text, &w, &h)) return "Type the width, an x, then the height: 3440x1440.";
        w &= ~7u, h &= ~7u;
        if (!hos_output_size_valid(w, h))
            return "Not a size the game can draw: at least 640x360, at most 5120x2880's pixels, from 5:4 to 48:9 in shape.";
    }
    // (changing the custom size can reorder the shape list: keep the startup and Later choices by shape, not index)
    int aspect_slot = -1;
    for (const Row& r : rows)
        if (r.value == &opts.ultrawide) aspect_slot = restart_slot_of(r);
    const bool follow_host = aspect_follows_host(opts.ultrawide), started_monitor = aspect_started == aspect_monitor_value();
    const std::string started_shape = aspect_shape(aspect_started);
    const bool later = aspect_slot >= 0 && restart_state.later;
    const int declined = later ? restart_state.declined[aspect_slot] : 0;
    const bool declined_monitor = later && declined == aspect_monitor_value();
    const std::string declined_shape = later ? aspect_shape(declined) : std::string();
    const bool start_custom = output_started == custom_index() && custom_output.w;
    const Out started = output_at(output_started);
    if (output_field.len) opts.output_res = output_choice_of(w, h);
    // (an offered size, including one found on a new screen, or an empty field: no separate custom choice)
    if (opts.output_res != custom_index() || !output_field.len)
        custom_output = {0, 0}, opts.output_res = output_choice(opts.output_res);
    // (the run's original custom size must still be reachable when returning to its starting shape)
    if (start_custom && (custom_output.w != started.w || custom_output.h != started.h)) {
        output_extras.push_back(started);
        output_started = last_choice();
    }
    aspect_started = started_monitor ? aspect_monitor_value() : aspect_index(started_shape);
    opts.ultrawide = aspect_of_choice(opts.output_res, follow_host);
    for (Row& r : rows) {
        if (r.value == &opts.output_res) r.hi = last_choice();
        if (r.value == &opts.ultrawide) r.hi = aspect_last();
    }
    if (aspect_slot >= 0) restart_state.restart_value(aspect_slot, aspect_started);
    if (later) restart_state.declined[aspect_slot] = declined_monitor ? aspect_monitor_value() : aspect_index(declined_shape);
    menu_refresh = true;
    output_field_show();   // (as taken: each side a multiple of 8)
    // (the player's from now on, also over HOS_OUTPUT_RES; the preset is unchanged, as for the Output resolution row)
    env_release(&opts.output_res);
    int now[mr::kMax];
    restart_values(now);
    restart_state.note(now);
    save();
    return nullptr;
}
struct FieldRow {
    const char* name;
    TextField* field;
    const char* (*apply)();
};
const FieldRow field_rows[] = {{"Custom output size", &output_field, output_field_apply}};
/// A row that is a text field (a row with no value, by its name, as is_motion_row): its field and apply; nullptr any other
const FieldRow* field_row(const Row& r) {
    for (const FieldRow& f : field_rows)
        if (!r.value && !strcmp(r.name, f.name)) return &f;
    return nullptr;
}
TextField* editing = nullptr;            // (the field that has the keyboard, menu_tick; nullptr none)
const char* (*edit_apply)() = nullptr;   // (what its Enter sets)
char edit_kept[sizeof TextField::text];  // (its text before: Esc puts it back)
const char* edit_why = nullptr;          // (why Enter did not take its text: the help's line, until the next key)
bool edit_enter_held = false;            // (the Enter that started it is still down: its repeats are not the field's Enter)
void edit_start(TextField& f, const char* (*apply)()) {
    editing = &f, edit_apply = apply, edit_why = nullptr, edit_enter_held = true;
    memcpy(edit_kept, f.text, sizeof edit_kept);
    f.caret = f.len;
}
/// The field lets the keyboard go: done (Enter: its apply takes the text, or says why not and it keeps the keyboard) or not (its
/// text back as it was)
void edit_end(bool done) {
    if (!editing || (done && edit_apply && (edit_why = edit_apply()))) return;
    if (!done) text_set(*editing, edit_kept), edit_why = nullptr;
    editing = nullptr, edit_apply = nullptr;
}

// ---- (hookshot) the Controls page: what presses each of the Switch's buttons, a gamepad input and up to two keys ----
struct Control {
    int button;   // HOS_SW_*, or HOS_KEY_* (keys only)
    const char* name;
};
const Control controls[] = {{HOS_SW_A, "A"}, {HOS_SW_B, "B"}, {HOS_SW_X, "X"}, {HOS_SW_Y, "Y"}, {HOS_SW_L, "L"},
                            {HOS_SW_R, "R"}, {HOS_SW_ZL, "ZL"}, {HOS_SW_ZR, "ZR"}, {HOS_SW_PLUS, "Plus"},
                            {HOS_SW_MINUS, "Minus"}, {HOS_SW_LS, "Left stick press"}, {HOS_SW_RS, "Right stick press"},
                            {HOS_SW_UP, "D-pad up"}, {HOS_SW_DOWN, "D-pad down"}, {HOS_SW_LEFT, "D-pad left"},
                            {HOS_SW_RIGHT, "D-pad right"}, {HOS_KEY_MOVE_UP, "Move forward"},
                            {HOS_KEY_MOVE_DOWN, "Move back"}, {HOS_KEY_MOVE_LEFT, "Move left"},
                            {HOS_KEY_MOVE_RIGHT, "Move right"}, {HOS_KEY_CAM_UP, "Camera up"},
                            {HOS_KEY_CAM_DOWN, "Camera down"}, {HOS_KEY_CAM_LEFT, "Camera left"},
                            {HOS_KEY_CAM_RIGHT, "Camera right"}, {HOS_KEY_WALK, "Walk"}, {HOS_KEY_OC_NOTE_L, "Ocarina note (L)"},
                            {HOS_KEY_OC_NOTE_R, "Ocarina note (R)"}, {HOS_KEY_OC_NOTE_A, "Ocarina note (A)"},
                            {HOS_KEY_OC_NOTE_Y, "Ocarina note (Y)"}, {HOS_KEY_OC_NOTE_X, "Ocarina note (X)"}};
constexpr int kControls = sizeof controls / sizeof controls[0];   // (then "Reset to defaults")
// (the stick's and camera's directions and Walk: keys only; the ocarina's note rows take a gamepad input too, host/nn_hid.c)
bool keys_only(int i) {
    return i < kControls && ((controls[i].button >= HOS_KEY_MOVE_UP && controls[i].button <= HOS_KEY_CAM_RIGHT) ||
                             controls[i].button == HOS_KEY_WALK);
}
// a pad input's name on the controller of the button prompts (the Button prompts row's choice; Auto: the face in use),
// else by its place
const char* pad_name(int p) {
    if (p < 0 || p >= HOS_PAD_N) return "None";
    static const char* paddles[] = {"R4", "L4", "R5", "L5"};
    if (p >= HOS_PAD_RPADDLE1) return paddles[p - HOS_PAD_RPADDLE1];
    static const char* t[HOS_PROMPT_KEYBOARD + 1][HOS_PAD_RPADDLE1] = {   // (by place, then HOS_PROMPT_*; the keyboard's: by place)
        {"Bottom button", "Right button", "Left button", "Top button", "Select / Back", "Home", "Start", "L stick press",
         "R stick press", "L1 / LB", "R1 / RB", "D-pad up", "D-pad down", "D-pad left", "D-pad right", "L2 / LT", "R2 / RT"},
        {"B", "A", "Y", "X", "Minus", "Home", "Plus", "L stick press", "R stick press", "L", "R", "D-pad up",
         "D-pad down", "D-pad left", "D-pad right", "ZL", "ZR"},
        {"A", "B", "X", "Y", "View", "Xbox", "Menu", "L stick press", "R stick press", "LB", "RB", "D-pad up",
         "D-pad down", "D-pad left", "D-pad right", "LT", "RT"},
        {"Cross", "Circle", "Square", "Triangle", "Share", "PS", "Options", "L3", "R3", "L1", "R1", "D-pad up", "D-pad down",
         "D-pad left", "D-pad right", "L2", "R2"},
        {"Cross", "Circle", "Square", "Triangle", "Create", "PS", "Options", "L3", "R3", "L1", "R1", "D-pad up", "D-pad down",
         "D-pad left", "D-pad right", "L2", "R2"},
        {"A", "B", "X", "Y", "View", "Steam", "Menu", "L3", "R3", "L1", "R1", "D-pad up", "D-pad down", "D-pad left",
         "D-pad right", "L2", "R2"},
        {"A", "B", "X", "Y", "View", "Steam", "Menu", "L3", "R3", "LB", "RB", "D-pad up", "D-pad down", "D-pad left",
         "D-pad right", "LT", "RT"}};
    const int face = opts.prompts ? opts.prompts - 1 : host && host->prompt_face ? host->prompt_face() : -1;
    return t[face >= 0 && face < HOS_PROMPT_KEYBOARD ? face + 1 : 0][p];
}
const char* key_name(int vk) {
    static char b[16];
    if ((vk >= 'A' && vk <= 'Z') || (vk >= '0' && vk <= '9')) return b[0] = (char)vk, b[1] = 0, b;
    if (vk >= VK_F1 && vk <= VK_F12) return snprintf(b, sizeof b, "F%d", vk - VK_F1 + 1), b;
    if (vk >= VK_NUMPAD0 && vk <= VK_NUMPAD0 + 9) return snprintf(b, sizeof b, "Num %d", vk - VK_NUMPAD0), b;
    switch (vk) {
    case VK_SPACE: return "Space";
    case VK_SHIFT: return "Shift";
    case VK_CONTROL: return "Ctrl";
    case VK_MENU: return "Alt";
    case VK_TAB: return "Tab";
    case VK_RETURN: return "Enter";
    case VK_BACK: return "Backspace";
    case VK_CAPITAL: return "Caps Lock";
    case VK_UP: return "Up";
    case VK_DOWN: return "Down";
    case VK_LEFT: return "Left";
    case VK_RIGHT: return "Right";
    case VK_HOME: return "Home";
    case VK_END: return "End";
    case VK_PRIOR: return "Page Up";
    case VK_NEXT: return "Page Down";
    case VK_ADD: return "Num +";
    case VK_SUBTRACT: return "Num -";
    case VK_MULTIPLY: return "Num *";
    case VK_DIVIDE: return "Num /";
    case VK_DECIMAL: return "Num .";
    case VK_OEM_1: return ";";
    case VK_OEM_PLUS: return "=";
    case VK_OEM_COMMA: return ",";
    case VK_OEM_MINUS: return "-";
    case VK_OEM_PERIOD: return ".";
    case VK_OEM_2: return "/";
    case VK_OEM_3: return "`";
    case VK_OEM_4: return "[";
    case VK_OEM_5: return "\\";
    case VK_OEM_6: return "]";
    case VK_OEM_7: return "'";
    case VK_LBUTTON: return "Left click";
    case VK_RBUTTON: return "Right click";
    case VK_MBUTTON: return "Middle click";
    case 0x05: return "Mouse 4";   // (VK_XBUTTON1)
    case 0x06: return "Mouse 5";
    }
    return snprintf(b, sizeof b, "Key %d", vk), b;
}
// the keys a binding can take (Esc cancels, Insert and F1 are the menu's, Delete clears)
const std::vector<int>& bindable_keys() {
    static std::vector<int> k;
    if (k.empty()) {
        for (int c = 'A'; c <= 'Z'; c++) k.push_back(c);
        for (int c = '0'; c <= '9'; c++) k.push_back(c);
        for (int c = VK_F2; c <= VK_F12; c++) k.push_back(c);
        for (int c = VK_NUMPAD0; c <= VK_NUMPAD0 + 9; c++) k.push_back(c);
        for (int c : {VK_SPACE, VK_SHIFT, VK_CONTROL, VK_MENU, VK_TAB, VK_RETURN, VK_BACK, VK_CAPITAL, VK_UP, VK_DOWN,
                      VK_LEFT, VK_RIGHT, VK_HOME, VK_END, VK_PRIOR, VK_NEXT, VK_ADD, VK_SUBTRACT, VK_MULTIPLY,
                      VK_DIVIDE, VK_DECIMAL, VK_OEM_1, VK_OEM_PLUS, VK_OEM_COMMA, VK_OEM_MINUS, VK_OEM_PERIOD,
                      VK_OEM_2, VK_OEM_3, VK_OEM_4, VK_OEM_5, VK_OEM_6, VK_OEM_7, VK_LBUTTON, VK_RBUTTON, VK_MBUTTON,
                      0x05, 0x06})   // (the mouse's buttons too: they count while the mouse is captured)
            k.push_back(c);
    }
    return k;
}
int page = 0;          // 0 the options, 1 the controls, 3 the teleport list, 4 the inventory, 5 the restart question (2: was the
                       // debug tools' own page, now on the Debug tab)
int csel = 0, ccol = menu_hit::kCtlPrimary;   // the page's row (options, then bindings and reset) and binding column
const int kTop = tab_row_count(TAB_PAGE);   // (Layout preset and Button prompts: a preset shows in the grid at once)
int listening = 0;     // waiting for the new input: 1 a gamepad's, 2 a key
bool listen_armed = false;   // (once what started it was let go)
int64_t listen_end = 0;
std::string keys_text(int button) {
    const int a = host->binding(HOS_BIND_KEY, button, 0), b = host->binding(HOS_BIND_KEY, button, 1);
    std::string t = a ? key_name(a) : "";
    if (b) t += std::string(a ? ", " : "") + key_name(b);
    return t.empty() ? "None" : t;
}

// ---- what is drawn: Dear ImGui over the window's image (vk_imgui.h) in the game's own style (vk_ui.h). Built anew at each
// present while something shows, from the menu's state (menu_tick and menu_record run on the presenting thread, one at a time:
// present_image's lock); nothing at all while nothing shows ----
std::mutex startup_mu;   // (the start-up screen's view, set from its own thread)
StartupView startup;
std::atomic<bool> startup_on{false};
std::atomic<float> startup_fade{0};   // (the start-up screen's fade to black at its end, 0 to 1: startup_fade_to)
std::atomic<int64_t> game_frames{0}, shown_frames{0};
char fps_text[48] = "";
char fps_sub[96] = "";   // (UTF-8: a translation's line can be three bytes a character)
// (the FPS counter's levels past the number, written every half second by menu_tick: the frame time and its 1% low; the
// Breakdown's parts, the GPU's time, the shaders built and draws left out over the graph's 4 s)
char fps_ms_text[24] = "", fps_low_text[24] = "";
double fps_ms_now = 0;   // (the frame time, for its colour)
double fps_rate_now = 0;   // (the number's rate, the game's own with frame generation: its colour)
char fps_part_text[fps_stats::kParts][24];
char fps_gpu_text[24] = "";
char fps_rt_text[fps_stats::kRtParts][24];   // (the render thread's parts, fps_texts)
char fps_gpu_busy_text[24] = "";              // (the GPU's share of the frame)
bool fps_rt_on = false;                       // (a render thread was measured)
char fps_built_text[16] = "", fps_left_text[16] = "";
char fps_dev_text[fps_stats::kDevLines][32];   // (the Dev level's values, fps_texts)
bool fps_vram_over = false;                    // (the VRAM line in red: past what the driver allows)
/// The FPS counter's target frame time, ms: the Game frame rate cap row's (HOS_FPS_MAX over it, as host/nn_vi.c, which follows
/// the row in play), or the display's refresh with V-Sync On and no frame generation when that is slower; 0 for none (Uncapped
/// without V-Sync)
/// The frame rate cap in effect: HOS_FPS_MAX's over the Game frame rate cap row's
int fps_cap_now() {
    static const int env_max = getenv("HOS_FPS_MAX") ? std::max(1, atoi(getenv("HOS_FPS_MAX"))) : 0;
    return fps_stats::cap_rate(opts.fps_cap, env_max);
}
double fps_target_ms() {
    const int cap = fps_cap_now();
    const bool fifo = menu_vsync() == 1 && opts.framegen == 0;
    return fps_stats::target_ms_for(cap, fifo, fifo ? (display_refresh_mhz() + 500) / 1000 : 0);
}
menu_hit::Map hits;      // (the menu's controls as last drawn: the mouse's, menu_tick)
float scroll_at[TAB_FPS_DEV + 2];   // (the first row shown, eased toward the selection: the options' tabs and the Motion page, then
                                   // the Controls page: kControlsSlot)
constexpr int kControlsSlot = TAB_FPS_DEV + 1;
int wheel_rows[TAB_FPS_DEV + 2];   // (the mouse wheel's notches since the last drawing, a slot each: scroll_rows scrolls by them)
int scrolled_to[TAB_FPS_DEV + 2] = {-1, -1, -1, -1, -1, -1, -1, -1};   // (the selection scroll_rows last brought into view)
float scroll_want[TAB_FPS_DEV + 2];   // (where scroll_at is going: the wheel moves it, a new selection too)
float ease_step = 0;     // (this drawing's share of the way: the time since the last one)

ui::Ctx ui_ctx(uint32_t w, uint32_t h) {
    ui::Ctx c{ImGui::GetForegroundDrawList(), ui::fonts(), 1, (float)w, (float)h, 0, pad_last};
    c.confirm_dot = menu_keys::dot(pad_confirm), c.back_dot = menu_keys::dot(pad_back);
    c.paste_dot = menu_keys::dot(pad_paste);   // (hookshot: a text field's Paste)
    c.extra_dot = menu_keys::dot(pad_junk);    // (the Tracker's Junk)
    c.s = ui::unit((float)h, opts.menu_size, &c.safe);
    return c;
}
/// The banner's height
float banner_h(const ui::Ctx& c) { return std::max(58 * c.s, c.safe + 40 * c.s); }

/// (the Bug report's line under its help once saved, below: measure_help makes room for the longest)
std::string bug_report_saved_text(const std::string& folder);
bool mic_help_row(const Row& r) {
    return r.tab == TAB_AUDIO && (!strcmp(r.name, "Test microphone") || !strcmp(r.name, "Microphone gain"));
}
std::string mic_help_text(const char* help) {
    // Whole-string lookup: translate each complete paragraph before joining the shared explanation.
    return std::string(help ? i18n::tr(help) : "") + "\n\n" + i18n::tr(kMicLevelHelp);
}
std::string mic_meter_label(int state, int incoming, int adjusted) {
    if (!(state & 1)) return i18n::tr("Test stopped");
    char text[64];
    snprintf(text, sizeof text, "Testing: %d%% -> %d%%", std::clamp(incoming, 0, 1000) / 10, std::clamp(adjusted, 0, 1000) / 10);
    return i18n::tr(text);
}
std::string mic_meter_status(int state) {
    if (!(state & 1)) return i18n::tr("Test stopped");
    std::string text = i18n::tr(!(state & 2) ? "Microphone unavailable" : !(state & 8) ? "Waiting for samples" :
                              (state & 16) ? "Clipping" : "");
    if (state & 4) text += i18n::tr(text.empty() ? "Default fallback" : " (Default fallback)");
    return text;
}
float mic_meter_height(ui::Ctx& c, float width) {
    float status = 0;
    for (int state : {0, 1, 5, 3, 7, 11, 15, 27, 31})
        status = std::max(status, ui::para(c, c.f.body, 16 * c.s, ImVec2(), 0, mic_meter_status(state).c_str(), width, false));
    return 42 * c.s + 8 * c.s + status + 14 * c.s;
}
void mic_help_meter(ui::Ctx& c, ImVec2 a, ImVec2 b);
/// The tallest help a row of the options can have, in pixels at width: its help and the tallest line any of its values can
/// have: the help box keeps that height whichever row is selected and whatever its value
float measure_help(ui::Ctx& c, float width) {
    float most = 0;
    for (const Row& r : rows) {
        float hint = 0;
        for (int v = r.lo; r.value && r.hint && v <= r.hi; v++)
            for (int k = 0; const char* t = r.hint(v, k); k++)
                hint = std::max(hint, ui::para(c, c.f.body, 16 * c.s, ImVec2(), 0, t, width - 18 * c.s, false));
        if (is_share_row(r))   // (Save my pipeline list's line after a save: the longest it can be, or the one shown when longer)
            hint = std::max(ui::para(c, c.f.body, 16 * c.s, ImVec2(), 0, kShareSaidLongest, width - 18 * c.s, false),
                            share_said.empty() ? 0.f : ui::para(c, c.f.body, 16 * c.s, ImVec2(), 0, share_said.c_str(), width - 18 * c.s, false));
        if (&r == &rows[kBugReportRow])   // (the Bug report's line once saved, with the longest folder name it can have)
            hint = ui::para(c, c.f.body, 16 * c.s, ImVec2(), 0, bug_report_saved_text("bug-reports/2026-12-31_23-59-59-99").c_str(),
                            width - 18 * c.s, false);
        if (r.help) {
            const bool mic = mic_help_row(r);
            const std::string explanation = mic ? mic_help_text(r.help) : r.help;
            most = std::max(most, ui::para(c, c.f.body, 18 * c.s, ImVec2(), 0, explanation.c_str(), width, false) +
                                  (hint ? 14 * c.s + hint : 0) + (mic ? mic_meter_height(c, width) : 0));
        }
    }
    return most;
}
/// label in room pixels: as it is when it fits; the selected row's slides through it (marquee_pos, marquee_max for menu_tick);
/// another's ends with "..."
/// (UTF-8: the byte offsets where its characters start, and the end; labels are cut and slid a character at a time, never
/// inside one: a microphone's name can be in any script)
std::vector<size_t> char_starts(const std::string& t) {
    std::vector<size_t> at;
    for (size_t i = 0; i < t.size(); i++)
        if (((unsigned char)t[i] & 0xC0) != 0x80) at.push_back(i);
    at.push_back(t.size());
    return at;
}
std::string fit(ui::Ctx& c, ImFont* f, float px, float room, const std::string& label, bool sel) {
    auto width = [&](const std::string& t) { return ui::size_of(f, px, t.c_str()).x; };
    if (width(label) <= room) return label;
    const std::vector<size_t> at = char_starts(label);
    const int chars = (int)at.size() - 1;
    if (sel) {   // (marquee_pos and marquee_max count characters)
        int start = chars;   // (the last start that still shows the label's end)
        while (start > 0 && width(label.substr(at[start - 1])) <= room) start--;
        marquee_max = start;
        const int from = std::min(marquee_pos, marquee_max);
        int end = chars;
        while (end > from + 1 && width(label.substr(at[from], at[end] - at[from])) > room) end--;
        return label.substr(at[from], at[end] - at[from]);
    }
    int end = chars;
    while (end > 1 && width(label.substr(0, at[end]) + "...") > room) end--;
    std::string t = label.substr(0, at[end]);
    while (!t.empty() && t.back() == ' ') t.pop_back();
    return t + "...";
}
/// A list of rows from top to bottom (pixels), n of them pitch apart, the selection sel kept in view: the first one shown,
/// eased toward its place (scroll_at[slot]); *shown how many fit
float scroll_rows(int slot, int n, int sel, float top, float bottom, float pitch, int* shown) {
    const int fit = std::max(1, (int)((bottom - top) / pitch));
    *shown = fit;
    float& at = scroll_at[slot];
    float& want = scroll_want[slot];
    const int wheel = std::exchange(wheel_rows[slot], 0);
    if (n <= fit) want = 0;   // (nothing to scroll: the wheel does nothing)
    else {
        want -= (float)wheel;   // (the wheel scrolls the rows and leaves the selection, and every value, as they are)
        static int fits[sizeof scroll_at / sizeof *scroll_at];   // (and after a resize: the rows that fit changed)
        if (sel != scrolled_to[slot] || fit != std::exchange(fits[slot], fit)) {   // (a new selection, by the keys or the pad: brought
                                                                                  // into view; the mouse's marks itself scrolled to)
            const int margin = fit > 4 ? 1 : 0;   // (a row of context above and below the selection)
            if (sel - margin < want) want = (float)(sel - margin);
            if (sel + margin + 1 > want + fit) want = (float)(sel + margin + 1 - fit);
        }
        want = std::round(std::clamp(want, 0.0f, (float)(n - fit)));
    }
    scrolled_to[slot] = sel;
    at += (want - at) * ease_step;
    if (std::fabs(want - at) < 0.01f) at = want;
    return at;
}
/// The scroll bar at x, beside a list of n rows of which shown fit, the first at `first`
void scroll_bar(ui::Ctx& c, float x, float top, float bottom, int n, int shown, float first) {
    if (n <= shown) return;
    const float s = c.s, span = bottom - top, y0 = top + span * first / n, y1 = top + span * (first + shown) / n;
    c.d->AddRectFilled(ImVec2(x - 2 * s, top), ImVec2(x + 2 * s, bottom), ui::rgba(0, 0, 0, 140), 2 * s);
    c.d->AddRectFilled(ImVec2(x - 2 * s, y0), ImVec2(x + 2 * s, y1), ui::kAccent, 2 * s);
}
/// The banner with a page's title in the middle (the Controls, Cheats and list pages), its height
float title_banner(ui::Ctx& c, const char* title, const char* right) {
    const float hh = banner_h(c), s = c.s;
    ui::banner(c, hh);
    ui::text_mid_centre(c, c.f.heading, 24 * s, c.w * 0.5f, hh * 0.5f + s, ui::kBannerInk, title);
    if (right) ui::text_mid_right(c, c.f.body, 17 * s, c.w - c.safe, hh * 0.5f + s, ui::kBannerInk, right);
    return hh;
}
/// Keep translated microphone explanations readable in the available help area. Other help keeps its normal size.
float mic_help_font_size(ui::Ctx& c, const char* help, float width, float height) {
    for (float px = 18; px > 14; px -= 0.5f)
        if (!help || ui::para(c, c.f.body, px * c.s, ImVec2(), 0, help, width, false) <= height) return px * c.s;
    return 14 * c.s;
}
/// The help box from (x0, y0) to x1: a title, the help, a line set off by a bar, a gold line at its foot. min_h: its height at
/// least (the tallest help the page can have, so it does not jump)
void help_box(ui::Ctx& c, float x0, float x1, float y0, const char* title, const char* help, const char* hint, const char* gold_line,
              float min_h = 0, bool after_restart = false, float y_min = 0, float y_max = FLT_MAX, bool microphone = false) {
    // (y_max: the box ends above it, the prompt strip's top: moved up as far as y_min (under the banner) when it is taller than
    // the room below y0, its reserved height (min_h) given up first, its text cut at its foot only if it still does not fit)
    const float s = c.s, w = x1 - x0 - 48 * s;
    const std::string explanation = microphone ? mic_help_text(help) : "";
    if (microphone) help = explanation.c_str();
    const float meter_h = microphone ? mic_meter_height(c, w) : 0;
    const float hh = hint ? ui::para(c, c.f.body, 16 * s, ImVec2(), 0, hint, w - 18 * s, false) : 0;
    const float note = after_restart ? 30 * s : 0;
    const float fixed = 22 * s + (title ? 32 * s : 0) + note + (gold_line ? 52 * s : 0) + 22 * s;
    const float help_px = microphone ? mic_help_font_size(c, help, w, y_max - y_min - fixed - meter_h - (hint ? 14 * s + hh : 0)) : 18 * s;
    const float th = help ? ui::para(c, c.f.body, help_px, ImVec2(), 0, help, w, false) : 0;
    const float text_h = th + (hint ? 14 * s + hh : 0) + meter_h;
    float body = std::max(min_h, text_h);
    if (y0 + fixed + body > y_max) y0 = std::max(y_min, y_max - fixed - body);
    if (y0 + fixed + body > y_max) body = std::max(text_h, y_max - y0 - fixed);
    const float y1 = std::min(y0 + fixed + body, y_max);
    ui::box(c, ImVec2(x0, y0), ImVec2(x1, y1));
    c.d->PushClipRect(ImVec2(x0, y0), ImVec2(x1, y1), true);
    float y = y0 + 22 * s;
    if (title) ui::text(c, c.f.heading, 21 * s, ImVec2(x0 + 24 * s, y), ui::kInk, title), y += 32 * s;
    if (after_restart) {   // (this row's change applies at the next start: said here, not in the row, where it would cut the name)
        ui::diamond(c, ImVec2(x0 + 29 * s, y + 10 * s), 4 * s, ui::kGoldHi);
        ui::text_mid(c, c.f.strong, 16 * s, x0 + 42 * s, y + 10 * s, ui::kGoldHi, "Takes effect after a restart");
        y += note;
    }
    if (microphone && mic_testing) {
        mic_help_meter(c, ImVec2(x0 + 24 * s, y), ImVec2(x1 - 24 * s, y + 42 * s));
        y += meter_h;
    }
    if (help) ui::para(c, c.f.body, help_px, ImVec2(x0 + 24 * s, y), ui::kInk, help, w);
    if (hint) {
        const float hy = y + th + 14 * s;
        c.d->AddRectFilled(ImVec2(x0 + 24 * s, hy + 2 * s), ImVec2(x0 + 26.5f * s, hy + hh - 2 * s), ui::kAccent, s);
        ui::para(c, c.f.body, 16 * s, ImVec2(x0 + 40 * s, hy), ui::kSoft, hint, w - 18 * s);
    }
    if (gold_line) {
        y = y0 + 22 * s + (title ? 32 * s : 0) + note + body + 20 * s;
        c.d->AddLine(ImVec2(x0 + 24 * s, y), ImVec2(x1 - 24 * s, y), ui::alpha(ui::kEdge, 0.8f), std::max(1.0f, s));
        ui::diamond(c, ImVec2(x0 + 29 * s, y + 20 * s), 4 * s, ui::kGoldHi);
        ui::text_mid(c, c.f.strong, 16 * s, x0 + 42 * s, y + 20 * s, ui::kGoldHi, gold_line);
    }
    c.d->PopClipRect();
}
/// The menu's column: from the safe margin to about 58% of the width (wide enough for a row at any unit); the help box beside it,
/// or, on a narrow window, over the column's foot (*narrow)
void columns(const ui::Ctx& c, float* x0, float* x1, float* hx0, float* hx1, bool* narrow) {
    const float s = c.s;
    *x0 = c.safe + 6 * s;
    *x1 = std::min(c.w - c.safe, std::max(c.w * 0.585f, *x0 + 560 * s));
    *hx0 = *x1 + 28 * s, *hx1 = c.w - c.safe;
    *narrow = *hx1 - *hx0 < 260 * s;
    if (*narrow) *hx0 = *x0 + 20 * s, *hx1 = *x1 - 20 * s;
}
void column(ui::Ctx& c, float x0, float x1, float top) {
    const float s = c.s;
    c.d->AddRectFilled(ImVec2(x0, top), ImVec2(x1, c.h), ui::kColumn);
    c.d->AddLine(ImVec2(x0, top), ImVec2(x0, c.h), ui::alpha(ui::kEdge, 0.7f), std::max(1.0f, s));
    c.d->AddLine(ImVec2(x1, top), ImVec2(x1, c.h), ui::alpha(ui::kEdge, 0.7f), std::max(1.0f, s));
}
/// A row's name cell, selected or not, its tag (After restart) at its right end
/// A row's name cell, selected or not; pending: a change that applies after a restart, a small gold diamond at its right end
/// (the help says it in words)
void name_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const char* name, bool sel, bool pending = false, float px = 18.5f) {
    const float s = c.s, mid = (a.y + b.y) * 0.5f;
    c.d->AddRectFilled(a, b, sel ? ui::kCellNameSel : ui::kCellName, ui::kRound * s);
    c.d->AddRect(a, b, ui::kEdge, ui::kRound * s, 0, std::max(1.0f, s));
    if (sel) c.d->AddRectFilled(ImVec2(a.x + 3 * s, a.y + 7 * s), ImVec2(a.x + 7 * s, b.y - 7 * s), ui::kAccent, 2 * s);
    float room = b.x - a.x - 36 * s;
    if (pending) {
        ui::diamond(c, ImVec2(b.x - 12 * s, mid), 4 * s, ui::kGoldHi);
        room -= 14 * s;
    }
    ImFont* f = sel ? c.f.strong : c.f.body;
    const std::string shown = fit(c, f, px * s, room, name, false);
    ui::text_mid(c, f, px * s, a.x + 20 * s, mid, sel ? ui::kInkBright : ui::kInk, shown.c_str());
}
/// A value cell: a choice with arrows at its ends (left, right: whether it can go that way), gold when selected
void choice_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const std::string& value, bool sel, bool left, bool right, bool fixed = false) {
    const float s = c.s, mid = (a.y + b.y) * 0.5f, in = 4 * s, px = 18 * s;
    c.d->AddRectFilled(a, b, ui::kCellDark, ui::kRound * s);
    c.d->AddRect(a, b, ui::kEdge, ui::kRound * s, 0, std::max(1.0f, s));
    if (sel && !fixed) ui::gold(c, a + ImVec2(in, in), b - ImVec2(in, in));
    const ImU32 ink = sel && !fixed ? ui::kGoldInk : fixed ? ui::kDim : ui::kInk, arrow = sel && !fixed ? ui::kGoldInk : ui::kDim;
    if (left) ui::triangle(c, ImVec2(a.x + in + 11 * s, mid), 9 * s, 0, arrow);
    if (right) ui::triangle(c, ImVec2(b.x - in - 11 * s, mid), 9 * s, 1, arrow);
    ImFont* f = sel ? c.f.strong : c.f.body;
    const std::string shown = fit(c, f, px, b.x - a.x - 2 * in - (left || right ? 48 : 16) * s, value, sel);   // (room for arrows)
    ui::text_mid_centre(c, f, px, (a.x + b.x) * 0.5f, mid, ink, shown.c_str());
    if (sel) ui::glow(c, a, b);
}
/// A value cell of two halves (a row of two values: On and Off), the chosen one filled
void halves_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const char* lo, const char* hi, bool high, bool sel, bool fixed) {
    const float s = c.s, mid = (a.y + b.y) * 0.5f, in = 4 * s, px = 18 * s, xm = (a.x + b.x) * 0.5f;
    c.d->AddRectFilled(a, b, ui::kCellDark, ui::kRound * s);
    c.d->AddRect(a, b, ui::kEdge, ui::kRound * s, 0, std::max(1.0f, s));
    const ImVec2 fa = high ? ImVec2(xm, a.y + in) : a + ImVec2(in, in), fb = high ? b - ImVec2(in, in) : ImVec2(xm, b.y - in);
    if (sel && !fixed) ui::gold(c, fa, fb);
    else c.d->AddRectFilled(fa, fb, ui::kBronze, (ui::kRound - 2) * s);
    const ImU32 on = sel && !fixed ? ui::kGoldInk : ui::kInk;
    ui::text_mid_centre(c, high ? c.f.body : c.f.strong, px, (a.x + xm) * 0.5f, mid, high ? ui::kDim : on, lo);
    ui::text_mid_centre(c, high ? c.f.strong : c.f.body, px, (xm + b.x) * 0.5f, mid, high ? on : ui::kDim, hi);
    if (sel) ui::glow(c, a, b);
}
/// A slider's value cell; a display-only meter omits adjustment arrows and mouse track bounds.
void slider_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const char* value, int permille, bool sel, float* t0, float* t1, bool adjustable = true) {
    const float s = c.s, mid = (a.y + b.y) * 0.5f, in = 4 * s, px = 18 * s;
    c.d->AddRectFilled(a, b, ui::kCellDark, ui::kRound * s);
    c.d->AddRect(a, b, ui::kEdge, ui::kRound * s, 0, std::max(1.0f, s));
    if (sel) ui::gold(c, a + ImVec2(in, in), b - ImVec2(in, in));
    const float x0 = a.x + in + 24 * s, x1 = b.x - in - 24 * s, xv = x0 + (x1 - x0) * permille / 1000.0f, ty = b.y - in - 5.5f * s;
    const ImU32 track = sel ? ui::rgba(255, 255, 255, 70) : ui::rgba(255, 255, 255, 40), done = sel ? ui::kGoldInk : ui::kAccent;
    c.d->AddRectFilled(ImVec2(x0, ty - 1.5f * s), ImVec2(x1, ty + 1.5f * s), track, 1.5f * s);
    c.d->AddRectFilled(ImVec2(x0, ty - 1.5f * s), ImVec2(xv, ty + 1.5f * s), done, 1.5f * s);
    c.d->AddCircleFilled(ImVec2(xv, ty), 4.5f * s, done);
    ui::text_mid_centre(c, c.f.strong, px, (a.x + b.x) * 0.5f, mid - 3 * s, sel ? ui::kGoldInk : ui::kInk, value);
    if (adjustable) {
        const ImU32 arrow = sel ? ui::kGoldInk : ui::kDim;
        ui::triangle(c, ImVec2(a.x + in + 11 * s, mid), 9 * s, 0, arrow), ui::triangle(c, ImVec2(b.x - in - 11 * s, mid), 9 * s, 1, arrow);
    }
    if (sel) ui::glow(c, a, b);
    *t0 = adjustable ? x0 : 0, *t1 = adjustable ? x1 : 0;
}
/// Read-only live meter in help, with no mouse-hit registration or adjustment arrows.
void mic_help_meter(ui::Ctx& c, ImVec2 a, ImVec2 b) {
    const std::string label = mic_meter_label(mic_test_state, mic_levels[0], mic_levels[1]);
    const std::string status = mic_meter_status(mic_test_state);
    float unused0 = 0, unused1 = 0;
    slider_cell(c, a, b, label.c_str(), std::clamp(mic_levels[1], 0, 1000), false, &unused0, &unused1, false);
    if (!status.empty()) ui::para(c, c.f.body, 16 * c.s, ImVec2(a.x, b.y + 8 * c.s), ui::kSoft, status.c_str(), b.x - a.x);
}
/// (hookshot) A text field's value cell: its text from the left (cut with "..." when too long); empty, the placeholder, dim.
/// While it has the keyboard (typing): light text on the dark cell inside a gold frame, a steady caret at its place, the text slid
/// left to keep the caret in view
void text_cell(ui::Ctx& c, ImVec2 a, ImVec2 b, const TextField& f, bool sel, bool typing, const char* placeholder) {
    const float s = c.s, mid = (a.y + b.y) * 0.5f, in = 4 * s, px = 18 * s, x0 = a.x + in + 12 * s, room = b.x - in - 12 * s - x0;
    c.d->AddRectFilled(a, b, ui::kCellDark);
    c.d->AddRect(a, b, ui::kEdge, 0, std::max(1.0f, s));
    if (sel && !typing) ui::gold(c, a + ImVec2(in, in), b - ImVec2(in, in));
    ImFont* font = sel ? c.f.strong : c.f.body;
    const std::string t(f.text, (size_t)std::clamp(f.len, 0, (int)sizeof f.text - 1));
    if (t.empty() && !typing) {
        ui::text_mid(c, c.f.body, px, x0, mid, sel ? ui::kGoldInk : ui::kDim, placeholder);
    } else if (!typing) {
        ui::text_mid(c, font, px, x0, mid, sel ? ui::kGoldInk : ui::kInk, fit(c, font, px, room, t, false).c_str());
    } else {
        const float caret = ui::size_of(font, px, t.substr(0, (size_t)std::clamp(f.caret, 0, (int)t.size())).c_str()).x;
        const float shift = std::max(0.0f, caret - room);
        c.d->PushClipRect(ImVec2(x0 - 3 * s, a.y), ImVec2(x0 + room + 3 * s, b.y), true);
        ui::text_mid(c, font, px, x0 - shift, mid, ui::kInkBright, t.c_str());
        c.d->AddRectFilled(ImVec2(x0 - shift + caret, mid - 11 * s), ImVec2(x0 - shift + caret + 2 * s, mid + 11 * s), ui::kGoldHi);
        c.d->PopClipRect();
        c.d->AddRect(a + ImVec2(in * 0.5f, in * 0.5f), b - ImVec2(in * 0.5f, in * 0.5f), ui::kGoldHi, 0, 2.5f * s);
    }
    if (sel) ui::glow(c, a, b);
}
/// "Restart needed: " and the pending rows, on one line of width: the last ones as "and N more" when they do not fit
std::string restart_line(ui::Ctx& c, float px, float width) {
    const unsigned all = restart_pending();
    std::string line;
    for (int keep = restart_state.n; keep >= 0; keep--) {   // (the first `keep` pending rows by name)
        unsigned shown = 0;
        int named = 0, more = 0;
        for (int i = 0; i < restart_state.n; i++)
            if ((all >> i) & 1) (named < keep ? (shown |= 1u << i, named++) : more++);
        const char* names[mr::kMax];
        for (int i = 0; i < restart_state.n; i++) names[i] = i18n::tr(restart_names[i]);
        line = i18n::tr("Restart needed: ") + mr::names(names, restart_state.n, shown);
        if (more) {   // (" settings (many)": the form Russian and Polish take for 5 and up, i18n::plural; never asked in English)
            const int form = i18n::plural(more);
            line += std::string(named ? i18n::tr(" and ") : "") + std::to_string(more) +
                    i18n::tr(named ? " more" : form == 0 ? " setting" : form == 1 ? " settings" : " settings (many)");
        }
        if (ui::size_of(c.f.strong, px, line.c_str()).x <= width) break;
    }
    return line;
}

/// (hookshot) The Debug tab's order: the tools' rows by their group (Row::cheat), Up and Down walking them so; Inventory item
/// and Change quantity are not shown (the Inventory page edits every amount)
struct DebugGroup { const char* title; int from, to; };   // (debug_tools_order[from, to))
// (-1 is the saved Damage taken option, not a cheat action: beside Heart protection in Player)
constexpr int debug_tools_order[] = {0, -1, 1, 11, 9, 10, 8, 2, 3, 7, 4};
constexpr DebugGroup debug_groups[] = {{"Player", 0, 6}, {"Travel", 6, 9}, {"Camera & world", 9, 11}};
constexpr int kDebugGroups = sizeof debug_groups / sizeof debug_groups[0];
constexpr int kDebugGeneralRows = 2;
constexpr int kDebugTools = sizeof debug_tools_order / sizeof debug_tools_order[0];
/// The Debug tab's rows as shown (its row numbers, tab_row_to_global's): the switch, the tools in debug_tools_order while they
/// are on, then the Developer rows; *dev where those start, *dev_head the Developer heading's row (-1 none). Their count
int debug_rows(int* out, int* dev, int* dev_head) {
    const int count = tab_row_count(TAB_DEBUG);
    int n = 0;
    *dev_head = -1;
    for (int k = 0; k < count; ++k) {
        const Row& r = rows[tab_row_to_global(TAB_DEBUG, k)];
        if (r.value == &opts.debug_tools || r.value == &opts.transition_autosave) out[n++] = k;
    }
    for (int t = 0; t < kDebugTools; ++t)
        for (int k = 0; k < count; ++k) {
            const Row& r = rows[tab_row_to_global(TAB_DEBUG, k)];
            if (debug_tools_order[t] == -1 ? r.value == &opts.damage_taken : r.cheat == debug_tools_order[t]) out[n++] = k;
        }
    *dev = n;
    if (quick_debug) return n;
    for (int k = 0; k < count; ++k) {
        const Row& r = rows[tab_row_to_global(TAB_DEBUG, k)];
        if (r.heading) *dev_head = k;
        else if (*dev_head >= 0 && r.cheat < 0 && r.value != &opts.debug_tools && !is_share_row(r)) out[n++] = k;   // (Mako: no pipeline share)
    }
    return n;
}
/// The Debug tab's row after sel (dir 1) or before it (dir -1), in debug_rows' order
int debug_step(int sel, int dir) {
    int order[64], dev = 0, head = -1;
    const int n = debug_rows(order, &dev, &head);
    int at = 0;
    while (at < n && order[at] != sel) at++;
    if (at == n) return order[0];
    return order[(at + n + dir) % n];
}
/// (hookshot) The Debug tab's rows from top down to bottom, sel selected: Debug tools across the top; the tools under their
/// headings, Player in the first column and Travel and Camera & world in the second when two fit (else one under another);
/// the Developer rows across the foot. Each value cell a column's width, so their edges line up. The hits are the tab's row
/// numbers, as the list's: menu_tick's clicks and keys are the other tabs'
void draw_debug_rows(ui::Ctx& c, float cx0, float cx1, float top, float bottom, int sel) {
    const float s = c.s, px = 18 * s, pitch = 48 * s, rh = 40 * s, gap = 24 * s;   // (the other tabs' rows: 40 high, 48 apart)
    const float left = cx0 + 44 * s, right = cx1 - 44 * s, mid = (left + right) * .5f;
    int order[64], dev = 0, dev_head = -1;
    const int n = debug_rows(order, &dev, &dev_head);
    // (two columns only when each fits its longest name whole (name_cell's room, the selected's bold) and its value cells at
    // their narrowest; the cells then as wide as the room lets them, up to what they ask)
    const float halves_w = 2 * std::max(ui::size_of(c.f.strong, px, "Off").x, ui::size_of(c.f.strong, px, "On").x);
    auto need = [&](const Row& r, bool tight) {
        const float pad = (tight ? 36 : 64) * s;
        if (r.cheat == 9 && age_shown(9))
            return 2 * std::max(ui::size_of(c.f.strong, px, "Kid").x, ui::size_of(c.f.strong, px, "Adult").x) + pad;
        if (r.value && r.hi - r.lo != r.step) {   // (a row of more than two values: its widest, arrows)
            float w = 0;
            for (int v = r.lo; v <= r.hi; v += r.step) w = std::max(w, ui::size_of(c.f.strong, px, r.text(v)).x);
            return w + (tight ? 56 : 68) * s;
        }
        if (r.cheat == 0 || r.cheat == 1 || r.cheat == 7 || r.value) return halves_w + pad;
        if (is_share_row(r)) return ui::size_of(c.f.strong, px, "Not saved").x + (tight ? 56 : 60) * s;   // (Save, Saved, Not saved)
        if (is_laptop_row(r)) return ui::size_of(c.f.strong, px, "Applied").x + (tight ? 56 : 60) * s;   // (Apply, Applied)
        const std::string v = r.cheat == 11 ? "1.25x" : cheat_value(r.cheat);   // (Movement speed: its widest, the cell kept still)
        const char* const says = cheat_button_text(r.cheat);
        return ui::size_of(c.f.strong, px, v.empty() ? says : v.c_str()).x + (cheat_chooses(r.cheat) ? 68 : tight ? 56 : 60) * s;   // (choice_cell keeps 48 for arrows either way)
    };
    float name_need[2] = {0, 0}, cell_full[2] = {halves_w + 64 * s, halves_w + 64 * s}, cell_tight[2] = {halves_w + 36 * s, halves_w + 36 * s};
    for (int i = kDebugGeneralRows; i < dev; ++i) {
        const Row& r = rows[tab_row_to_global(TAB_DEBUG, order[i])];
        const int col = i - kDebugGeneralRows >= debug_groups[0].to ? 1 : 0;   // (Player in the first, the rest in the second)
        name_need[col] = std::max(name_need[col], ui::size_of(c.f.strong, 18.5f * s, r.name).x + 40 * s);
        cell_full[col] = std::max(cell_full[col], need(r, false)), cell_tight[col] = std::max(cell_tight[col], need(r, true));
    }
    const float col_w = (right - left - gap) * .5f;
    const bool two = col_w >= name_need[0] + cell_tight[0] && col_w >= name_need[1] + cell_tight[1];
    // (where each goes: a row number of the layout and a column)
    int vrow[64] = {}, vcol[64] = {}, head_row[kDebugGroups] = {}, head_col[kDebugGroups] = {};
    vrow[1] = 1;
    int next_row[2] = {kDebugGeneralRows, kDebugGeneralRows};
    const bool tools = dev > kDebugGeneralRows;
    for (int g = 0; tools && g < kDebugGroups; ++g) {
        const int col = two && g > 0 ? 1 : 0;
        if (next_row[col] > kDebugGeneralRows) next_row[col]++;   // (a gap over a heading that follows another group)
        head_row[g] = next_row[col]++, head_col[g] = col;
        for (int t = debug_groups[g].from; t < debug_groups[g].to; ++t) vrow[kDebugGeneralRows + t] = next_row[col]++, vcol[kDebugGeneralRows + t] = col;
    }
    int foot = std::max(next_row[0], next_row[1]);
    if (tools) foot++;
    const int dev_row = foot;
    for (int i = dev; i < n; ++i) vrow[i] = dev_row + 1 + (i - dev);
    const int visual_count = n > dev ? dev_row + 1 + (n - dev) : foot;
    int sel_at = 0;
    for (int i = 0; i < n; ++i)
        if (order[i] == sel) sel_at = vrow[i];
    int shown = 0;
    const float first = scroll_rows(TAB_DEBUG, visual_count, sel_at, top, bottom, pitch, &shown);
    scroll_bar(c, cx0 + 20 * s, top, top + shown * pitch - (pitch - rh), visual_count, shown, first);
    // (the value cells' widths, a column's alike: what they ask, given up toward their narrowest while a name needs the room)
    float cell_w[2];
    if (two) {
        for (int k = 0; k < 2; ++k) cell_w[k] = std::max(cell_tight[k], std::min(cell_full[k], col_w - name_need[k]));
    } else {   // (one column: as wide as any of the tools asks)
        const float w = std::max(cell_full[0], cell_full[1]);
        cell_w[0] = cell_w[1] = std::max(std::min(w, right - left - std::max(name_need[0], name_need[1])), std::max(cell_tight[0], cell_tight[1]));
    }
    auto heading = [&](float x0, float x1, int row, const char* title) {   // (as the list's Developer heading: gold, a rule after)
        const float y = top + (row - first) * pitch, ty = y + rh * 0.62f, tw = ui::size_of(c.f.heading, 19 * s, title).x;
        if (y + pitch <= top || y >= bottom) return;
        ui::text_mid(c, c.f.heading, 19 * s, x0 + 2 * s, ty, ui::kGoldHi, title);
        if (x0 + tw + 16 * s < x1) c.d->AddLine(ImVec2(x0 + tw + 16 * s, ty), ImVec2(x1, ty), ui::alpha(ui::kEdge, 0.9f), std::max(1.0f, s));
    };
    c.d->PushClipRect(ImVec2(cx0, top), ImVec2(cx1, std::max(top, bottom)), true);
    for (int g = 0; tools && g < kDebugGroups; ++g)
        heading(head_col[g] ? mid + gap * .5f : left, !two || head_col[g] ? right : mid - gap * .5f, head_row[g], debug_groups[g].title);
    if (dev_head >= 0 && n > dev) heading(left, right, dev_row, rows[tab_row_to_global(TAB_DEBUG, dev_head)].name);
    for (int i = 0; i < n; ++i) {
        const int k = order[i];
        const Row& r = rows[tab_row_to_global(TAB_DEBUG, k)];
        const float y = top + (vrow[i] - first) * pitch;
        if (y + pitch <= top || y >= bottom) continue;
        const bool in_tools = i >= kDebugGeneralRows && i < dev;
        const float x0 = two && in_tools && vcol[i] ? mid + gap * .5f : left;
        const float x1 = !two || !in_tools || vcol[i] ? right : mid - gap * .5f;
        const bool selected = k == sel;
        const float width = in_tools ? cell_w[vcol[i]] : std::max(need(r, false), cell_w[two ? 1 : 0]);
        const ImVec2 va(x1 - width, y), vb(x1, y + rh);
        name_cell(c, ImVec2(x0, y), ImVec2(va.x, y + rh), r.name, selected, restart_changed(r));   // (boxed, as on the other tabs)
        if (r.value && r.hi - r.lo != r.step) {   // (a choice with arrows, as on the other tabs)
            const bool fixed = row_fixed(r.value);
            choice_cell(c, va, vb, r.text(*r.value), selected, !fixed, !fixed, fixed);
        } else if (r.value) {   // (Debug tools and the Developer rows: values of the options, Off and On)
            halves_cell(c, va, vb, std::string(r.text(r.lo)).c_str(), std::string(r.text(r.hi)).c_str(), *r.value == r.hi, selected,
                        row_fixed(r.value));
        } else if (is_share_row(r)) {   // (Save my pipeline list: what the last press did)
            choice_cell(c, va, vb, share_value.empty() ? "Save" : share_value, selected, false, false);
        } else if (is_laptop_row(r)) {
            choice_cell(c, va, vb, laptop_applied ? "Applied" : "Apply", selected, false, false);
        } else if (r.cheat == 0 || r.cheat == 1 || r.cheat == 7) {
            halves_cell(c, va, vb, "Off", "On", cheat_value(r.cheat) == "On", selected, false);
        } else if (age_shown(r.cheat)) {   // (Link's age now: the other half switches)
            halves_cell(c, va, vb, "Kid", "Adult", link_age.load(std::memory_order_relaxed) == 1, selected, false);
        } else {
            const std::string v = cheat_value(r.cheat);
            choice_cell(c, va, vb, v.empty() ? cheat_button_text(r.cheat) : v, selected, cheat_chooses(r.cheat), cheat_chooses(r.cheat), r.cheat == 9);
        }
        hits.add(x0, std::max(y, top), x1, std::min(y + rh, bottom), menu_hit::kRow, k, va.x, vb.x);
    }
    c.d->PopClipRect();
}

// A report cannot format Options{} as a live list index, or format a hypothetical
// default through a callback that reads the current engine/display (the Output
// resolution, Upscaler, Render resolution, Window scaling filter). The Quality
// preset's is Auto (this PC) at a first start. The other rows a preset sets have
// the built-in defaults only for a Custom player Auto never chose for (auto_for 0);
// else Auto's for this PC, which only apply_auto knows, and running it here would
// change the live options the renderer reads. Keep their current values, but do
// not call them changes or invent a default. GPU 0 and microphone 1 stay stable;
// report_default has the Aspect ratio's, the Game language's and Frame generation by's.
// The DLSS model's depends on RX_VK_DLSS_PRESET, and on the card's memory (CNN (E) under 7 GB).
bool report_default_depends_on_pc(const Row& r) {
    if (r.value == &opts.sharpness || r.value == &opts.pace || r.value == &opts.realtime ||
        r.value == &opts.handheld)
        return opts.preset != 0 || auto_for != 0;
    return r.value == &opts.output_res || r.value == &opts.resolution || r.value == &opts.dlss ||
           r.value == &opts.preset || r.value == &opts.upscale ||
           (r.value == &opts.dlss_model && (dlss_preset_env() || ur::cnn_for_vram(ur::MODEL_K, device_vram_bytes())));
}
// The report's default for row r: the default options' value (fixed), or the one the
// menu knows better. The Aspect ratio's is the monitor's shape, as outputs_sync makes
// it from the default Output resolution and ultrawide=1; the Game language's is
// language.txt's, else the first (README). Frame generation by with nothing to
// choose (framegen_by_fixed) is the run's, whatever is saved: no change of the player's.
int report_default(const Row& r, int fixed) {
    static const Options defaults{};
    if (r.value == &opts.ultrawide) return aspect_of_choice(defaults.output_res, defaults.ultrawide);
    if (r.value == &opts.game_lang) return i18n::game_lang_index();
    if (r.value == &opts.framegen_by && framegen_by_fixed()) return *r.value;
    return fixed;
}
// (hookshot) the Gameplay tab's Bug report: the rows not at their defaults, as the menu shows them, for its "Changes from the
// defaults"
std::string changed_rows_text(std::string& pc_options) {
    static const Options defaults{};
    std::string out;
    pc_options.clear();
    for (const Row& r : rows) {
        const char* at = (const char*)r.value;
        if (!r.value || !r.text || r.heading || at < (const char*)&opts || at >= (const char*)(&opts + 1)) continue;
        const int was = report_default(r, *(const int*)((const char*)&defaults + (at - (const char*)&opts)));
        const bool depends = report_default_depends_on_pc(r);
        if (!depends && *r.value == was) continue;
        std::string& to = depends ? pc_options : out;
        to += r.name;
        to += ": ";
        // (a microphone chosen by its name, not the name: a device's name can be a person's)
        to += r.value == &opts.mic && *r.value >= 2 ? "a microphone by its name" : r.text(*r.value);
        to += depends ? " (default depends on this PC" : " (default: ";
        if (!depends) to += r.text(was);
        if (restart_changed(r)) to += "; takes effect after a restart";
        to += ")\n";
    }
    return out;
}
/// (the report's picture: the control bridge's kind of shot, of the next present, vk_replay.cpp shot_ask_next: an image and a
/// buffer of its own, 1280x720, copied from the game's frame, which the menu is never drawn into, read back once the GPU is past it)
bool bug_report_picture(const char* path, uint64_t ticket) {
    return shot_ask_next(path, [](void* asked, int64_t, int ok) { bug_report::picture_written((uint64_t)(uintptr_t)asked, ok != 0); },
                         (void*)(uintptr_t)ticket) != 0;
}
/// A or Enter on the Bug report: the report gathered here (the menu's part) and written on a thread of its own
void bug_report_save() {
    if (bug_report::state() == bug_report::kSaving) return;
    if (host && host->log_flush) host->log_flush();   // (the log's queued lines into the file first)
    bug_report::Inputs in;
    bug_report::fill_here(in);
    in.version = HOOKSHOT_VERSION;
    in.gpu = device_report_text();
    in.options = changed_rows_text(in.pc_options);
    in.game_dir = game_folder_path();   // (its logs/ and bug-reports/: vk_paths.h)
    in.log = [](const char* line) { logf("%s", line); };
    in.ask_picture = bug_report_picture;
    logf("menu: bug report asked for");
    bug_report::start(std::move(in));
}
/// The Bug report's value cell: what A or Enter does, or how the last report went
const char* bug_report_cell() {
    switch (bug_report::state()) {
    case bug_report::kSaving: return "Saving...";
    case bug_report::kSaved: return "Saved";
    case bug_report::kFailed: return "Not saved";
    default: return "Press to save";
    }
}
/// Under its help once saved: where the report is and what to do with it (the game opens nothing: no browser or file manager is
/// sure to be there, as on a Steam Deck in Game Mode)
std::string bug_report_saved_text(const std::string& folder) {
    return "Saved in the game folder as " + folder + ". To send it, open github.com/Shakoquo/Mako/issues, choose New issue and "
           "Game problem, copy report.txt's answers into the form and drag the folder's files into it: on Windows from File "
           "Explorer, on Linux from a file manager (on a Steam Deck, in Desktop Mode).";
}
/// Under its help once pressed: how the report goes
const char* bug_report_hint() {
    static std::string text;
    switch (bug_report::state()) {
    case bug_report::kSaving: text = "Saving: the logs are copied and the picture taken."; break;
    case bug_report::kSaved: text = bug_report_saved_text(bug_report::shown()); break;
    case bug_report::kFailed: text = "Not saved: " + bug_report::shown() + "."; break;
    default: return nullptr;
    }
    return text.c_str();
}

const char* const tab_titles[TAB_COUNT] = {"Graphics", "Audio", "Gameplay", "Controls", "Debug", "Tracker"};
inline const char* tab_title(int t) { return t >= 0 && t < TAB_COUNT ? tab_titles[t] : "Settings"; }
inline bool cheat_is_toggle(int c) { return c == 0 || c == 1 || c == 7; }

/// Draws a row's value cell (slider, toggle, choice, or subpage arrow), shared between the full menu and tuning bar
void row_value_cell(ui::Ctx& c, const Row& r, ImVec2 va, ImVec2 vb, bool selected, float* t0, float* t1) {
    const float s = c.s, mid = (va.y + vb.y) * 0.5f;
    const std::string tool = r.cheat >= 0 ? cheat_value(r.cheat) : "";
    if (r.cheat >= 0 && cheat_is_toggle(r.cheat)) {
        halves_cell(c, va, vb, "Off", "On", tool == "On", selected, false);
    } else if (r.cheat >= 0 && age_shown(r.cheat)) {
        halves_cell(c, va, vb, "Kid", "Adult", link_age.load(std::memory_order_relaxed) == 1, selected, false);
    } else if (r.cheat >= 0 && !tool.empty()) {
        choice_cell(c, va, vb, tool, selected, cheat_chooses(r.cheat), cheat_chooses(r.cheat));
    } else if (r.cheat >= 0 && *cheat_button_text(r.cheat)) {
        choice_cell(c, va, vb, cheat_button_text(r.cheat), selected, false, false, r.cheat == 9);
    } else if (r.tracker >= 0) {   // (a line of the Tracker tab: what the seed's file says, or the check it is stepped to)
        const bool steps = r.tracker == kTrackerShowRow ? tracker_check_count > 0 : r.tracker >= kTrackerFirstArea && tracker_row_checks(r.tracker) > 0;
        choice_cell(c, va, vb, tracker_says(r.tracker), selected, steps, steps);
    } else if (const FieldRow* f = field_row(r)) {
        text_cell(c, va, vb, *f->field, selected, editing == f->field, "None");
    } else if (!r.value) {
        if (!strcmp(r.name, "Test microphone"))
            choice_cell(c, va, vb, !host || !host->mic_test ? "Unavailable" : opts.mic == 0 ? "Microphone Off" : mic_testing ? "Stop test" : "Start test", selected, false, false);
        else if (pending == &r) choice_cell(c, va, vb, "Press again to confirm", selected, false, false);
        else if (is_share_row(r)) choice_cell(c, va, vb, share_value.empty() ? "Save" : share_value, selected, false, false);   // (an action, not a page)
        else if (&r == &rows[kBugReportRow]) choice_cell(c, va, vb, bug_report_cell(), selected, false, false);   // (how the last report went)
        else {
            choice_cell(c, va, vb, "", selected, false, false);
            ui::triangle(c, ImVec2(vb.x - 15 * s, mid), 10 * s, 1, selected ? ui::kGoldInk : ui::kInk);
        }
    } else {
        const bool fixed = row_fixed(r.value);
        const std::string lo = r.text(r.lo), hi = r.text(r.hi);
        const float half = (vb.x - va.x) * 0.5f - 18 * s;
        if (is_slider(r)) {
            slider_cell(c, va, vb, r.text(*r.value), menu_hit::slider_permille(*r.value, r.lo, r.hi), selected, t0, t1);
        } else if (r.hi - r.lo == r.step && !fixed && ui::size_of(c.f.strong, 18 * s, lo.c_str()).x <= half &&
                   ui::size_of(c.f.strong, 18 * s, hi.c_str()).x <= half) {
            halves_cell(c, va, vb, lo.c_str(), hi.c_str(), *r.value == r.hi, selected, fixed);
        } else {
            const bool output_row = r.value == &opts.output_res;
            const bool left = !fixed && (!output_row || step_output_choice(*r.value, -1) != *r.value) && (!stops_at_ends(r) || *r.value > r.lo);
            const bool right = !fixed && (!output_row || step_output_choice(*r.value, 1) != *r.value) && (!stops_at_ends(r) || *r.value < r.hi);
            choice_cell(c, va, vb, r.text(*r.value), selected, left, right, fixed);
        }
    }
}

void draw_options(ui::Ctx& c) {
    const float s = c.s, hh = banner_h(c);
    ui::banner(c, hh);
    // the tabs in the banner: dark ink on the tan, the shown one light on a dark inset; the tab keys at their ends (a click there
    // is the previous or the next tab)
    float tw[TAB_COUNT], total = 0;
    const int tabs = tabs_shown();
    for (int i = 0; i < tabs; i++) tw[i] = ui::size_of(c.f.heading, 23 * s, tab_titles[i]).x + 56 * s, total += tw[i];
    float x = (c.w - total) * 0.5f;
    const float ty = hh * 0.5f + s;
    const char* const keys[2] = {c.pad ? "L" : "Q", c.pad ? "R" : "E"};
    for (int i = 0; i < 2; i++) {
        const float cw = 26 * s, cx = i ? x + total + 22 * s : x - 22 * s - cw;
        const bool hover = hover_tab == TAB_COUNT + i;
        c.d->AddRectFilled(ImVec2(cx, ty - 13 * s), ImVec2(cx + cw, ty + 13 * s), hover ? ui::kTabInset : ui::kChip, 4 * s);
        ui::text_mid_centre(c, c.f.strong, 14 * s, cx + cw * 0.5f, ty, ui::kInk, keys[i]);
        hits.add(i ? cx - 10 * s : 0, 0, i ? c.w : cx + cw + 10 * s, hh, i ? menu_hit::kTabNext : menu_hit::kTabPrev, -1);
    }
    for (int i = 0; i < tabs; i++) {
        // (the Motion page: under Controls; the FPS counter details: under Gameplay)
        const bool shown = i == (cur_tab == TAB_MOTION ? TAB_CONTROLS : cur_tab == TAB_FPS_DEV ? TAB_GAMEPLAY : cur_tab);
        if (shown || i == hover_tab) {
            const ImU32 foot = shown ? ui::kTabInset : ui::alpha(ui::kTabInset, 0.45f), clear = ui::alpha(ui::kTabInset, 0);
            c.d->AddRectFilledMultiColor(ImVec2(x, 0), ImVec2(x + tw[i], hh), clear, clear, foot, foot);
            if (shown) c.d->AddRectFilled(ImVec2(x + 14 * s, hh - 4 * s), ImVec2(x + tw[i] - 14 * s, hh), ui::kAccent, 2 * s);   // (a cyan bar under it)
        }
        ui::text_mid(c, c.f.heading, 23 * s, x + 28 * s, ty, shown ? ui::kInkBright : ui::kSoft, tab_titles[i]);
        hits.add(x, 0, x + tw[i], hh, menu_hit::kTab, i);
        x += tw[i];
    }
    {   // (which build, at the banner's left, so a report can say it without opening the log; the release alone when the whole
        // line would run into the tabs)
        std::string ver = HOOKSHOT_VERSION;   // (Mako: "mako-3.3 (source ...)" shown as "Mako 3.3 (source ...)")
        ver = ver.rfind("mako-", 0) == 0 ? "Mako " + ver.substr(5) : "Mako " + ver;
        const float room = (c.w - total) * 0.5f - 60 * s - c.safe, px = 15 * s;
        const auto width = [&](float p) { return ui::size_of(c.f.body, p, ver.c_str()).x; };
        // (still too long, as a source build's "v2.0.11-821-g7b81752-dirty" since the Audio tab: at Small and Medium smaller
        // until it fits, on half-point steps, 10 points at the least; at Large, the size for a TV across the room, at its size
        // or not at all, as before)
        const float fit = ui::fit_px(px, opts.menu_size == 3 ? px : kVersionMinPt * s, 0.5f * s, room, width);
        if (fit > 0) ui::text_mid(c, c.f.body, fit, c.safe, ty, ui::kBannerInk, ver.c_str());
    }
    // the rows, in the column; the help beside it
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const int count = tab_row_count(cur_tab), sel = tab_selected[cur_tab];
    const Row& selr = rows[tab_row_to_global(cur_tab, sel)];
    const bool mic_help = mic_help_row(selr);
    const FieldRow* field = field_row(selr);   // (hookshot: a text field: why Enter did not take it, while it is edited)
    const char* hint = selr.value && selr.hint ? selr.hint(*selr.value, -1) : field && editing == field->field ? edit_why : nullptr;
    if (is_share_row(selr) && !share_said.empty()) hint = share_said.c_str();   // (what the last save did)
    if (&selr == &rows[kBugReportRow]) hint = bug_report_hint();   // (the Bug report: where it was saved, or why not)
    static std::string tracker_line;   // (a Tracker row stepped to a check: in logic, or what Link still needs)
    if (selr.tracker >= 0 && !(tracker_line = tracker_hint(selr.tracker)).empty()) hint = tracker_line.c_str();
    const std::string pending_line = (cur_tab == TAB_GRAPHICS || cur_tab == TAB_DEBUG) && restart_pending() ? restart_line(c, 16 * s, hx1 - hx0 - 66 * s) : "";
    static float help_tall = 0, help_tall_w = 0;
    static std::string help_said;   // (Save my pipeline list's line as measured: measured again when it changes)
    if (help_tall_w != hx1 - hx0 || help_said != share_said)
        help_tall_w = hx1 - hx0, help_said = share_said, help_tall = measure_help(c, hx1 - hx0 - 48 * s);
    // (a row that opens a page (Motion, Controls, Open debug tools): A or Enter opens it; Restart and Quit: A or Enter twice)
    const bool confirms = &selr == &rows[kRestartRow] || &selr == &rows[kQuitRow];
    ui::Prompt prompt_list[7] = {{ui::kUpDown, "Choose"}};
    int prompts_n = 1;
    const char* compact_key_name = opts.compact_menu_key == 1 ? "RCtrl" : "RShift";
    if (field && editing == field->field) {
        prompts_n = 0;
        prompt_list[prompts_n++] = {ui::kLeftRight, "Caret"};
        if (c.pad) {
            prompt_list[prompts_n++] = {ui::kUpDown, "Character"};
            prompt_list[prompts_n++] = {ui::kAddChar, "Add"};
            prompt_list[prompts_n++] = {ui::kRemoveChar, "Remove"};
        }
        prompt_list[prompts_n++] = {ui::kPaste, "Paste"};
        prompt_list[prompts_n++] = {ui::kConfirm, "Done"}, prompt_list[prompts_n++] = {ui::kBack, "Cancel"};
    } else if (selr.tracker >= 0) {   // (a line of the Tracker tab: its area's checks to step through, and the one shown to go to)
        if (selr.tracker >= kTrackerFirstArea && tracker_row_checks(selr.tracker)) prompt_list[prompts_n++] = {ui::kLeftRight, "Checks"};
        if (selr.tracker == kTrackerShowRow && tracker_check_count) prompt_list[prompts_n++] = {ui::kLeftRight, "Change"};
        if (!selr.tracker && tracker_check_count) prompt_list[prompts_n++] = {ui::kConfirm, "Forget"};   // (the whole game's row: the record forgotten)
        if (selr.tracker == kTrackerHomeRow && tracker_check_count) prompt_list[prompts_n++] = {ui::kConfirm, "Go home"};
        if (const TrackerCheck* k = tracker_pick[selr.tracker] ? tracker_row_check(selr.tracker, tracker_pick[selr.tracker]) : nullptr)   // (Y or J: tracker_junk)
            prompt_list[prompts_n++] = {ui::kExtra, tracker_junk[k - tracker_checks] ? "Not junk" : "Junk", "J"};
        if (tracker_pick[selr.tracker] && cheats_on()) prompt_list[prompts_n++] = {ui::kConfirm, "Go there"};
        prompt_list[prompts_n++] = {ui::kTabs, "Tabs"}, prompt_list[prompts_n++] = {ui::kBack, "Close"};
    } else {
        if (field) {
            prompt_list[prompts_n++] = {ui::kConfirm, "Edit"};
        } else if (selr.value || (selr.cheat >= 0 && (selr.cheat <= 1 || selr.cheat == 7 || cheat_chooses(selr.cheat) || age_shown(selr.cheat)))) {
            prompt_list[prompts_n++] = {ui::kLeftRight, "Change"};
            if (selr.cheat >= 0) if (const char* says = cheat_confirm(selr.cheat)) prompt_list[prompts_n++] = {ui::kConfirm, says};
            prompt_list[prompts_n++] = {ui::kCompact, "Compact", compact_key_name};
        } else if (selr.cheat >= 0) {
            if (const char* says = cheat_confirm(selr.cheat)) prompt_list[prompts_n++] = {ui::kConfirm, says};
            prompt_list[prompts_n++] = {ui::kCompact, "Compact", compact_key_name};
        } else {
            prompt_list[prompts_n++] = {ui::kConfirm, confirms ? (pending == &selr ? "Confirm" : selr.name) : &selr == &rows[kBugReportRow] || is_share_row(selr) ? "Save" : "Open"};
        }
        if (cur_tab == TAB_MOTION || cur_tab == TAB_FPS_DEV) prompt_list[prompts_n++] = {ui::kBack, "Back"};   // (Esc: to Controls, or Gameplay)
        else {
            prompt_list[prompts_n++] = {ui::kTabs, "Tabs"}, prompt_list[prompts_n++] = {ui::kBack, "Close"};
        }
    }
    const float bar_top = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    float bottom = std::min(c.h - c.safe, bar_top) - 10 * s;   // (the rows end above the prompts)
    const bool after = restart_changed(selr);
    // (the Tracker tab: an area's row shows its checks where the help is; the tab's second row has words of its own)
    const bool area_panel = selr.tracker >= kTrackerFirstArea && tracker_check_count > 0 && tracker_row_checks(selr.tracker, true) > 0;
    const char* row_help = selr.tracker == kTrackerShowRow && tracker_check_count ? kTrackerShowHelp :
                           selr.tracker == kTrackerHomeRow && tracker_check_count ? kTrackerHomeHelp : selr.help;
    if (narrow) {   // (help over the column's foot: normally half the room, up to 65% for the mic meter and its explanation)
        const float help_h = std::min(22 * s + 32 * s + help_tall + (after ? 30 * s : 0) + (pending_line.empty() ? 0 : 52 * s) + 22 * s,
                                      (bottom - hh) * (mic_help ? 0.65f : 0.5f));
        bottom = std::min(bar_top, c.h - c.safe) - help_h - 16 * s;
        if (area_panel) tracker_panel(c, hx0, hx1, bottom + 8 * s, bar_top - 10 * s, selr.tracker, hint);
        else help_box(c, hx0, hx1, bottom + 8 * s, selr.name, row_help, hint, pending_line.empty() ? nullptr : pending_line.c_str(), help_tall,
                      after, bottom + 8 * s, bar_top - 10 * s, mic_help);
    } else if (area_panel) {   // (an area's row of the Tracker tab: its checks, from under the banner down)
        tracker_panel(c, hx0, hx1, hh + 18 * s, bar_top - 12 * s, selr.tracker, hint);
    } else {
        help_box(c, hx0, hx1, std::max(hh + 26 * s, c.h * 0.30f), selr.name, row_help, hint,
                 pending_line.empty() ? nullptr : pending_line.c_str(), help_tall, after, hh + 18 * s, bar_top - 12 * s, mic_help);
    }
    const float rh = 40 * s, pitch = 48 * s, top = hh + 24 * s, rx0 = cx0 + 44 * s, rx1 = cx1 - 44 * s, split = rx0 + (rx1 - rx0) * 0.55f;
    if (cur_tab == TAB_DEBUG) {   // (the Debug tab: its own layout of the same rows)
        marquee_max = 0;
        draw_debug_rows(c, cx0, cx1, top, bottom, sel);
        ui::prompt_bar(c, prompt_list, prompts_n);
        return;
    }
    int shown = 0;
    const float first = scroll_rows(cur_tab, count, sel, top, bottom, pitch, &shown);
    scroll_bar(c, cx0 + 20 * s, top, top + shown * pitch - (pitch - rh), count, shown, first);
    marquee_max = 0;   // (set again below while the selected row's value is too long)
    c.d->PushClipRect(ImVec2(cx0, top - 8 * s), ImVec2(cx1, bottom + 8 * s));
    for (int i = 0; i < count; i++) {
        const float y = top + (i - first) * pitch;
        if (y + rh < top - 8 * s || y > bottom + 8 * s) continue;
        const Row& r = rows[tab_row_to_global(cur_tab, i)];
        if (r.heading) {   // (a section's title: gold, a rule after it to the column's end; no cell, nothing to click)
            const float ty = y + rh * 0.62f, tw = ui::size_of(c.f.heading, 19 * s, r.name).x;
            ui::text_mid(c, c.f.heading, 19 * s, rx0 + 2 * s, ty, ui::kGoldHi, r.name);
            c.d->AddLine(ImVec2(rx0 + tw + 16 * s, ty), ImVec2(rx1, ty), ui::alpha(ui::kEdge, 0.9f), std::max(1.0f, s));
            continue;
        }
        const bool selected = i == sel;
        name_cell(c, ImVec2(rx0, y), ImVec2(split, y + rh), r.name, selected, restart_changed(r));
        const ImVec2 va(split, y), vb(rx1, y + rh);
        float t0 = 0, t1 = 0;
        row_value_cell(c, r, va, vb, selected, &t0, &t1);
        hits.add(rx0, std::max(y, top - 8 * s), rx1, std::min(y + rh, bottom + 8 * s), menu_hit::kRow, i, va.x, vb.x, t0, t1);
    }
    c.d->PopClipRect();
    ui::prompt_bar(c, prompt_list, prompts_n);   // (the prompts, on top of the help and the rows)
}

/// The tuning bar: a compact TV-style picture settings bar docked at the bottom of the screen,
/// leaving 90% of the game scene visible so visual settings can be judged live.
void draw_tune_bar(ui::Ctx& c) {
    const float s = c.s;
    const int count = tab_row_count(cur_tab);
    int& sel = tab_selected[cur_tab];
    if (sel >= count) sel = count - 1;
    auto heading_at = [&](int k) { return rows[tab_row_to_global(cur_tab, k)].heading; };
    while (heading_at(sel)) sel = (sel + 1) % count;
    Row& r = rows[tab_row_to_global(cur_tab, sel)];

    const float bw = std::min(c.w - 2 * c.safe, 740 * s);
    const float bx0 = (c.w - bw) * 0.5f, bx1 = bx0 + bw;
    const float bh = 104 * s;
    const float by1 = c.h - c.safe - 16 * s;
    const float by0 = by1 - bh;

    // Dark panel with subtle edge
    c.d->AddRectFilled(ImVec2(bx0, by0), ImVec2(bx1, by1), ui::rgba(14, 10, 6, 235), 6 * s);
    c.d->AddRect(ImVec2(bx0, by0), ImVec2(bx1, by1), ui::alpha(ui::kEdge, 0.9f), 6 * s, std::max(1.0f, s));

    // Header strip inside card: Tab Name and restart status
    const char* cur_name = cur_tab == TAB_MOTION ? "Motion" : tab_title(cur_tab);
    if (cur_tab == TAB_FPS_DEV) cur_name = "FPS counter details";
    const float header_y = by0 + 13 * s;
    ui::text_mid(c, c.f.heading, 14 * s, bx0 + 16 * s, header_y, ui::kGoldHi, cur_name);

    char tab_hint[32];
    if (c.pad) snprintf(tab_hint, sizeof tab_hint, " (LB / RB)");
    else snprintf(tab_hint, sizeof tab_hint, " (Q / E)");
    const float thw = ui::size_of(c.f.heading, 14 * s, cur_name).x;
    ui::text_mid(c, c.f.body, 12 * s, bx0 + 16 * s + thw + 4 * s, header_y, ui::kDim, tab_hint);

    if (restart_changed(r)) {
        ui::diamond(c, ImVec2(bx1 - 20 * s, header_y), 4 * s, ui::kGoldHi);
        ui::text_mid_centre(c, c.f.body, 12 * s, bx1 - 68 * s, header_y, ui::kGoldHi, "Restart needed");
    }

    // Active Row widget: Name cell and Value cell
    const float ry0 = by0 + 26 * s, ry1 = ry0 + 38 * s;
    const float rx0 = bx0 + 14 * s, rx1 = bx1 - 14 * s;
    const float split = rx0 + (rx1 - rx0) * 0.46f;
    name_cell(c, ImVec2(rx0, ry0), ImVec2(split, ry1), r.name, true, restart_changed(r));

    const ImVec2 va(split, ry0), vb(rx1, ry1);
    float t0 = 0, t1 = 0;
    row_value_cell(c, r, va, vb, true, &t0, &t1);
    hits.add(rx0, ry0, rx1, ry1, menu_hit::kRow, sel, va.x, vb.x, t0, t1);

    // Prompts line
    const char* compact_key_name = opts.compact_menu_key == 1 ? "RCtrl" : "RShift";
    ui::Prompt tune_prompts[4] = {
        {ui::kUpDown, "Setting"},
        {ui::kLeftRight, "Adjust"},
        {ui::kCompact, "Full menu", compact_key_name},
        {ui::kBack, "Close"}
    };
    const bool confirms = &r == &rows[kRestartRow] || &r == &rows[kQuitRow];
    if (r.cheat >= 0 && cheat_confirm(r.cheat)) {
        tune_prompts[1] = {ui::kConfirm, cheat_confirm(r.cheat)};
    } else if (!r.value && r.cheat < 0) {
        tune_prompts[1] = {ui::kConfirm, confirms ? (pending == &r ? "Confirm" : r.name) : &r == &rows[kBugReportRow] || is_share_row(r) ? "Save" : "Open"};
    }
    const float pw = ui::prompts(c, ImVec2(0, 0), tune_prompts, 4, false);
    const float px0 = bx0 + (bw - pw) * 0.5f;
    ui::prompts(c, ImVec2(px0, by1 - 32 * s), tune_prompts, 4, true);
}

void draw_controls(ui::Ctx& c) {
    using enum menu_hit::CtlColumn;
    // (the page's own rows first, kTop of them (the layout preset, the button prompts), then a row per control and Reset to
    // defaults: one list, csel its selection)
    const float s = c.s, hh = title_banner(c, "Controls", nullptr);
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const int n = kTop + kControls + 1, sel_i = csel - kTop;   // (sel_i: the control's, kControls Reset; negative: a page row)
    const ui::Prompt idle[] = {{ui::kUpDown, "Choose"}, {ui::kLeftRight, "Column"}, {ui::kConfirm, "Bind"}, {ui::kKey, "Clear", "Del"},
                               {ui::kBack, "Back"}};
    const ui::Prompt option[] = {{ui::kUpDown, "Choose"}, {ui::kLeftRight, "Change"}, {ui::kBack, "Back"}};
    const ui::Prompt wait[] = {{ui::kBack, "Cancel"}};
    const float bar_top = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const Row* page_row = sel_i < 0 ? &rows[tab_row_to_global(TAB_PAGE, csel)] : nullptr;
    const char* title = page_row ? page_row->name : sel_i < kControls ? controls[sel_i].name : "Reset to defaults";
    const char* help = listening ? (listening == 1 ? "Press the gamepad button to use. Esc cancels." : "Press the key to use. Esc cancels.")
                       : page_row ? page_row->help
                       : sel_i < kControls && controls[sel_i].button < HOS_SW_N && controls[sel_i].button != HOS_SW_PLUS &&
                         controls[sel_i].button != HOS_SW_MINUS && ccol == kCtlToggle
                           ? "Hold-to-toggle: press once to hold this Switch button, again to release it. Either gamepad input or a "
                             "bound key works. Opening Insert, pressing Plus or Minus, focus loss or rebinding releases it. Off by default."
                           : "Either gamepad input or an assigned key presses the selected Switch button. Enter binds the "
                             "selected input and Delete clears it. A button's only gamepad input stays with it: it does not move into "
                             "another's empty Input 2. The game's button icons follow after a restart.";
    const char* hint = page_row ? (page_row->hint ? page_row->hint(*page_row->value, -1) : nullptr)
                                : "Gamepad: the D-pad moves, A binds, B goes back. Ocarina note keys are only notes while "
                                  "the ocarina waits for one; away from it they do their other jobs.";
    float bottom = std::min(c.h - c.safe, bar_top) - 10 * s;   // (the rows end above the prompts)
    if (narrow) {
        bottom = std::min(bar_top, c.h - c.safe) - 200 * s;
        help_box(c, hx0, hx1, bottom + 8 * s, nullptr, help, hint, nullptr, 0, page_row && restart_changed(*page_row), bottom + 8 * s,
                 bar_top - 10 * s);
    } else {
        help_box(c, hx0, hx1, std::max(hh + 26 * s, c.h * 0.30f), title, help, hint, nullptr, 0, page_row && restart_changed(*page_row),
                 hh + 18 * s, bar_top - 12 * s);
    }
    const float rx0 = cx0 + 44 * s, rx1 = cx1 - 44 * s, width = rx1 - rx0;
    const float pad_x = rx0 + width * 0.28f, key_x = rx0 + width * 0.64f, toggle_x = rx0 + width * 0.87f;
    const float col_x[] = {pad_x, (pad_x + key_x) * 0.5f, key_x, toggle_x, rx1};
    float top = hh + 22 * s;
    ui::text_mid_centre(c, c.f.body, 15 * s, col_x[kCtlAlternate], top + 8 * s, ui::kDim, "Gamepad");
    ui::text_mid(c, c.f.body, 15 * s, rx0 + 20 * s, top + 27 * s, ui::kDim, "Button");
    const char* titles[kCtlColumns] = {"Input 1", "Input 2", "Keyboard", "Toggle"};
    for (int col = kCtlPrimary; col < kCtlColumns; col++)
        ui::text_mid_centre(c, c.f.body, 15 * s, (col_x[col] + col_x[col + 1]) * 0.5f, top + 27 * s, ui::kDim, titles[col]);
    top += 43 * s;
    const float rh = 36 * s, pitch = 42 * s;
    int shown = 0;
    const float first = scroll_rows(kControlsSlot, n, csel, top, bottom, pitch, &shown);
    scroll_bar(c, cx0 + 20 * s, top, top + shown * pitch - (pitch - rh), n, shown, first);
    c.d->PushClipRect(ImVec2(cx0, top - 8 * s), ImVec2(cx1, bottom + 8 * s));
    for (int j = 0; j < n; j++) {
        const float y = top + (j - first) * pitch;
        if (y + rh < top - 8 * s || y > bottom + 8 * s) continue;
        const bool sel = j == csel;
        const int i = j - kTop;
        const float y0 = std::max(y, top - 8 * s), y1 = std::min(y + rh, bottom + 8 * s);
        if (i < 0) {   // (one of the page's own rows: a name and a choice, as on the tabs)
            const Row& r = rows[tab_row_to_global(TAB_PAGE, j)];
            // (their names wider than a control's, as wide as the tabs' rows': "Button prompts" whole at any size)
            const float opt_x = rx0 + (rx1 - rx0) * 0.5f;
            name_cell(c, ImVec2(rx0, y), ImVec2(opt_x, y + rh), r.name, sel, restart_changed(r), 17);
            choice_cell(c, ImVec2(opt_x, y), ImVec2(rx1, y + rh), r.text(*r.value), sel, *r.value > r.lo, *r.value < r.hi);
            hits.add(rx0, y0, rx1, y1, menu_hit::kCtlOption, j, opt_x, rx1);
            continue;
        }
        if (i == kControls) {
            ui::button(c, ImVec2(rx0, y), ImVec2(pad_x - 8 * s, y + rh), "Reset to defaults", sel);
            hits.add(rx0, y0, pad_x - 8 * s, y1, menu_hit::kCtlRow, i);
            continue;
        }
        const Control& ctl = controls[i];
        name_cell(c, ImVec2(rx0, y), ImVec2(pad_x, y + rh), ctl.name, sel, false, 17);
        hits.add(rx0, y0, pad_x, y1, menu_hit::kCtlRow, i);
        const bool keys = keys_only(i);
        for (int col = kCtlPrimary; col < kCtlColumns; col++) {
            const bool keyboard = col == kCtlKeyboard, toggle = col == kCtlToggle;
            const bool disabled = (keys && !keyboard) || (toggle && (ctl.button >= HOS_SW_N || ctl.button == HOS_SW_PLUS || ctl.button == HOS_SW_MINUS));
            const float a = col_x[col] + (col == kCtlPrimary ? 0 : 3 * s), b = col_x[col + 1] - (toggle ? 0 : 3 * s);
            const std::string v = disabled ? "-" : keyboard ? keys_text(ctl.button) : toggle
                ? tx_onoff((opts.hold_toggle >> ctl.button) & 1) : pad_name(host->binding(HOS_BIND_PAD, ctl.button, col));
            const bool here = sel && col == (keys ? kCtlKeyboard : ccol);
            const ImVec2 va(a, y), vb(b, y + rh);
            if (here && listening) {   // (waiting for the new input: amber, the outline as a selected value's)
                const float in = 4 * s;
                c.d->AddRectFilled(va, vb, ui::kCellDark);
                c.d->AddRect(va, vb, ui::kEdge, 0, std::max(1.0f, s));
                c.d->AddRectFilled(va + ImVec2(in, in), vb - ImVec2(in, in), ui::kListen);
                const std::string prompt = fit(c, c.f.strong, 16.5f * s, b - a - 2 * in, keyboard ? "Press key" : "Press button", false);
                ui::text_mid_centre(c, c.f.strong, 16.5f * s, (a + b) * 0.5f, y + rh * 0.5f, ui::kInkBright, prompt.c_str());
                ui::glow(c, va, vb);
            } else {
                choice_cell(c, va, vb, v, here, false, false, disabled);
            }
            if (!disabled) hits.add(a, y0, b, y1, menu_hit::kCtlCell, i, 0, 0, 0, 0, col);
        }
    }
    c.d->PopClipRect();
    (void)(listening ? ui::prompt_bar(c, wait, 1) : sel_i < 0 ? ui::prompt_bar(c, option, 3) : ui::prompt_bar(c, idle, 5));   // (the prompts, on top of the help and the rows)
}

/// A small square page arrow at a (its size side): dir 0 back, 1 on; dim when it cannot go that way
void page_arrow(ui::Ctx& c, ImVec2 a, float side, int dir, bool can) {
    const float s = c.s;
    const ImVec2 b = a + ImVec2(side, side);
    c.d->AddRectFilled(a, b, can ? ui::kCellName : ui::alpha(ui::kCellName, 0.4f), 3 * s);
    c.d->AddRect(a, b, can ? ui::kEdge : ui::alpha(ui::kEdge, 0.4f), 3 * s, std::max(1.0f, s));
    ui::triangle(c, (a + b) * 0.5f, 10 * s, dir, can ? ui::kInkBright : ui::kDim);
}

/// A tag at the right end of a card (its right edge x, its middle y): the text on an accent plate; its width
float card_tag(ui::Ctx& c, float x, float y, const char* tag, bool draw = true) {
    const float s = c.s, tw = ui::size_of(c.f.strong, 13 * s, tag).x + 14 * s;
    if (draw) {
        const ImVec2 g(x - tw, y - 10 * s);
        c.d->AddRectFilled(g, g + ImVec2(tw, 20 * s), ui::kAccent, 2 * s);
        ui::text_mid(c, c.f.strong, 13 * s, g.x + 7 * s, y, ui::kGoldInk, tag);
    }
    return tw;
}

void draw_inventory(ui::Ctx& c) {
    const float s = c.s;
    const int begin = inventory_begin(), end = inventory_end();
    bool loaded = false;   // (a save's counts reported: -1 for all until the game side has a save to read)
    for (int i = 0; i < kItems && !loaded; ++i) loaded = item_counts[i].load(std::memory_order_relaxed) >= 0;
    char count_text[48];
    snprintf(count_text, sizeof count_text, "%d items", end - begin);
    const float hh = title_banner(c, "Inventory", count_text);
    const int have = item_counts[item_choice].load(std::memory_order_relaxed);
    const char* edit = item_kinds[item_choice] ? (inventory_amount ? "Done" : "Edit amount") : (have ? "Relock" : "Unlock");
    ui::Prompt prompts[5] = {{ui::kUpDown, "Move"}, {ui::kLeftRight, inventory_amount ? "Amount" : "Move"}, {ui::kTabs, "Section"}};
    int prompts_n = 3;
    if (have >= 0) prompts[prompts_n++] = {ui::kConfirm, edit};
    prompts[prompts_n++] = {ui::kBack, inventory_amount ? "Done" : "Back"};
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const float bar = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const float left = cx0 + 24 * s, right = cx1 - 24 * s;
    const float gap = 10 * s;
    // the sections, as tabs over the grid (Q and E, or a click)
    // (on one line: their padding, then their text, made smaller as far as needed for the column's width)
    float tpx = 16 * s, tpad = 26 * s, tgap = 8 * s;
    auto tabs_w = [&] {
        float w = 0;
        for (int i = 0; i <= kItemSections; ++i) w += ui::size_of(c.f.strong, tpx, i ? item_sections.s[i - 1].name : "All").x + tpad + tgap;
        return w - tgap;
    };
    if (tabs_w() > right - left) tpad = 16 * s, tgap = 6 * s;
    if (const float w = tabs_w(); w > right - left) {
        const float text = w - (kItemSections + 1) * tpad - kItemSections * tgap;
        tpx = std::max(12 * s, tpx * (right - left - (w - text)) / text);
    }
    float x = left, y = hh + 18 * s;
    for (int i = 0; i <= kItemSections; ++i) {
        const char* label = i ? item_sections.s[i - 1].name : "All";
        const float w = ui::size_of(c.f.strong, tpx, label).x + tpad;
        if (x > left && x + w > right) x = left, y += 36 * s;
        const ImVec2 a(x, y), b(std::min(x + w, right), y + 30 * s);
        const bool active = i == inventory_filter;
        if (active) ui::gold(c, a, b);
        else c.d->AddRectFilled(a, b, ui::kCellName, 4 * s);
        c.d->AddRect(a, b, active ? ui::kGoldHi : ui::kEdge, 4 * s, std::max(1.0f, s));
        ui::text_mid_centre(c, c.f.strong, tpx, (a.x + b.x) * .5f, y + 15 * s, active ? ui::kGoldInk : ui::kInkBright, label);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kRow, i);
        x += w + tgap;
    }
    float top = y + 44 * s;
    const float pitch = (loaded ? 62 : 46) * s;   // (the title screen: the names alone, no line under them)
    if (!loaded) {   // (the title screen: one note for the page, not "Load a save" on every card)
        ui::diamond(c, ImVec2(left + 5 * s, top - 2 * s), 4 * s, ui::kGoldHi);
        ui::text_mid(c, c.f.body, 16 * s, left + 18 * s, top - 2 * s, ui::kSoft, "Load a save to edit the inventory.");
        top += 30 * s;
    }
    const float strip = 58 * s, detail = bar - 14 * s - strip, grid_bottom = std::max(top, detail - 8 * s);
    const char* help = have < 0 ? "Load a save to edit this item." : item_kinds[item_choice] ?
        "Choose Edit amount, then use Left and Right to change the quantity." : "Unlock or relock this item.";
    if (!narrow)
        help_box(c, hx0, hx1, std::max(hh + 26 * s, c.h * .30f), item_names[item_choice], help, nullptr, nullptr, 0, false,
                 hh + 18 * s, bar - 12 * s);
    // (as many columns as fit the longest name, at most 5; whole pages of cards, the range and the page under them)
    static float name_w = 0, name_s = 0;
    if (name_s != s) {
        name_s = s, name_w = 0;
        for (int i = 0; i < kItems; ++i) name_w = std::max(name_w, ui::size_of(c.f.strong, 15.5f * s, item_names[i]).x);
    }
    inventory_columns = std::clamp((int)((right - left + gap) / std::max(name_w + 26 * s + gap, 150 * s)), 1, 5);
    inventory_capacity = inventory_columns * std::max(1, (int)((grid_bottom - top + gap) / pitch));
    const int pages_n = std::max(1, (end - begin + inventory_capacity - 1) / inventory_capacity);
    inventory_page = std::clamp(inventory_page, 0, pages_n - 1);
    const int first = begin + inventory_page * inventory_capacity;
    const float width = (right - left + gap) / inventory_columns;
    c.d->PushClipRect(ImVec2(left - 12 * s, top - 12 * s), ImVec2(right + 12 * s, grid_bottom + 12 * s));
    for (int i = first; i < std::min(end, first + inventory_capacity); ++i) {
        const int cell = i - first;
        const ImVec2 a(left + (cell % inventory_columns) * width, top + (cell / inventory_columns) * pitch);
        const ImVec2 b(a.x + width - gap, a.y + pitch - gap);
        const int count = item_counts[i].load(std::memory_order_relaxed);
        const bool selected = i == item_choice, owned = count > 0, editing = selected && inventory_amount;
        c.d->AddRectFilled(a, b, owned ? ui::kCellNameSel : ui::kCellName, 4 * s);
        c.d->AddRect(a, b, owned ? ui::kAccent : ui::alpha(ui::kEdge, count < 0 ? 0.5f : 1.0f), 4 * s, std::max(1.0f, s));
        if (owned) c.d->AddRectFilled(a + ImVec2(0, 4 * s), ImVec2(a.x + 3 * s, b.y - 4 * s), ui::kAccent);
        c.d->PushClipRect(a + ImVec2(8 * s, 0), b - ImVec2(8 * s, 0), true);
        ui::text_mid(c, c.f.strong, 15.5f * s, a.x + 13 * s, loaded ? a.y + 17 * s : (a.y + b.y) * 0.5f, count < 0 ? ui::kDim : ui::kInkBright, item_names[i]);
        char amount[40];
        if (count < 0) snprintf(amount, sizeof amount, "%s", loaded ? "Unavailable" : "");
        else if (item_kinds[i]) snprintf(amount, sizeof amount, "Quantity %d", count);
        else snprintf(amount, sizeof amount, "%s", count ? "Unlocked" : "Locked");
        const float ly = a.y + 37 * s;
        if (editing) {   // (the amount being changed: its arrows, gold)
            ui::triangle(c, ImVec2(a.x + 18 * s, ly), 8 * s, 0, ui::kGoldHi);
            ui::text_mid(c, c.f.strong, 15 * s, a.x + 28 * s, ly, ui::kGoldHi, amount);
            ui::triangle(c, ImVec2(a.x + 38 * s + ui::size_of(c.f.strong, 15 * s, amount).x, ly), 8 * s, 1, ui::kGoldHi);
        } else {
            ui::text_mid(c, c.f.body, 15 * s, a.x + 13 * s, ly, owned ? ui::kAccent : ui::kDim, amount);
        }
        c.d->PopClipRect();
        if (selected) ui::glow(c, a, b);
        if (a.y < grid_bottom) hits.add(a.x, a.y, b.x, std::min(b.y, grid_bottom), menu_hit::kListLine, i);
    }
    c.d->PopClipRect();
    if (detail >= top) {   // (the page: its arrows, Page n of m and the range; the selected item's action at the right)
        c.d->AddLine(ImVec2(left, detail), ImVec2(right, detail), ui::alpha(ui::kEdge, 0.8f));
        const int pages = (end - begin + inventory_capacity - 1) / inventory_capacity, at = (first - begin) / inventory_capacity;
        const float my = detail + strip * 0.5f + 2 * s, side = 32 * s;
        float px0 = left;
        if (pages > 1) {
            page_arrow(c, ImVec2(px0, my - side * 0.5f), side, 0, at > 0);
            hits.add(px0, my - side * 0.5f, px0 + side, my + side * 0.5f, menu_hit::kButton, 2);
            char page_text[32];
            snprintf(page_text, sizeof page_text, "Page %d of %d", at + 1, pages);
            const float tw = ui::size_of(c.f.strong, 17 * s, page_text).x;
            ui::text_mid(c, c.f.strong, 17 * s, px0 + side + 12 * s, my, ui::kInkBright, page_text);
            const float nx = px0 + side + 24 * s + tw;
            page_arrow(c, ImVec2(nx, my - side * 0.5f), side, 1, at + 1 < pages);
            hits.add(nx, my - side * 0.5f, nx + side, my + side * 0.5f, menu_hit::kButton, 3);
            px0 = nx + side + 18 * s;
        }
        char range[64];
        snprintf(range, sizeof range, "%d–%d of %d", first - begin + 1, std::min(end, first + inventory_capacity) - begin, end - begin);
        ui::text_mid(c, c.f.body, 15 * s, px0, my, ui::kSoft, range);
        if (have >= 0) {
            const float bw = ui::size_of(c.f.strong, 18 * s, "Edit amount").x + 36 * s;
            const ImVec2 a(right - bw, my - 17 * s), b(right, my + 17 * s);
            ui::button(c, a, b, edit, false);
            hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 0);
            if (inventory_amount) {
                char amount[32];
                snprintf(amount, sizeof amount, "%d", have);
                const ImVec2 av(a.x - 118 * s, a.y), bv(a.x - 10 * s, b.y);
                choice_cell(c, av, bv, amount, true, true, true);
                hits.add(av.x, av.y, bv.x, bv.y, menu_hit::kButton, 1, av.x, bv.x);
            }
        }
    }
    ui::prompt_bar(c, prompts, prompts_n);   // (the prompts, on top of the help and the cards)
}

void draw_teleport(ui::Ctx& c) {
    const float s = c.s;
    char count[32];
    snprintf(count, sizeof count, "%d of %d", teleport_choice + 1, kTeleports);
    const float hh = title_banner(c, "Teleport", count);
    float cx0, cx1, hx0, hx1;
    bool narrow;
    columns(c, &cx0, &cx1, &hx0, &hx1, &narrow);
    column(c, cx0, cx1, hh);
    const ui::Prompt prompts[] = {{ui::kUpDown, "Move"}, {ui::kLeftRight, "Move"}, {ui::kTabs, "Section"},
        {ui::kConfirm, "Travel"}, {ui::kBack, "Back"}};
    const float bar = ui::prompt_bar_top(c);   // (the strip itself drawn last, over all: below)
    const float left = cx0 + 24 * s, right = cx1 - 24 * s, top = hh + 16 * s;
    const float strip = 58 * s, detail = bar - 14 * s - strip;
    const float bottom = std::max(top, detail - 6 * s), gap = 10 * s, pitch = 48 * s, head = 40 * s;
    const char* const note = teleport_notes[teleport_choice];
    if (!narrow)
        help_box(c, hx0, hx1, std::max(hh + 26 * s, c.h * .30f), teleport_names[teleport_choice],
                 "Select a destination, then Travel (or Enter) to go to its map entrance. Link keeps his current age.", note, nullptr, 0,
                 false, hh + 18 * s, bar - 12 * s);
    // (as many columns as fit the longest name and its tag, at most 4; each section under its heading, the cards scrolled to
    // keep the selected one in view)
    static float card_w = 0, card_s = 0;
    if (card_s != s) {
        card_s = s, card_w = 0;
        for (int i = 0; i < kTeleports; ++i)
            card_w = std::max(card_w, ui::size_of(c.f.body, 17 * s, teleport_names[i]).x +
                                          (teleport_notes[i] ? card_tag(c, 0, 0, teleport_notes[i], false) + 12 * s : 0));
    }
    teleport_columns = std::clamp((int)((right - left + gap) / (card_w + 36 * s + gap)), 1, 4);
    const int cols = teleport_columns;
    const float width = (right - left + gap) / cols;
    // (the y of each section's heading and first row, from the top of the list)
    float section_y[kTeleportSections + 1];
    float total = 0;
    for (int k = 0; k < kTeleportSections; ++k) {
        section_y[k] = total;
        const int n = teleport_section_end(k) - teleport_sections[k].first;
        total += head + (n + cols - 1) / cols * pitch + (k + 1 < kTeleportSections ? 10 * s : 0);
    }
    section_y[kTeleportSections] = total;
    auto card_y = [&](int i) {
        const int k = teleport_section_of(i);
        return section_y[k] + head + (i - teleport_sections[k].first) / cols * pitch;
    };
    const float view = bottom - top;
    teleport_page_rows = std::max(1, (int)(view / pitch) - 1);
    float& at = teleport_scroll_px;
    float& want = teleport_want_px;
    if (teleport_wheel) want -= teleport_wheel * pitch, teleport_wheel = 0;   // (the wheel: the cards move, the choice stays)
    if (total <= view) want = 0;
    else if (!teleport_follow) want = std::clamp(want, 0.0f, total - view);
    else {
        const int k = teleport_section_of(teleport_choice);
        const bool first_row = teleport_choice - teleport_sections[k].first < cols;
        const float y0 = first_row ? section_y[k] : card_y(teleport_choice) - pitch * 0.5f, y1 = card_y(teleport_choice) + pitch * 1.5f;
        if (y0 < want) want = y0;
        if (y1 > want + view) want = y1 - view;
        want = std::clamp(want, 0.0f, total - view);
    }
    at += (want - at) * ease_step;
    if (std::fabs(want - at) < 0.5f) at = want;
    if (total > view) scroll_bar(c, cx0 + 12 * s, top, bottom, (int)total, (int)view, at);
    c.d->PushClipRect(ImVec2(left - 12 * s, top), ImVec2(right + 12 * s, bottom), true);
    for (int k = 0; k < kTeleportSections; ++k) {
        const float hy = top + section_y[k] - at + head * 0.5f;
        if (hy > bottom + head || hy < top - head) continue;
        ui::text_mid(c, c.f.heading, 20 * s, left, hy, ui::kInkBright, teleport_sections[k].name);
        const float tw = ui::size_of(c.f.heading, 20 * s, teleport_sections[k].name).x;
        char n_text[16];
        snprintf(n_text, sizeof n_text, "%d", teleport_section_end(k) - teleport_sections[k].first);
        const float nw = ui::size_of(c.f.body, 15 * s, n_text).x;
        ui::text_mid(c, c.f.body, 15 * s, right - nw, hy, ui::kSoft, n_text);
        c.d->AddLine(ImVec2(left + tw + 14 * s, hy + s), ImVec2(right - nw - 12 * s, hy + s), ui::alpha(ui::kAccent, 0.45f),
                     std::max(1.0f, s));
    }
    for (int i = 0; i < kTeleports; ++i) {
        const int k = teleport_section_of(i), cell = i - teleport_sections[k].first;
        const ImVec2 a(left + cell % cols * width, top + card_y(i) - at);
        const ImVec2 b(a.x + width - gap, a.y + pitch - 8 * s);
        if (b.y < top || a.y > bottom) continue;
        const bool selected = i == teleport_choice;
        c.d->AddRectFilled(a, b, selected ? ui::kCellNameSel : ui::kCellName, 3 * s);
        c.d->AddRect(a, b, ui::kEdge, 3 * s, std::max(1.0f, s));
        if (selected) c.d->AddRectFilled(a, ImVec2(a.x + 4 * s, b.y), ui::kGoldHi);
        float name_end = b.x - 10 * s;
        if (teleport_notes[i]) name_end -= card_tag(c, b.x - 8 * s, (a.y + b.y) * 0.5f, teleport_notes[i]) + 8 * s;
        c.d->PushClipRect(a, ImVec2(name_end, b.y), true);
        ui::text_mid(c, selected ? c.f.strong : c.f.body, 17 * s, a.x + 16 * s, (a.y + b.y) * 0.5f, selected ? ui::kInkBright : ui::kInk,
                     teleport_names[i]);
        c.d->PopClipRect();
        if (selected) ui::glow(c, a, b);
        hits.add(a.x, std::max(a.y, top), b.x, std::min(b.y, bottom), menu_hit::kListLine, i);
    }
    c.d->PopClipRect();
    if (detail >= top) {   // (the selection, its section and note, and Travel: what Enter does)
        c.d->AddLine(ImVec2(left, detail), ImVec2(right, detail), ui::alpha(ui::kEdge, 0.8f));
        const float my = detail + strip * 0.5f + 2 * s;
        const float bw = ui::size_of(c.f.strong, 20 * s, "Travel").x + 56 * s;
        const ImVec2 a(right - bw, my - 18 * s), b(right, my + 18 * s);
        c.d->PushClipRect(ImVec2(left, detail), ImVec2(a.x - 12 * s, detail + strip), true);
        ui::text_mid(c, c.f.strong, 18 * s, left, my - 10 * s, ui::kInkBright, teleport_names[teleport_choice]);
        char where[64];
        snprintf(where, sizeof where, note ? "%s · %s" : "%s", teleport_sections[teleport_section_of(teleport_choice)].name, note);
        ui::text_mid(c, c.f.body, 15 * s, left, my + 12 * s, ui::kAccent, where);
        c.d->PopClipRect();
        ui::button(c, a, b, "Travel", false);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 0);
    }
    ui::prompt_bar(c, prompts, 5);   // (the prompts, on top of the help and the cards)
}

void draw_quick_debug(ui::Ctx& c) {
    const float s = c.s, width = std::min(1040 * s, c.w - 2 * c.safe);
    const float left = (c.w - width) * .5f, right = left + width;
    const float top = std::max(c.safe, c.h * .10f), bottom = std::min(c.h - c.safe, top + 540 * s);
    c.d->AddRectFilled(ImVec2(left, top), ImVec2(right, bottom), ui::kCellDark);
    c.d->AddRect(ImVec2(left, top), ImVec2(right, bottom), ui::kEdge);
    ui::text_mid(c, c.f.heading, 23 * s, left + 24 * s, top + 25 * s, ui::kGoldHi, "Debug Tools");
    draw_debug_rows(c, left, right, top + 52 * s, bottom - 12 * s, tab_selected[TAB_DEBUG]);
    const ui::Prompt prompts[] = {{ui::kUpDown, "Choose"}, {ui::kLeftRight, "Change"},
        {ui::kConfirm, "Select"}, {ui::kBack, "Close"}};
    ui::prompt_bar(c, prompts, 4);
}

void draw_debug_warning(ui::Ctx& c) {
    const float s = c.s, width = std::min(600 * s, c.w - 2 * c.safe), height = 234 * s;
    const ImVec2 a((c.w - width) * .5f, (c.h - height) * .5f), b = a + ImVec2(width, height);
    c.d->AddRectFilled(a, b, ui::kCellDark);
    c.d->AddRect(a, b, ui::kEdge, 0, 2 * s);
    c.d->AddRectFilled(a, ImVec2(b.x, a.y + 48 * s), ui::kBanner);
    ui::text_mid_centre(c, c.f.heading, 23 * s, (a.x + b.x) * .5f, a.y + 24 * s, ui::kBannerInk, "Enable Debug Tools?");
    ui::para(c, c.f.body, 18 * s, a + ImVec2(24 * s, 62 * s), ui::kInk,
             "Debug tools can change your progress. Use a backup save. Enabling Debug tools turns off autosave. "
             "You can turn it back on in the Debug tab.", width - 48 * s);
    const char* labels[] = {"Cancel", "Enable Debug Tools"};
    const float button_w = (width - 60 * s) / 2;
    for (int i = 0; i < 2; ++i) {
        const ImVec2 p(a.x + 24 * s + i * (button_w + 12 * s), b.y - 66 * s);
        const ImVec2 q = p + ImVec2(button_w, 42 * s);
        ui::button(c, p, q, labels[i], i == debug_warning_choice);
        hits.add(p.x, p.y, q.x, q.y, menu_hit::kButton, i);
    }
}

void draw_ask(ui::Ctx& c) {
    const float s = c.s, W = 560 * s, H = 232 * s;
    const ImVec2 p((c.w - W) * 0.5f, (c.h - H) * 0.5f), q = p + ImVec2(W, H);
    ui::shadow(c, p, q, 30 * s, 1.0f, 8 * s);
    const float hb = 50 * s, rr = ui::kRound * 1.5f * s;   // (a navy title strip, as the banner, a cyan line under it)
    c.d->AddRectFilled(p, q, ui::kBox, rr);
    c.d->AddRectFilled(p, ImVec2(q.x, p.y + hb), ui::kBannerTop, rr, ImDrawFlags_RoundCornersTop);
    c.d->AddRectFilled(ImVec2(p.x + 24 * s, p.y + hb - 2 * s), ImVec2(q.x - 24 * s, p.y + hb), ui::kAccent, s);
    c.d->AddRect(p, q, ui::kBoxEdge, rr, 0, 1.5f * s);
    ui::text_mid_centre(c, c.f.heading, 23 * s, (p.x + q.x) * 0.5f, p.y + hb * 0.5f, ui::kBannerInk, "Restart Needed");
    const std::string ask = i18n::tr("Restart to apply ") + restart_list(i18n::tr(" and ")) + "?";
    ui::para(c, c.f.body, 19 * s, ImVec2(p.x + 28 * s, p.y + 64 * s), ui::kInk, ask.c_str(), W - 56 * s);
    ui::text_mid(c, c.f.body, 16 * s, p.x + 28 * s, p.y + 124 * s, ui::kSoft, "Progress since your last save is lost.");
    const float bw = 210 * s, bh = 46 * s, gap = 24 * s, by = p.y + 160 * s, x0 = (p.x + q.x) * 0.5f - bw - gap * 0.5f;
    const char* labels[2] = {"Later", "Restart Now"};
    for (int i = 0; i < 2; i++) {
        const ImVec2 a(x0 + i * (bw + gap), by), b = a + ImVec2(bw, bh);
        ui::button(c, a, b, labels[i], i == ask_sel);
        hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, i);
    }
    const ui::Prompt prompt_list[] = {{ui::kLeftRight, "Choose"}, {ui::kConfirm, "Confirm"}, {ui::kBack, "Later"}};
    ui::prompt_bar(c, prompt_list, 3);
}

/// (Mako) Master Quest preview: the end of what is made. The host sets MAKO_MQ_PREVIEW_END=1 in the process's environment when
/// the Kokiri Emerald's scene starts (host/prompts.c); the menu then stays open on this page, black, its one button back to the
/// launcher
bool preview_end = false;
bool preview_end_asked() {
    static int64_t next = 0;
    const int64_t now = prof_now();
    if (now < next) return false;
    next = now + 250000000;   // (a look every quarter second)
    char v[8];
    return GetEnvironmentVariableA("MAKO_MQ_PREVIEW_END", v, sizeof v) > 0 && v[0] == '1';
}
void back_to_launcher() {   // (Mako Launcher.exe beside the game, then the window closes as the player would close it)
    char path[MAX_PATH];
    DWORD n = GetModuleFileNameA(nullptr, path, MAX_PATH);
    while (n > 0 && path[n - 1] != '\\' && path[n - 1] != '/') n--;
    if (n > 1 && n + 20 < MAX_PATH) {
        path[n - 1] = 0;   // (the game's folder)
        char cmd[MAX_PATH + 24];
        snprintf(cmd, sizeof cmd, "\"%s\\Mako Launcher.exe\"", path);
        STARTUPINFOA si{};
        si.cb = sizeof si;
        PROCESS_INFORMATION pi{};
        if (CreateProcessA(nullptr, cmd, nullptr, nullptr, FALSE, 0, nullptr, path, &si, &pi)) {
            CloseHandle(pi.hThread), CloseHandle(pi.hProcess);
            logf("menu: master quest preview over: back to the launcher");
        } else logf("menu: master quest preview over: the launcher could not start (%lu)", GetLastError());
    }
    if (const HWND window = app_window()) PostMessageA(window, WM_CLOSE, 0, 0);
}
void draw_preview_end(ui::Ctx& c) {
    const float s = c.s, mid = c.w * 0.5f;
    ui::text_mid_centre(c, c.f.heading, 34 * s, mid, c.h * 0.40f, ui::kInkBright, "More coming.");
    ui::text_mid_centre(c, c.f.body, 22 * s, mid, c.h * 0.40f + 48 * s, ui::kSoft, "Thanks for playing the Master Quest preview!");
    const float bw = 300 * s, bh = 50 * s;
    const ImVec2 a(mid - bw * 0.5f, c.h * 0.40f + 110 * s), b = a + ImVec2(bw, bh);
    ui::button(c, a, b, "Back to Launcher", true);
    hits.add(a.x, a.y, b.x, b.y, menu_hit::kButton, 0);
    const ui::Prompt prompt_list[] = {{ui::kConfirm, "Back to Launcher"}};
    ui::prompt_bar(c, prompt_list, 1);
}

void draw_menu(ui::Ctx& c);
/// The menu's text sizes at this window's unit, baked ahead by vk_imgui.cpp a few a frame: the first open then draws with no
/// glyphs to make (it took 2.6 ms at 1080p)
float prebaked[2] = {0, 0};   // (the unit and the width prebake last did)
/// The menu's unit now for a window w x h: whether prebake has not done it yet
bool prebake_needed(uint32_t w, uint32_t h) {
    float m = 0;
    return ui::unit((float)h, opts.menu_size, &m) != prebaked[0] || (float)w != prebaked[1];
}
void prebake(const ui::Ctx& c) {
    if (c.s == prebaked[0] && c.w == prebaked[1]) return;
    prebaked[0] = c.s, prebaked[1] = c.w;
    static const float points[] = {12, 12.5f, 13, 13.6f, 14, 14.28f, 14.5f, 15, 15.5f, 16, 16.5f, 17, 18, 18.5f, 19, 20, 21, 23, 24};
    constexpr int n = sizeof points / sizeof points[0];
    float px[n];
    for (int i = 0; i < n; i++) px[i] = points[i] * c.s;
    ui::prebake(px, n);
    if (open_now.load(std::memory_order_relaxed)) return;
    // (and the page itself drawn once into a list of its own, thrown away: what the first open would measure and bake (the
    // help's height over every row, the exact sizes) done now, the menu's state as it was)
    const menu_hit::Map saved_hits = hits;
    const int saved_marquee = marquee_max;
    const int saved_tele[2] = {teleport_columns, teleport_page_rows}, saved_inv[3] = {inventory_columns, inventory_capacity, inventory_page};
    const float saved_tele_px[2] = {teleport_scroll_px, teleport_want_px};
    const float saved_ease = ease_step;
    float saved_scroll[sizeof scroll_at / sizeof *scroll_at], saved_want[sizeof scroll_at / sizeof *scroll_at];
    int saved_to[sizeof scroll_at / sizeof *scroll_at];   // (the scratch drawing's scroll, given back: the next is the menu's)
    memcpy(saved_scroll, scroll_at, sizeof scroll_at);
    memcpy(saved_want, scroll_want, sizeof scroll_want);
    memcpy(saved_to, scrolled_to, sizeof scrolled_to);
    ImDrawList scratch(ImGui::GetDrawListSharedData());
    scratch._ResetForNewFrame();
    scratch.PushTexture(ImGui::GetIO().Fonts->TexRef);
    scratch.PushClipRectFullScreen();
    ease_step = 0;
    {
        ui::Ctx dry = c;
        dry.d = &scratch;
        draw_menu(dry);
    }
    hits = saved_hits, marquee_max = saved_marquee, ease_step = saved_ease;
    teleport_columns = saved_tele[0], teleport_page_rows = saved_tele[1], teleport_scroll_px = saved_tele_px[0], teleport_want_px = saved_tele_px[1];
    inventory_columns = saved_inv[0], inventory_capacity = saved_inv[1], inventory_page = saved_inv[2];
    memcpy(scroll_at, saved_scroll, sizeof scroll_at);
    memcpy(scroll_want, saved_want, sizeof scroll_want);
    memcpy(scrolled_to, saved_to, sizeof scrolled_to);
}

float menu_ox = 0;   // (the menu's column's left edge in the window: more than 0 only on a window wider than 16:9)
/// The menu: the game dimmed across the whole window, the pages in a column as wide as a 16:9 screen of this height, in the
/// middle (a window of 16:9 or narrower: the whole of it). The pages draw from 0 as on 16:9; their vertices and clip
/// rectangles are moved over after, and menu_tick moves the mouse back by menu_ox before it tests the hits
void draw_menu(ui::Ctx& c) {
    if (!(tune_mode && page == 0)) c.d->AddRectFilled(ImVec2(0, 0), ImVec2(c.w, c.h), ui::rgba(2, 5, 12, ui::kDimAlpha));   // (the game behind, dimmed; Mako's colour)
    ui::Ctx k = c;
    k.w = std::min(c.w, std::floor(c.h * 16.0f / 9.0f + 0.5f));
    menu_ox = std::floor((c.w - k.w) * 0.5f);
    const int vtx0 = c.d->VtxBuffer.Size, cmd0 = c.d->CmdBuffer.Size;
    hits.clear(0, 0, k.w, k.h);
    if (page == 6) c.d->AddRectFilled(ImVec2(0, 0), ImVec2(c.w, c.h), ui::rgba(0, 0, 0, 255));   // (Mako: the preview's end, black)
    if (page == 6) draw_preview_end(k);
    if (debug_warning) draw_debug_warning(k);
    else if (page == 5) draw_ask(k);
    else if (page == 1) draw_controls(k);
    else if (page == 3) draw_teleport(k);
    else if (page == 4) draw_inventory(k);
    else if (quick_debug && cur_tab == TAB_DEBUG) draw_quick_debug(k);
    else if (tune_mode) draw_tune_bar(k);
    else draw_options(k);
    if (menu_ox <= 0) return;
    for (int i = vtx0; i < c.d->VtxBuffer.Size; i++) c.d->VtxBuffer[i].pos.x += menu_ox;
    // (a clip rectangle of the column's: moved with it; the whole window's (the dim's, and the draw list's own) stays, as it
    // holds the column wherever it is)
    for (int i = std::max(0, cmd0 - 1); i < c.d->CmdBuffer.Size; i++) {
        ImVec4& r = c.d->CmdBuffer[i].ClipRect;
        if (r.x <= 0 && r.z >= c.w) continue;
        r.x += menu_ox, r.z += menu_ox;
    }
    // (the draw list's current header, for whatever is drawn next: the window's again after the pages' pops)
}

/// Text with a dark outline (each side, one step of the scale), as the counter always had: readable over any scene
void outlined_right(ui::Ctx& c, ImFont* font, float px, float right, float top, ImU32 col, const char* t) {
    const float x = right - ui::size_of(font, px, t).x, o = std::max(1.0f, c.s);
    for (int dy = -1; dy <= 1; dy++)
        for (int dx = -1; dx <= 1; dx++)
            if (dx || dy) c.d->AddText(font, px, ImVec2(x + dx * o, top + dy * o), ui::rgba(0, 0, 0, 230), t);
    c.d->AddText(font, px, ImVec2(x, top), col, t);
}

/// (the FPS counter's lines past the number) Text with a soft shadow: a thin dark outline, lighter than the number's, and a
/// darker copy a step down, so it reads over sand and sky as over a dungeon. Digits on even steps (tabular: the widest
/// digit's advance), so a changing value does not shift
struct Tab {
    ImFont* font;
    float px, digit;
    Tab(ImFont* f, float size) : font(f), px(size), digit(0) {
        char d[2] = {0, 0};
        for (char k = '0'; k <= '9'; k++) d[0] = k, digit = std::max(digit, ui::size_of(f, size, d).x);
    }
    static bool dig(char c) { return c >= '0' && c <= '9'; }
    /// Each piece of t: a digit alone (in its even cell), or a run of what is not one (drawn whole). fn(begin, end, x, width)
    template <class Fn>
    float pieces(const char* t, float x, Fn fn) const {
        const float x0 = x;
        for (const char* q = t; *q;) {
            const char* e = q + 1;
            if (!dig(*q))
                while (*e && !dig(*e)) e++;
            const float w = dig(*q) ? digit : font->CalcTextSizeA(px, FLT_MAX, 0, q, e).x;
            fn(q, e, x, w);
            x += w, q = e;
        }
        return x - x0;
    }
    float width(const char* t) const { return pieces(t, 0, [](const char*, const char*, float, float) {}); }
    /// Each piece five times under itself (a faint copy at each diagonal step, a darker one a step down) and once in col: a
    /// dozen strings make a few hundred quads' worth of glyphs, not a glyph each ten times
    void draw(ImDrawList* d, float x, float y, ImU32 col, const char* t, float s) const {
        const float o = std::max(1.0f, s);
        const int a = std::max(200, (int)((col >> IM_COL32_A_SHIFT) & 0xff));
        const ImU32 shade = ui::rgba(0, 0, 0, a * 210 / 255), faint = ui::rgba(0, 0, 0, a * 160 / 255);
        pieces(t, x, [&](const char* q, const char* e, float px0, float w) {
            if (*q == ' ' && e == q + 1) return;
            const float gx = px0 + (dig(*q) ? (w - font->CalcTextSizeA(px, FLT_MAX, 0, q, e).x) * 0.5f : 0);
            static const float dx[4] = {-1, 1, -1, 1}, dy[4] = {-1, -1, 1, 1};
            for (int k = 0; k < 4; k++) d->AddText(font, px, ImVec2(gx + dx[k] * o * 0.8f, y + dy[k] * o * 0.8f), faint, q, e);
            d->AddText(font, px, ImVec2(gx, y + o), shade, q, e);
            d->AddText(font, px, ImVec2(gx, y), col, q, e);
        });
    }
};

/// The processor's name without its marks, clock and core count: "Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz" is "Intel Core
/// i7-8700K", "AMD Ryzen 5 5600X 6-Core Processor" is "AMD Ryzen 5 5600X"
static std::string hardware_cpu_name(std::string t) {
    for (const char* mark : {"(R)", "(TM)", "(tm)"})
        for (size_t at; (at = t.find(mark)) != std::string::npos;) t.erase(at, strlen(mark));
    if (const size_t at = t.find(" @ "); at != std::string::npos) t.erase(at);
    while (!t.empty() && t.back() == ' ') t.pop_back();
    const auto drop_end = [&](const char* w) {
        const size_t n = strlen(w);
        if (t.size() > n && t.compare(t.size() - n, n, w) == 0) t.erase(t.size() - n);
    };
    drop_end(" Processor");
    drop_end(" CPU");
    if (const size_t sp = t.rfind(' '); sp != std::string::npos && t.size() > 5 && t.compare(t.size() - 5, 5, "-Core") == 0) t.erase(sp);
    std::string out;
    for (char ch : t)
        if (ch != ' ' || (!out.empty() && out.back() != ' ')) out += ch;
    while (!out.empty() && out.back() == ' ') out.pop_back();
    return out;
}

/// The GPU's name without its marks and the driver's note in brackets at its end, which the driver line says:
/// "AMD Radeon RX 6750 XT (RADV NAVI22)" is "AMD Radeon RX 6750 XT", "Intel(R) Arc(tm) A770 Graphics (DG2)" "Intel Arc A770 Graphics"
static std::string hardware_gpu_name(std::string t) {
    for (const char* mark : {"(R)", "(TM)", "(tm)"})
        for (size_t at; (at = t.find(mark)) != std::string::npos;) t.erase(at, strlen(mark));
    while (!t.empty() && t.back() == ' ') t.pop_back();
    if (const size_t open = t.rfind(" ("); open != std::string::npos && open > 0 && !t.empty() && t.back() == ')') t.erase(open);
    return t;
}

static_assert(sizeof opts.fps_dev_show / sizeof *opts.fps_dev_show == fps_stats::kDevLines + 1,
              "a details page toggle for each Dev line and the CPU and GPU lines");

/// The FPS counter's scale (pixels per point): the menu's with Auto; else a fixed one, Small, Medium and Large the counter's
/// size in a 720p, 1080p and 1440p window at the Medium menu size, at most what Auto gives at the Large menu size
float fps_scale(const ui::Ctx& c) {
    if (opts.fps_size < 1 || opts.fps_size > 3) return c.s;
    static const float fixed[] = {1.0f, 1.5f, 2.0f};
    return std::min(fixed[opts.fps_size - 1], c.h / 720.0f * 1.3f);
}

/// The FPS counter, in the corner the FPS counter position row chooses (the safe area's; under the banner at the top right
/// while the menu is open, unless it fits beside the menu's column on a very wide window). The number as it always looked:
/// green outlined bold, "FPS" small beside it, the frame generation line under them, no plate (#1957, v2.0.14's paint_fps).
/// Past FPS (the row's levels, fps_stats.h), a tidy column under it, aligned to the same edge, with the same soft-shadowed
/// text and no plate either: the frame time (green, amber or red against the cap's) and the 1% low; the graph of the last
/// 4 s, a thin line over a soft fill, one column a frame span with its slowest frame (a stutter never falls between two), a
/// faint dashed line at the cap's frame time, red ticks over frames past twice it; the Breakdown, where the time goes
/// stacked in the graph's columns, its legend with the values, the GPU's time and the stutters' causes (their columns get a
/// red tick too). Dev adds the renderer's own numbers, and at the foot the version, the CPU, GPU and driver.
void draw_fps(ui::Ctx& c, bool under_banner) {
    namespace fs = fps_stats;
    int level = fs::level_of(opts.show_fps);
    const float s = fps_scale(c), big = 28 * s, small = 13 * s, label = 12 * s;
    const ImU32 green = ui::rgba(72, 255, 110), ink = ui::kInkBright, dim = ui::kSoft, soft = ui::kInk;
    const Tab num(c.f.strong, big), tab(c.f.strong, small), lab(c.f.strong, label);
    const float nw = num.width(fps_text), lw = ui::size_of(c.f.strong, small, "FPS").x;
    const float sw = fps_sub[0] ? tab.width(fps_sub) : 0;
    const float gw = (fs::level_of(opts.show_fps) >= fs::kBreakdown ? 280 : 208) * s;   // (the column's width from the graph on; wider with the lanes)
    // (while the menu is open: the top right under the banner, the number and the frame time only, unless the window is so much
    // wider than 16:9 that the column fits beside the menu's, in its own corner)
    const bool beside = menu_ox >= (level >= fs::kGraph ? gw : nw + lw) + 2 * c.safe + 8 * s;
    int corner = std::clamp(opts.fps_corner, 0, 3);
    if (under_banner && !tune_mode && !beside) corner = 0, level = std::min(level, (int)fs::kFrameTime);
    const bool left = corner & 1, bottom = corner >= 2;
    // (the column's height, to anchor it at the bottom)
    const float row = 17 * s, gh = 50 * s, lh = 16 * s;
    float h = 32 * s + (fps_sub[0] ? row : 0);
    if (level >= fs::kFrameTime && fps_ms_text[0]) h += row;
    if (level >= fs::kGraph) h += 8 * s + gh + 4 * s;
    const bool rt_lane = fps_render_thread_on();   // (no render thread, threaded rendering off: no lane, no legend section)
    if (level >= fs::kBreakdown) h += (rt_lane ? 36 * s + 6 * lh : 0) + 10 * s + 11 * lh + 12 * s;   // (the render lane, the legend's rows)
    // (the Dev lines the details page leaves on, laid out by their width: VRAM on a row of its own, the rest two to a row while the
    // name and the value fit in half the column, a row of their own when not ("2089, 3.9 GB"). A line that went wide stays wide
    // until it fits with room to spare: its value changes every half second, and it would jump between the two)
    struct DevRow { int a, b; };   // (b: the right half's line; -1 a row of its own, -2 the left half alone)
    static DevRow dev_layout[fs::kDevLines];
    static bool dev_wide[fs::kDevLines];
    int dev_shown = 0, dev_rows = 0;
    if (level >= fs::kDev) {
        const float room = gw * 0.5f - 8 * s;
        int pending = -1;
        for (int i = 0; i < fs::kDevLines; i++) dev_shown += opts.fps_dev_show[i] != 0;
        if (opts.fps_dev_show[fs::kVram]) dev_layout[dev_rows++] = {fs::kVram, -1};
        for (int g : fs::kDevGrid) {
            if (!opts.fps_dev_show[g]) continue;
            const float need = lab.width(fs::dev_short(g)) + tab.width(fps_dev_text[g]) + 8 * s;
            dev_wide[g] = need > room || (dev_wide[g] && need > room * 0.85f);
            if (dev_wide[g]) dev_layout[dev_rows++] = {g, -1};
            else if (pending < 0) pending = g;
            else dev_layout[dev_rows++] = {pending, g}, pending = -1;
        }
        if (pending >= 0) dev_layout[dev_rows++] = {pending, -2};
    }
    if (level >= fs::kDev && dev_shown) h += 6 * s + dev_rows * lh;
    // (the footer, under everything: the version, the CPU, the GPU and its driver, what the counter ran on: at Dev, or at every
    // level with Version and hardware at every level; the CPU and GPU lines row turns the last three off)
    const bool footer = level >= fs::kDev || opts.fps_version_always;
    const bool hw_lines = footer && opts.fps_dev_show[fs::kDevLines];
    const int foot = (footer ? 1 : 0) + (hw_lines ? 3 : 0);
    if (foot) h += 6 * s + foot * lh;
    const float edge = left ? c.safe : c.w - c.safe;
    const float top = bottom ? c.h - c.safe - h : under_banner && !tune_mode && page != 5 && !beside ? banner_h(c) + 10 * s : c.safe;
    // (x for a width at the column's edge)
    const auto at = [&](float w) { return left ? edge : edge - w; };
    // (the number's colour: at FPS the classic green whatever the rate, the counter as it always was (#1957); from Frame time on
    // green at the cap's rate, amber under it, red under two thirds of it, as the frame time beside it)
    const double target = fps_target_ms();   // (0: none, Uncapped: the colours against the console's 60, no line)
    const ImU32 grade_col[3] = {green, ui::rgba(255, 200, 60), ui::rgba(255, 95, 80)};
    const ImU32 num_col = level >= fs::kFrameTime && fps_rate_now > 0 ? grade_col[fs::rate_grade(fps_rate_now, target)] : green;
    {   // (the number and "FPS", as they always looked: outlined, the number's digits on even steps)
        const float x = at(nw + 4 * s + lw), o = std::max(1.0f, s);
        for (int dy = -1; dy <= 1; dy++)
            for (int dx = -1; dx <= 1; dx++)
                if (dx || dy) {
                    float gx = x;
                    char one[2] = {0, 0};
                    for (const char* q = fps_text; *q; q++) {
                        one[0] = *q;
                        const float adv = ui::size_of(c.f.strong, big, one).x;
                        c.d->AddText(c.f.strong, big, ImVec2(gx + (num.digit - adv) * 0.5f + dx * o, top + dy * o), ui::rgba(0, 0, 0, 230), one);
                        gx += num.digit;
                    }
                    c.d->AddText(c.f.strong, small, ImVec2(x + nw + 4 * s + dx * o, top + 14 * s + dy * o), ui::rgba(0, 0, 0, 230), "FPS");
                }
        float gx = x;
        char one[2] = {0, 0};
        for (const char* q = fps_text; *q; q++) {
            one[0] = *q;
            const float adv = ui::size_of(c.f.strong, big, one).x;
            c.d->AddText(c.f.strong, big, ImVec2(gx + (num.digit - adv) * 0.5f, top), num_col, one);
            gx += num.digit;
        }
        c.d->AddText(c.f.strong, small, ImVec2(x + nw + 4 * s, top + 14 * s), num_col, "FPS");
    }
    float y = top + 32 * s;
    if (fps_sub[0]) tab.draw(c.d, at(sw), y, soft, fps_sub, s), y += row;
    if (level >= fs::kFrameTime && fps_ms_text[0]) {   // ("16.7 ms" coloured by its distance from the cap's frame time, "1% low 20.1 ms" beside it)
        const ImU32 ms_col = grade_col[fps_ms_now > 0 ? fs::rate_grade(1000.0 / fps_ms_now, target) : 0];
        const float mw = tab.width(fps_ms_text), gap = 10 * s, low_w = tab.width(fps_low_text);
        const float x = at(mw + gap + low_w);
        tab.draw(c.d, x, y, ms_col, fps_ms_text, s);
        tab.draw(c.d, x + mw + gap, y, soft, fps_low_text, s);
        y += row;
    }
    if (foot) {   // (the footer, at the column's foot: the version, as the banner says it; at Dev the CPU, the GPU, its driver. A line
        // too long for the column's width loses its end)
        static std::string cpu, gpu, drv, fit[4];
        static const std::string ver = std::string("Hookshot ") + version_text(HOOKSHOT_VERSION);
        static float fit_w = 0;
        if (gpu.empty()) cpu = hardware_cpu_name(bug_report::cpu_name()), gpu = hardware_gpu_name(device_name_text()), drv = driver_text(), fit_w = 0;
        if (fit_w != gw) {
            fit_w = gw;
            const auto shorten = [&](std::string t, float room) {
                if (lab.width(t.c_str()) <= room) return t;
                while (!t.empty() && lab.width((t + "...").c_str()) > room) {
                    t.pop_back();
                    while (!t.empty() && ((unsigned char)t.back() & 0xC0) == 0x80) t.pop_back();
                }
                while (!t.empty() && t.back() == ' ') t.pop_back();
                return t + "...";
            };
            fit[0] = shorten(ver, gw);
            fit[1] = shorten(cpu.empty() ? "-" : cpu, gw);
            fit[2] = shorten(gpu.empty() ? "-" : gpu, gw);
            fit[3] = shorten(drv.empty() ? "-" : drv, gw);
        }
        float fy = top + h - foot * lh;
        for (int i = 0; i < foot; i++) lab.draw(c.d, at(lab.width(fit[i].c_str())), fy + 1 * s, soft, fit[i].c_str(), s), fy += lh;
    }
    if (level < fs::kGraph) return;
    // (the graph)
    constexpr int kCols = 64;   // (wider columns, the lanes' parts readable)
    static fs::Frame col[kCols];
    static bool mark[kCols];
    // (the columns from the ring at most 60 times a second: at the cap Uncapped's 1000 fps, 4 s of frames each present cost
    // more than the drawing; a 4 s graph moves a column every 40 ms)
    static double topms = 0, scroll = 0;
    static int64_t graph_at = 0;
    if (const int64_t now = fps_clock(); now - graph_at >= fs::kSecond / 60 || now < graph_at) {
        graph_at = now;
        (void)fps_graph(now, kCols, col, mark, &scroll);   // (fixed slots, scrolled by how far into the newest one now is)
        static float ms[kCols];   // (the scale from the usual frame, not the slowest: a spike past the top is drawn at it, and marked)
        int k = 0;
        for (int i = 0; i < kCols; i++)
            if (col[i].ms > 0) ms[k++] = col[i].ms;
        // (up at once, down slowly, so the whole graph does not rescale with each frame that scrolls out: 0.5% a 60th of a second,
        // whatever the frame rate the counter is drawn at)
        const double want = fs::graph_top(target, fs::typical_ms(ms, k));
        static int64_t decayed_at = 0;
        const double ticks = decayed_at && now > decayed_at ? std::min(60.0, (now - decayed_at) / (fs::kSecond / 60.0)) : 1.0;
        decayed_at = now;
        topms = want >= topms ? want : std::max(want, topms * std::pow(0.995, ticks));
    }
    const bool parts = level >= fs::kBreakdown;
    const float x0 = at(gw), x1 = x0 + gw, gy0 = y + 8 * s, gy1 = gy0 + gh;
    const float cw = gw / kCols, py = (float)(gh / topms);
    const float thin = std::max(1.0f, 1.75f * s);
    const ImU32 line_col = ui::rgba(130, 240, 150), fill_top = ui::rgba(120, 225, 140, 80), fill_bot = ui::rgba(120, 225, 140, 0);
    // (the floor: a faint line; the cap's frame time: a dashed one, its value at the inner end. The dashes are drawn last, over
    // the columns and the line, with a dark line under them: in view over any part's colour)
    c.d->AddLine(ImVec2(x0, std::floor(gy1) + 0.5f), ImVec2(x1, std::floor(gy1) + 0.5f), ui::rgba(255, 255, 255, 60), std::max(1.0f, s));
    const auto cap_line = [&](float ty) {
        const float dash = 4 * s, gap = 3 * s, w = std::max(1.0f, 1.25f * s);
        c.d->AddLine(ImVec2(x0, ty + w), ImVec2(x1, ty + w), ui::rgba(0, 0, 0, 140), w);
        for (float x = x0; x < x1; x += dash + gap)
            c.d->AddLine(ImVec2(x, ty), ImVec2(std::min(x + dash, x1), ty), ui::rgba(255, 255, 255, 230), w);
    };
    const float cap_y = target > 0 ? std::floor(gy1 - (float)target * py) + 0.5f : -1;   // (Uncapped without V-Sync: no line)
    {
        // (the scale's two values outside the graph, on its inner side: the cap's frame time at its line, the top at the top)
        char t[16];
        if (target > 0) {
            const float ty = cap_y;
            snprintf(t, sizeof t, "%.1f", target);
            lab.draw(c.d, left ? x1 + 5 * s : x0 - 5 * s - lab.width(t), ty - label * 0.55f, ui::rgba(235, 235, 235), t, s);
        }
        snprintf(t, sizeof t, topms < 10 ? "%.1f" : "%.0f", topms);
        lab.draw(c.d, left ? x1 + 5 * s : x0 - 5 * s - lab.width(t), gy0 - label * 0.55f, ui::rgba(200, 200, 200), t, s);
    }
    // (the soft fill: a column each, fading down; then the line over it, broken where a column had no frame, a faint dark line
    // under it for the bright scenes. with the Breakdown, each column its frame's parts stacked instead of the fill, and
    // with a render thread a lane under the graph on the same time axis, the render thread's frame)
    static ImVec2 pts[kCols];
    const auto yv = [&](float ms) { return std::max(gy0, gy1 - ms * py); };
    const auto cx_of = [&](int i) { return x0 + (i + 0.5f - (float)scroll) * cw; };   // (scrolled smoothly)
    // (the parts' colours, one meaning in every lane: blue the game's work, red the waits for the GPU, purple the render thread,
    // grey the pacing and idle; the lighter shade of a family its smaller part)
    static const ImU32 part_col[fs::kParts] = {ui::rgba(96, 160, 232), ui::rgba(160, 200, 245), ui::rgba(246, 150, 130),
                                                ui::rgba(120, 120, 120), ui::rgba(168, 132, 230), ui::rgba(232, 72, 60),
                                                ui::rgba(56, 108, 196)};
    static const char* const names[fs::kParts] = {"Game", "Renderer", "GPU present", "Pacing", "Render thread", "GPU fence",
                                                  "Game's main thread"};
    static const bool part_waits[fs::kParts] = {false, false, true, false, true, true, true};   // (under the legend's "Waiting on")
    static const int order[fs::kParts] = {fs::kGame, fs::kRender, fs::kWaitMain, fs::kWaitRender, fs::kWaitGpu, fs::kGpuWait,
                                          fs::kPace};
    static const ImU32 rt_col[fs::kRtParts] = {ui::rgba(168, 132, 230), ui::rgba(210, 190, 245), ui::rgba(232, 72, 60),
                                                ui::rgba(110, 110, 110)};
    static const char* const rt_names[fs::kRtParts] = {"Recording", "Workers", "GPU slot", "Idle"};
    const auto alpha = [](ImU32 c, int a) { return (c & 0x00FFFFFF) | ((ImU32)a << 24); };
    c.d->PushClipRect(ImVec2(x0, gy0 - 8 * s), ImVec2(x1, gy1 + 1), true);
    if (parts)
        for (int i = 0; i < kCols; i++) {
            if (col[i].ms <= 0) continue;
            const float l = cx_of(i) - cw * 0.5f + 0.5f, r = l + cw - 0.5f;   // (a hairline between columns)
            float yb = gy1;
            for (int o = 0; o < fs::kParts && yb > gy0; o++) {
                const float hgt = col[i].part[order[o]] * py;
                if (hgt <= 0) continue;
                const float yt = std::max(gy0, yb - hgt);
                c.d->AddRectFilled(ImVec2(l, yt), ImVec2(r, yb), alpha(part_col[order[o]], 190));
                yb = yt;
            }
        }
    // (the columns with a frame, joined across those without: a slow stretch has fewer frames than columns)
    int n = 0;
    for (int i = 0; i < kCols; i++)
        if (col[i].ms > 0) pts[n++] = ImVec2(cx_of(i), yv(col[i].ms));
    if (n >= 2 && !parts) {   // (the fill: a quad under each segment, its colour at the line fading to nothing at the floor)
        const ImVec2 uv = ImGui::GetFontTexUvWhitePixel();
        c.d->PrimReserve((n - 1) * 6, (n - 1) * 4);
        for (int k = 0; k + 1 < n; k++) {
            const ImDrawIdx i0 = (ImDrawIdx)c.d->_VtxCurrentIdx;
            c.d->PrimWriteVtx(pts[k], uv, fill_top);
            c.d->PrimWriteVtx(pts[k + 1], uv, fill_top);
            c.d->PrimWriteVtx(ImVec2(pts[k + 1].x, gy1), uv, fill_bot);
            c.d->PrimWriteVtx(ImVec2(pts[k].x, gy1), uv, fill_bot);
            c.d->PrimWriteIdx(i0), c.d->PrimWriteIdx((ImDrawIdx)(i0 + 1)), c.d->PrimWriteIdx((ImDrawIdx)(i0 + 2));
            c.d->PrimWriteIdx(i0), c.d->PrimWriteIdx((ImDrawIdx)(i0 + 2)), c.d->PrimWriteIdx((ImDrawIdx)(i0 + 3));
        }
    }
    if (n == 1) pts[n++] = ImVec2(pts[0].x + 1, pts[0].y);
    if (n >= 2) {
        static ImVec2 under[kCols];
        for (int k = 0; k < n; k++) under[k] = ImVec2(pts[k].x, pts[k].y + std::max(1.0f, s));
        c.d->AddPolyline(under, n, ui::rgba(0, 0, 0, 150), ImDrawFlags_None, thin + std::max(1.0f, s));
        c.d->AddPolyline(pts, n, line_col, ImDrawFlags_None, thin);
    }
    if (cap_y > gy0) cap_line(cap_y);
    // (red ticks: spikes, frames past twice the cap's and half again the graph's usual (a steady slow stretch is not a row of
    // them), and with the Breakdown the frames that built shaders or left draws out. A frame's tick is decided once, the first
    // time a column shows it, and kept while it scrolls by: decided again at every drawing from the columns on screen, a frame
    // near the line went on and off as others scrolled in and out and the scale settled)
    float usual = 0;
    {
        int k = 0;
        for (int i = 0; i < kCols; i++)
            if (col[i].ms > 0) usual += col[i].ms, k++;
        usual = k ? usual / k : 0;
    }
    static std::unordered_map<int64_t, bool> spike_of;   // (a frame's at_ns: its tick)
    if (spike_of.size() > 4 * kCols) {   // (the frames past the window's left end)
        int64_t oldest = INT64_MAX;
        for (int i = 0; i < kCols; i++)
            if (col[i].ms > 0) oldest = std::min(oldest, col[i].at_ns);
        for (auto it = spike_of.begin(); it != spike_of.end();) it = it->first < oldest ? spike_of.erase(it) : std::next(it);
    }
    for (int i = 0; i < kCols; i++) {
        if (col[i].ms <= 0) continue;
        auto [it, fresh] = spike_of.try_emplace(col[i].at_ns, false);
        if (fresh)   // (no target: past half again the usual)
            it->second = (col[i].ms > 2 * target && col[i].ms > 1.5f * usual) || col[i].ms > topms;
        if (it->second || (parts && mark[i])) {
            const float cx = cx_of(i);
            c.d->AddCircleFilled(ImVec2(cx, gy0 - 3 * s), 2.2f * s, ui::rgba(0, 0, 0, 120));
            c.d->AddCircleFilled(ImVec2(cx, gy0 - 3 * s), 1.6f * s, ui::rgba(240, 100, 85));
        }
    }
    c.d->PopClipRect();
    if (!parts) return;
    // (hookshot) the render thread's lane: its frame in ms on the frame graph's scale (its own height), the work and the waits
    // stacked and idle left empty, so a column's height is what the render thread spent of the frame; the cap's line and the
    // top's value beside it, as the frame graph's
    const float lane_gap = 6 * s, rh = rt_lane ? 30 * s : 0;
    const float ry0 = gy1 + (rt_lane ? lane_gap : 0), ry1 = ry0 + rh, rpy = (float)(rh / topms);
    if (rt_lane) {
        const auto scale_label = [&](const char* t, float ty, ImU32 col_) {
            lab.draw(c.d, left ? x1 + 5 * s : x0 - 5 * s - lab.width(t), ty - label * 0.55f, col_, t, s);
        };
        c.d->AddLine(ImVec2(x0, std::floor(ry1) + 0.5f), ImVec2(x1, std::floor(ry1) + 0.5f), ui::rgba(255, 255, 255, 60), std::max(1.0f, s));
        {
            char t[16];
            if (target > 0) {
                const float ty = std::floor(ry1 - (float)target * rpy) + 0.5f;
                snprintf(t, sizeof t, "%.1f", target);
                scale_label(t, ty, ui::rgba(235, 235, 235));
            }
            snprintf(t, sizeof t, topms < 10 ? "%.1f" : "%.0f", topms);
            scale_label(t, ry0, ui::rgba(200, 200, 200));
        }
        c.d->PushClipRect(ImVec2(x0, ry0), ImVec2(x1, ry1 + 1), true);
        for (int i = 0; i < kCols && fps_rt_on; i++) {
            if (col[i].ms <= 0) continue;
            const float l = cx_of(i) - cw * 0.5f + 0.5f, r = l + cw - 0.5f;
            float yb = ry1;
            for (int k = 0; k < fs::kRtParts && yb > ry0; k++) {
                if (k == fs::kRtIdle) continue;   // (idle: the space above)
                const float hgt = col[i].rt[k] * rpy;
                if (hgt <= 0) continue;
                const float yt = std::max(ry0, yb - hgt);
                c.d->AddRectFilled(ImVec2(l, yt), ImVec2(r, yb), alpha(rt_col[k], 190));
                yb = yt;
            }
        }
        if (target > 0) {   // (over the lane's columns, as the frame graph's)
            const float ty = std::floor(ry1 - (float)target * rpy) + 0.5f;
            if (ty > ry0) cap_line(ty);
        }
        c.d->PopClipRect();
    }
    // (the legend: the frame's parts first, adding up to the frame time shown under the number, then the render thread's to the same
    // span on its own clock, the GPU's beside them; the render thread and the GPU run in parallel with the frame, not after it.
    // The waits under a "Waiting on" sub-heading of their own, which has no value)
    float by = ry1 + 10 * s;
    const float half_w = gw * 0.5f;
    const auto swatch = [&](float sx, ImU32 col) {
        c.d->AddRectFilled(ImVec2(sx, by + lh * 0.5f - 3 * s), ImVec2(sx + 6 * s, by + lh * 0.5f + 3 * s), col, 1.5f * s);
    };
    const auto cell = [&](int column, ImU32 dot, bool indent, const char* name, const char* value, ImU32 value_col) {
        const float cx0 = column < 0 ? x0 : x0 + column * half_w, cx1 = column < 0 ? x1 : cx0 + half_w - (column ? 0 : 8 * s);   // (-1: the whole width)
        float nx = cx0 + (indent ? 10 * s : 0);   // (indent: a part under "Waiting on")
        if (dot) swatch(nx, dot), nx += 10 * s;
        lab.draw(c.d, nx, by + 1 * s, soft, name, s);
        tab.draw(c.d, cx1 - tab.width(value), by, value_col, value, s);
    };
    const auto header = [&](const char* t, const char* value, ImU32 value_col) {
        lab.draw(c.d, x0, by + 1 * s, ui::rgba(255, 255, 255, 200), t, s);
        if (value) tab.draw(c.d, x1 - tab.width(value), by, value_col, value, s);
        by += lh;
    };
    // (a sub-heading over the waits, without a value of its own: the values in the column are the parts, and they add up)
    const auto waiting_on = [&] {
        lab.draw(c.d, x0, by + 1 * s, soft, "Waiting on", s);
        by += lh;
    };
    for (int o = 0; o < fs::kParts; o++) {   // (the work first, then the waits under their sub-heading, then the pacing)
        if (part_waits[order[o]] && (o == 0 || !part_waits[order[o - 1]])) waiting_on();
        cell(-1, part_col[order[o]], part_waits[order[o]], names[order[o]], fps_part_text[order[o]], ink);
        by += lh;
    }
    if (rt_lane) {
        header("Render thread", "in parallel", dim);
        for (int k = 0; k < fs::kRtParts; k++) {
            const bool waits = k == fs::kRtWorkers || k == fs::kRtGpu;
            if (k == fs::kRtWorkers) waiting_on();
            cell(-1, rt_col[k], waits, rt_names[k], fps_rt_text[k], ink);
            by += lh;
        }
    }
    header("GPU", "in parallel", dim);
    {
        char busy[48];
        snprintf(busy, sizeof busy, "%s  %s", fps_gpu_text, fps_gpu_busy_text);
        cell(-1, 0, false, "GPU time", busy, ink);
        by += lh;
    }
    c.d->AddLine(ImVec2(x0, std::floor(by + 3 * s) + 0.5f), ImVec2(x1, std::floor(by + 3 * s) + 0.5f), ui::rgba(255, 255, 255, 40), std::max(1.0f, s));
    by += 6 * s;
    const ImU32 red = ui::rgba(240, 100, 85);
    cell(0, 0, false, "Shaders built (4 s)", fps_built_text, strcmp(fps_built_text, "0") ? red : dim);
    cell(1, 0, false, "Draws left out (4 s)", fps_left_text, strcmp(fps_left_text, "0") ? red : dim);
    by += lh;
    if (level < fs::kDev || !dev_shown) return;
    // (Dev: the renderer's own numbers, for debugging; those the details page leaves on)
    c.d->AddLine(ImVec2(x0, std::floor(by + 3 * s) + 0.5f), ImVec2(x1, std::floor(by + 3 * s) + 0.5f), ui::rgba(255, 255, 255, 40), std::max(1.0f, s));
    by += 6 * s;
    const auto dev_cell = [&](int column, int i) {
        const bool alarm = (i == fs::kVram && fps_vram_over) || (i == fs::kSkipped && strcmp(fps_dev_text[i], "0") && strcmp(fps_dev_text[i], "-"));
        cell(column, 0, false, fs::dev_short(i), fps_dev_text[i], alarm ? red : ink);
    };
    for (int r = 0; r < dev_rows; r++) {   // (as laid out with the column's height, above)
        const DevRow& d = dev_layout[r];
        dev_cell(d.b == -1 ? -1 : 0, d.a);
        if (d.b >= 0) dev_cell(1, d.b);
        by += lh;
    }
}

/// (Mako) The performance monitor (perf_monitor.cpp, by Ducky) as 3.0.2 drew it: perf_monitor_paint's red plates (GDI,
/// black keyed out), 260 x 212 at the window's whole scale (height / 720), at (12, 260) times that scale
std::atomic<bool> perf_new{true};
void draw_perf(ui::Ctx& c) {
    static ImTextureData* tex = nullptr;
    static int drawn_scale = 0;
    const int scale = std::max(1, (int)c.h / 720);
    const uint32_t w = perf_monitor_width(scale), h = perf_monitor_height(scale);
    if (perf_new.exchange(false) || drawn_scale != scale || !tex) {
        drawn_scale = scale;
        BITMAPINFO bi{};
        bi.bmiHeader.biSize = sizeof bi.bmiHeader;
        bi.bmiHeader.biWidth = (LONG)w;
        bi.bmiHeader.biHeight = -(LONG)h;
        bi.bmiHeader.biPlanes = 1;
        bi.bmiHeader.biBitCount = 32;
        bi.bmiHeader.biCompression = BI_RGB;
        HDC dc = CreateCompatibleDC(nullptr);
        void* bits = nullptr;
        HBITMAP bmp = dc ? CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, nullptr, 0) : nullptr;
        if (!bmp) {
            if (dc) DeleteDC(dc);
            return;
        }
        HGDIOBJ old = SelectObject(dc, bmp);
        perf_monitor_paint(dc, w, h, scale);
        GdiFlush();
        static std::vector<uint8_t> rgba;
        rgba.resize((size_t)w * h * 4);
        const uint8_t* src = (const uint8_t*)bits;
        for (size_t i = 0; i < (size_t)w * h; i++) {   // (BGRX to RGBA; black is see-through, as 3.0.2 keyed it)
            const uint8_t bl = src[i * 4], g = src[i * 4 + 1], r = src[i * 4 + 2];
            rgba[i * 4] = r, rgba[i * 4 + 1] = g, rgba[i * 4 + 2] = bl, rgba[i * 4 + 3] = (r | g | bl) ? 255 : 0;
        }
        SelectObject(dc, old);
        DeleteObject(bmp);
        DeleteDC(dc);
        tex = ui::picture(tex, (int)w, (int)h, rgba.data());
    }
    const float x = 12.0f * scale, y = 260.0f * scale;
    c.d->AddImage(tex->GetTexRef(), ImVec2(x, y), ImVec2(x + w, y + h));
}

/// The start-up screen: the logo, the wordmark, what the start is doing, a bar, on a warm dark. A little below the middle; what
/// is under the logo at 0.86 of the logo's scale. startup_fade, 0 to 1, darkens it all to black as it ends
void draw_startup(ui::Ctx& c) {
    StartupView v;
    {
        std::lock_guard lk(startup_mu);
        v = startup;
    }
    const float s = c.s, w = c.w, h = c.h, cx = w * 0.5f, k = s * 0.86f;   // (k: the scale of what is under the logo)
    c.d->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), ui::rgba(5, 9, 18));
    const float lh = 112 * s, top = h * 0.5f - 176 * s;
    for (int i = 40; i >= 1; i--) c.d->AddCircleFilled(ImVec2(cx, top + lh * 0.5f + 70 * s), h * 0.021f * i, ui::rgba(20, 60, 120, 4), 128);
    float aspect = 1;
    ImTextureData* logo = ui::logo(&aspect);
    if (logo) c.d->AddImage(logo->GetTexRef(), ImVec2(cx - lh * aspect * 0.5f, top), ImVec2(cx + lh * aspect * 0.5f, top + lh));
    float y = top + lh + 16 * s;
    ui::spaced(c, c.f.heading, 42 * k, ImVec2(cx, y), ui::kInkBright, "MAKO", 14 * k);
    {   // (a thin cyan line under the wordmark, fading at its ends)
        const float ly = y + 66 * k, t = std::max(1.0f, 1.5f * k);
        const ImU32 a0 = ui::alpha(ui::kAccent, 0);
        c.d->AddRectFilledMultiColor(ImVec2(cx - 150 * k, ly), ImVec2(cx, ly + t), a0, ui::kAccent, ui::kAccent, a0);
        c.d->AddRectFilledMultiColor(ImVec2(cx, ly), ImVec2(cx + 150 * k, ly + t), ui::kAccent, a0, a0, ui::kAccent);
    }
    ui::text_centre(c, c.f.body, 14.5f * k, ImVec2(cx, y + 78 * k), ui::kDim, v.version.c_str());
    if (!v.title.empty()) {
        y += 120 * k;
        if (!v.step.empty()) {   // ("STEP 2 OF 2" as "Step 2 of 2")
            std::string step = v.step;
            for (size_t i = 1; i < step.size(); i++) step[i] = (char)tolower((unsigned char)step[i]);
            ui::text_centre(c, c.f.body, 15 * k, ImVec2(cx, y), ui::kAccent, step.c_str());
        }
        ui::text_centre(c, c.f.heading, 24 * k, ImVec2(cx, y + 20 * k), ui::kInk, v.title.c_str());
        const float x0 = cx - 270 * k, x1 = cx + 270 * k, by = y + 64 * k;
        float under = by;
        if (v.fraction >= 0) {   // (the bar as a value cell: a dark cell, gold inside, the percentage on it)
            const float bh = 26 * k, in = 4 * k, fx = x0 + in + (x1 - x0 - 2 * in) * (float)std::min(v.fraction, 1.0);
            c.d->AddRectFilled(ImVec2(x0, by), ImVec2(x1, by + bh), ui::kCellDark, ui::kRound * k);
            c.d->AddRect(ImVec2(x0, by), ImVec2(x1, by + bh), ui::kEdge, ui::kRound * k, 0, std::max(1.0f, s));
            if (fx > x0 + in) ui::gold(c, ImVec2(x0 + in, by + in), ImVec2(fx, by + bh - in));
            // (the percentage in the middle of the whole bar, drawn twice: dark ink where the gold is under it, light where the
            // empty bar is, each clipped to its part, so every letter keeps its contrast as the edge passes through it)
            const float split = std::max(fx, x0 + in);
            c.d->PushClipRect(ImVec2(x0, by), ImVec2(split, by + bh), true);
            ui::text_mid_centre(c, c.f.strong, 15 * k, cx, by + bh * 0.5f, ui::kGoldInk, v.pct.c_str());
            c.d->PopClipRect();
            c.d->PushClipRect(ImVec2(split, by), ImVec2(x1, by + bh), true);
            ui::text_mid_centre(c, c.f.strong, 15 * k, cx, by + bh * 0.5f, ui::kInk, v.pct.c_str());
            c.d->PopClipRect();
            under = by + bh;
        }
        const float px = 16.5f * k;
        ui::text(c, c.f.body, px, ImVec2(v.fraction >= 0 ? x0 : cx - ui::size_of(c.f.body, px, v.left.c_str()).x * 0.5f, under + 12 * k),
                 ui::kSoft, v.left.c_str());
        if (!v.right.empty())
            ui::text(c, c.f.body, px, ImVec2(x1 - ui::size_of(c.f.body, px, v.right.c_str()).x, under + 12 * k), ui::kSoft, v.right.c_str());
        if (!v.hint.empty()) ui::text_centre(c, c.f.body, 15.5f * k, ImVec2(cx, by + 92 * k), ui::kDim, v.hint.c_str());
    }
    if (const float f = startup_fade.load(std::memory_order_relaxed); f > 0)   // (the end: to black, the game's first frame next)
        c.d->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), ui::rgba(0, 0, 0, (int)(std::min(f, 1.0f) * 255 + 0.5f)));
}

} // namespace

void startup_fade_to(float f) { startup_fade.store(f, std::memory_order_relaxed); }

// (hookshot, #1886) The Upscaler row's one-time questions: NVIDIA's NGX started (dlss_probe), AMD's FSR 4 loaded
// (fsr4_probe), Intel's XeSS context made once (xess_probe), FSR 3.1's GPU check. They were asked at the menu's first open, on the frame's thread, and NGX's start
// alone held that frame about 3 s (an RTX 5080 at 4K; 2.9 s here): the game stood still and its sound ran on, out of
// step with a cutscene. Now asked once on a thread of their own while the start-up screen shows, where nobody waits on
// them; each is locked and asked once (ngx_init, fsr4's load, fsr3::supported's static), so the menu's own calls at its
// open return at once, or wait for the rest of the one under way.
static void probe_upscalers_soon() {
    static std::once_flag once;
    std::call_once(once, [] {
        if (!dev.device) return;
        std::thread([] {
            const auto t0 = std::chrono::steady_clock::now();
            dlss_probe();
            dlss_fg_probe();   // (after DLSS's own answer: whether the Frame generation by row offers DLSS FG)
            fsr4_probe();
            xess_probe();
            (void)fsr3::supported();
            logf("menu: the upscalers asked in the background while the start-up screen shows (%.0f ms)",
                 std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
        }).detach();
    });
}

void startup_screen(const StartupView* view) {
    if (!view) {
        startup_on.store(false, std::memory_order_release);
        startup_fade.store(0, std::memory_order_relaxed);
        return;
    }
    StartupView v = *view;
    if (v.version.empty()) v.version = version_text(HOOKSHOT_VERSION);   // ("v2.0.5"; "v2.0.5 dev" between releases)
    {
        std::lock_guard lk(startup_mu);
        startup = v;
    }
    startup_on.store(true, std::memory_order_release);
    probe_upscalers_soon();
}

static bool first_start = false;   // (menu_init: no options file yet. menu_first_start_for_gpu picks the preset for the card)
void menu_init() {
    static bool done;
    if (done) return;
    done = true;
    for (auto& count : item_counts) count.store(-1, std::memory_order_relaxed);
    for (auto& done : tracker_done) done.store(-1, std::memory_order_relaxed);
    bool has_options = false;
    bool has_output = false;   // (an output_res= line: the Output resolution chosen; none: hos_output_default, as the host)
    bool has_memory_budget = false;   // (a file from before memory_budget: its preset's)
    const char* cheats = getenv("HOS_OOT_CHEATS");
    cheats_env = cheats && !strcmp(cheats, "1");
    if (cheats_env) {
        const char* hearts = getenv("HOS_OOT_PROTECT_HEARTS");
        protect_hearts.store(hearts && !strcmp(hearts, "1"));
    }
    if (FILE* f = fopen(ini_path().c_str(), "r")) {
        char line[4096]; // Endpoint IDs are opaque and must not be cut into multiple settings.
        bool has_resolution = false;
        bool v2 = false;
        int version = 0;
        int old_dynres = -1;   // (the row before Resolution: 0, the full scale, is its 100%; 1 is Auto)
        bool menu_auto = false;   // (menu_size=0, the Menu size Auto there was before: Medium, not the Small the row's clamp gives)
        while (fgets(line, sizeof line, f)) {
            if (!strchr(line, '\n') && !feof(f)) {
                if (!strncmp(line, "audio_output_device_id=", 23)) output_want.clear();
                int c; while ((c = fgetc(f)) != '\n' && c != EOF) {}
                continue;
            }
            char* eq = strchr(line, '=');
            if (!eq) continue;
            *eq = 0;
            // (a file with only the builders' Compile shaders in it, compile_shaders=, which make_game.py writes into a new
            // folder before the game ever started: still a first start, so Auto (this PC) chooses as it would with no file)
            has_options |= strcmp(line, "compile_shaders") != 0;
            for (Row& r : rows) {
                if (!r.value || r.value == &opts.game_lang || strcmp(line, ini_key(r))) continue;
                const int v = atoi(eq + 1);
                *r.value = r.value == &opts.output_res ? parse_output(eq + 1) : std::min(std::max(v, r.lo), r.hi);
            }
            if (!strncmp(line, "toggle_", 7))
                for (int i = 0; i < HOS_SW_N; i++)
                    if (i != HOS_SW_PLUS && i != HOS_SW_MINUS && !strcmp(line + 7, bind_names[i])) {
                        const int bit = 1 << i;
                        opts.hold_toggle = atoi(eq + 1) == 1 ? opts.hold_toggle | bit : opts.hold_toggle & ~bit;
                    }
            has_resolution |= !strcmp(line, "resolution");
            has_output |= !strcmp(line, "output_res");
            v2 |= !strcmp(line, "options_version");
            if (!strcmp(line, "options_version")) version = atoi(eq + 1);
            if (!strcmp(line, "dynamic_resolution")) old_dynres = atoi(eq + 1);
            if (!strcmp(line, "menu_size") && atoi(eq + 1) == 0) menu_auto = true;
            if (!strcmp(line, "auto_for")) auto_for = strtoull(eq + 1, nullptr, 16);
            if (!strcmp(line, "gpu_device_id")) gpu_saved_card.assign(eq + 1, strcspn(eq + 1, " \t\r\n"));   // (menu_set_gpu_count)
            if (!strcmp(line, "auto_tuned")) auto_tuned = strtoull(eq + 1, nullptr, 16);
            if (!strcmp(line, "auto_steps")) {
                int steps = 0, down = 0;
                if (sscanf(eq + 1, "%d,%d", &steps, &down) == 2)
                    auto_tuning.steps = std::max(steps, 0), auto_tuning.went_down = down != 0;
            }
            if (!strcmp(line, "memory_budget")) opts.budget = std::min(std::max(atoi(eq + 1), 0), 5), has_memory_budget = true;
            if (!strcmp(line, "microphone_device")) {   // (hookshot: the microphone, by its name)
                mic_want = mic_key(eq + 1);
            }
            if (!strcmp(line, "audio_output_device_id")) output_want = output_id_key(eq + 1);
            if (!strcmp(line, "audio_output_device_name")) output_saved_name = output_name_key(eq + 1);
            if (!strcmp(line, "fullscreen_monitor_id")) monitor_want = monitor_choice::id_key(eq + 1);
            if (!strcmp(line, "fullscreen_monitor_name")) monitor_saved_name = output_name_key(eq + 1);
        }
        fclose(f);
        // (the saved microphone by its name, not its place; the host told the row's choice. Off or the default: no list, no SDL
        // audio at the start)
        refresh_outputs();
        if (can_outputs()) host->audio_output_select(output_want.c_str());
        refresh_monitors();
        if (can_monitors()) host->monitor_select(monitor_want.c_str());
        if (!mic_want.empty()) refresh_mics();
        else {
            if (opts.mic >= 2) opts.mic = 1;
            mic_tell_host();
        }
        if (!has_resolution && old_dynres >= 0) opts.resolution = old_dynres ? 0 : 1;
        if (menu_auto) opts.menu_size = 2;
        opts.rumble = rumble_step(opts.rumble);   // (a hand-edited 60: 50, on the arrows' steps)
        // (Game speed is Real time by default now: Per frame played at half speed at 30 fps, the "slow motion" players
        // reported. An options file from before kept the old default whether chosen or not: Real time for it too)
        if (!v2) opts.realtime = 1;
        // (Descriptor reuse is on by default from options_version 4: a file from before wrote its 0 whether chosen or not, as
        // the off default it then was; fewer stutters and a better 1% low in the field, the flash checks clean, 2026-11-10)
        if (version < 4) opts.descriptor_reuse = 1;
        // (Esc opens the menu by default from options_version 5, as a PC game's pause menu: a file from before wrote its
        // Menu shortcut 0, Insert or F1, whether chosen or not, and moves to Insert, F1 or Esc, where Insert and F1 still
        // work. F1 only was chosen: kept)
        if (version < 5 && opts.menu_shortcut == 0) opts.menu_shortcut = 2;
        // (the Aspect ratio from options_version 6: a file from before wrote ultrawide=0, the 16:9 default then, whether
        // chosen or not. On a screen narrower than 16:9 host/hos_main.c starts the game at the monitor's shape for it
        // (host/hos_wide_size.h hos_aspect_on), and the row follows what the host started with: a picture narrower than
        // 16:9 there. On Linux too, where the menu has no screen size of its own. Not with HOS_ASPECT, a debugging switch
        // the host takes instead of the file: the shape it started with is then the switch's, not a move, and the next save
        // would keep a choice the player never made)
        if (version < 6 && opts.ultrawide == 0 && !getenv("HOS_ASPECT") && host && host->aspect_ratio) {
            const float started = host->aspect_ratio();
            if (started > 1.0f && started < 16.0f / 9.0f * 0.99f) opts.ultrawide = 1;
        }
    }
    first_start = !has_options;
    sync_transition_autosave();
    const char* handheld_env = getenv("HOS_HANDHELD");   // (host/nn_applet.c handheld(): the environment over the file's)
    if (!has_output && !(handheld_env ? atoi(handheld_env) != 0 : opts.handheld != 0)) {
        // (none chosen, a new install: the size host/nn_applet.c took at boot, the game's 2560x1440 or the main screen's where
        // it has fewer pixels (a Steam Deck's 1280x800), hos_output_default. Saved from now on, so the two never part.
        // HOS_OUTPUT_RES, below, is over it, as over a chosen one)
        uint32_t sw = 0, sh = 0, w = 0, h = 0;
        host_screen_size(&sw, &sh);   // (not known: 0 x 0, the game's 2560x1440)
        hos_output_default(sw, sh, &w, &h);
        opts.output_res = output_choice_of(w, h);
        logf("vk: the Output resolution: none chosen, %ux%u (the game's 2560x1440, or the screen's where smaller)", w, h);
    }
    // An opt-in profile for 4 GB cards: keep existing options authoritative, but make a first run usable on
    // low-VRAM hardware without requiring the menu to render first.
    if (!has_options && env_on("RX_VK_LOW_SPEC")) {
        apply_preset(1);
        opts.upscale = 0;
        opts.sharpness = 0;
    }
    if (opts.preset > 0 && !has_memory_budget) opts.budget = opts.preset;   // (a file from before memory_budget: its preset's)
    if (opts.preset == kAutoPreset && !has_memory_budget) opts.budget = 0;   // (Auto: its tier's, menu_auto_for_gpu)
    menu_debug_rows(opts.descriptor_reuse, opts.sampler_cache);   // (the Debug rows that apply in play: what was loaded)
    fps_level_now.store(fps_stats::level_of(opts.show_fps), std::memory_order_relaxed);
    output_field_show();   // (hookshot: Custom output size, the size of the player's own, as the file has it)
    // (the environment over the saved rows, for this run only: env_override, save)
    if (const char* e = getenv("RX_VK_FRAMEGEN_MULT")) env_override(&opts.framegen, std::min(std::max(atoi(e), 2), 8));
    if (const char* e = getenv("RX_VK_PACE")) env_override(&opts.pace, !env_value_off(e));
    if (const char* e = getenv("RX_VK_UPSCALE"))
        for (Row& r : rows)
            if (r.value == &opts.upscale) env_override(r.value, std::min(std::max(atoi(e), r.lo), r.hi));
    if (const char* e = getenv("HOS_REALTIME_STEP")) env_override(&opts.realtime, !env_value_off(e));
    if (const char* e = getenv("HOS_DYNRES")) env_override(&opts.resolution, env_value_off(e) ? 1 : 0);
    if (const char* e = getenv("HOS_SKIP_OPENING")) env_override(&opts.skip_opening, !env_value_off(e));
    // (vk_texture.cpp reads RX_VK_ASTC_RGBA8 over the row: the row shows it, fixed (row_fixed), and the ini keeps the player's)
    if (const char* e = getenv("RX_VK_ASTC_RGBA8")) env_override(&opts.astc_rgba8, !env_value_off(e));
    if (const char* e = getenv("RX_VK_NO_INTEL_SERIAL")) env_override(&opts.intel_compiles, env_value_off(e) ? 2 : 1);
    if (const char* e = getenv("RX_VK_COMPUTE_QUICK_FIRST")) env_override(&opts.intel_quick, !env_value_off(e));
    if (const char* e = getenv("HOS_OUTPUT_RES")) {
        player_custom_output = custom_output;   // (parse_output replaces the player's own size with the environment's)
        env_override(&opts.output_res, parse_output(e));
    }
    outputs_sync();   // (the Aspect ratio follows the size read)
    restart_init();   // (what this run started with: the rows that take a restart differ from it once changed)
}

/// (hookshot) The Quality preset "Auto (this PC)", once the card is chosen (vk_main.cpp pick_device): the profile auto_settings.h
/// picks from the hardware. A first start (no options file yet) starts on it. With Auto on, the profile is applied when the
/// hardware it was chosen for changes (another card, its memory, the screen's size, a build with or without DLSS or FSR 4):
/// the fingerprint is kept in the options file (auto_for=). Changing a row yourself comes back to Custom, and then nothing here
/// touches the settings; the rows no preset sets (the Output resolution) leave it on Auto, and Auto never sets the Output
/// resolution. The VRAM budgets are no preset's: one rule by the card (texture_budget.h, mirror_budget.h). Before Auto,
/// a first start chose Minimum or Low by the card's memory alone: an older or smaller card no longer starts with the full-size
/// budget (a GTX 1050 lost the device at the first scene that way,
/// Discord 2026-11-10). RX_VK_AUTO_PRESET=0: a first start keeps the defaults, as before Auto.
/// RX_VK_AUTO_PRESET_VRAM_MB=<n>: the card's memory taken as n MB, to try the choice for a smaller or larger card
void menu_auto_for_gpu(const VkPhysicalDeviceProperties& props, ::auto_settings::Hardware hw) {
    const bool first = first_start;
    first_start = false;
    if (const char* e = getenv("RX_VK_AUTO_PRESET_VRAM_MB")) hw.vram_mb = (uint32_t)atoll(e);
    auto_choice = ::auto_settings::choose(hw);
    const uint64_t fp = auto_fp = ::auto_settings::fingerprint(hw, props.vendorID, props.deviceID);
    if (first && (!env_int("RX_VK_AUTO_PRESET", 1) || env_on("RX_VK_LOW_SPEC"))) return;   // (off, or chosen already: menu_init)
    char hw_line[200];
    snprintf(hw_line, sizeof hw_line, "%s, %u MB of video memory, %s, screen %dx%d at %d Hz, %u MB of RAM, %d threads",
             props.deviceName, (unsigned)hw.vram_mb, hw.integrated ? "integrated" : "dedicated", hw.screen_w, hw.screen_h,
             hw.refresh_hz, (unsigned)hw.ram_mb, hw.threads);
    if (first) opts.preset = kAutoPreset;
    if (opts.preset != kAutoPreset) {
        logf("vk: Auto (this PC) would be: %s (%s)", auto_choice.why, hw_line);   // (for a bug report: what Auto would choose)
        return;
    }
    // (an options file from the VRAM budget row, set under Auto: memory_budget=0, the preset Auto's tier is again, for Minimum's
    // mip trimming: low_vram_texture_mips)
    if (opts.budget == 0) opts.budget = auto_choice.tier;
    if (fp == auto_for) {
        logf("vk: Auto (this PC): the settings chosen for this PC before (%s)", hw_line);
        return;
    }
    apply_auto();   // (the hardware changed)
    // (a row that takes a restart Auto sets, the Profile (docked), applies at the next start, a first start's too: host/hos_main.c
    // read it at boot, before the device, and this run keeps what menu_init recorded. It is Auto's, not the player's: closing the
    // menu does not ask to restart for it, as after Later. The row still says After restart, and a change of the player's own to
    // any restart row asks again, about all of them)
    {
        int now[mr::kMax];
        restart_values(now);
        if (restart_state.pending(now)) restart_state.choose_later(now);
    }
    save();   // (for the next start: host/nn_applet.c read handheld_profile and output_res once, at boot in host/hos_main.c, before this)
    logf("vk: Auto (this PC): %s: %s (%s)", first ? "first start" : "the hardware changed", auto_choice.why, hw_line);
}

// (the switches read once, at the first present: they are for the whole run, and each present asked twice)
int menu_vsync() { static const int run = env_on("RX_VK_FIFO") ? 1 : env_on("RX_VK_IMMEDIATE") ? 2 : 0; return run ? run : opts.vsync; }
/// (hookshot) The Threaded rendering row, resolved once for the run (threaded_rendering.h): the row as the options file had it
/// at the start (menu_init, asked here too: a reader can come before the device is picked), the logical processors the process
/// may run on (usable_cpus: its affinity mask) and, for Auto, whether the mode is safe on this run. Known at the start and
/// read here: the capture off (RX_VK_CAPTURE=0: a replay behind the game is right only from the capture),
/// RX_VK_LOW_SPEC, a frame dump (RX_VK_DUMP), a benchmark replay (RX_VK_BENCH), and buffer pools with no mirrors at all
/// (pools_mirrored: RX_VK_MIRROR=0, an integrated GPU, GCN), asked last and only when Auto would otherwise say yes, since it
/// reads the device. Not known at the start, so not here: one pool refused its mirror or over the mirrors' budget while the
/// game runs (that needs the run-time fallback, which is not written). On is the player's word: nothing is checked for it
bool menu_threaded_rendering() {
    static const bool on = [] {
        menu_init();
        const unsigned cpus = usable_cpus();
        const char* capture = getenv("RX_VK_CAPTURE");
        // (vk_memory.cpp capture_on's reading: 0 none, anything else the capture)
        const char* unsafe = capture && atoi(capture) == 0 ? "RX_VK_CAPTURE" :
                             env_on("RX_VK_LOW_SPEC") ? "RX_VK_LOW_SPEC" : getenv("RX_VK_DUMP") ? "RX_VK_DUMP" :
                             getenv("RX_VK_BENCH") ? "RX_VK_BENCH" : nullptr;
        threaded::Choice c = threaded::choose(opts.threaded_rendering, cpus, unsafe != nullptr);
        if (c.why == threaded::Why::AutoCpus && !pools_mirrored()) {
            c = threaded::Choice{false, threaded::Why::AutoUnsafe};
            unsafe = "the buffer pools have no mirrors";
        }
        switch (c.why) {
        case threaded::Why::On: logf("vk: Threaded rendering: On (the render thread and the recorder thread)"); break;
        case threaded::Why::Off: logf("vk: Threaded rendering: Off"); break;
        case threaded::Why::AutoGate:
            logf("vk: Threaded rendering: Auto: off (Auto is turned off in this build; %u logical processors, its rule is on "
                 "from %u)", cpus, threaded::kAutoCpus);
            break;
        case threaded::Why::AutoUnsafe: logf("vk: Threaded rendering: Auto: off (not safe on this run: %s)", unsafe); break;
        case threaded::Why::AutoFewCpus:
            logf("vk: Threaded rendering: Auto: off (%u logical processors, on from %u)", cpus, threaded::kAutoCpus);
            break;
        case threaded::Why::AutoCpus:
            logf("vk: Threaded rendering: Auto: on, the render thread and the recorder thread (%u logical processors)", cpus);
            break;
        }
        return c.on;
    }();
    return on;
}
bool intel_compiles_side_by_side() {   // (RX_VK_NO_INTEL_SERIAL in the row: menu_init. Asked once the device is made)
    return intel_side_by_side_chosen(opts.intel_compiles, dev.props.deviceID, dev.props.driverVersion);
}
// (Intel's Windows driver only, where the row shows: Mesa's ANV ignores DISABLE_OPTIMIZATION, same instructions, spills and
// compile time on an Iris Xe, its slow part register allocation at SIMD32)
bool intel_quick_compute() { return opts.intel_quick != 0 && intel_compiler_row(); }   // (RX_VK_COMPUTE_QUICK_FIRST in it: menu_init)
bool resolution_auto() { return opts.resolution == 0; }
int resolution_scale() {
    const float s = upscaler_rows::percent(ur::snap_render(upscaler(), opts.resolution)) / 100.0f;
    return s > 0 ? (int)(twelfths(s) * 10000.0f / 12.0f + 0.5f) : 0;   // (the twelfth game_size labels)
}

/// The usable GPUs counted (vk_main.cpp pick_device, gpu_device_cards filled): the row offers them, and a card the options file
/// saved (gpu_device_id=) is found where it is in this run's list, whatever its place was (gpu_choice.h). One not here (taken
/// out, an eGPU unplugged) is Auto for the run, and stays saved (save) until the row is changed. A file from before the card
/// was saved keeps its place (gpu_device=), and saves the card at its next save
void menu_set_gpu_count(int count) {
    if (!gpu_saved_card.empty()) {
        const int at = gpu_choice::menu_of_card(gpu_device_cards, gpu_saved_card);
        gpu_card_missing = at == 0;
        if (at > 0 && at != opts.gpu_device)
            logf("vk: GPU device: the saved card (%s) is %d: %s now, not %d", gpu_saved_card.c_str(), at - 1,
                 gpu_device_names[at - 1].c_str(), opts.gpu_device - 1);
        else if (!at) logf("vk: GPU device: the saved card (%s) is not here: Auto for this run, kept for when it is back", gpu_saved_card.c_str());
        opts.gpu_device = at;
    }
    for (Row& r : rows) {
        if (r.value == &opts.gpu_device) {
            r.hi = count;
            if (opts.gpu_device > count) opts.gpu_device = 0;
        }
    }
    restart_init();
    for (int i = 0; i < kRows; i++)   // (the row's value the game started with, the cards counted)
        if (rows[i].value == &opts.gpu_device) restart_state.restart_value(restart_slot[i], opts.gpu_device);
}

bool menu_is_open() { return open_now.load(std::memory_order_relaxed); }
double menu_target_ms() { return fps_target_ms(); }   // (the performance summary's: perf_report.cpp)
int menu_fps_cap() { return fps_cap_now(); }          // (likewise: its fps_cap label)
bool scene_tonemap_on() { return dev.hdr && opts.hdr == 2 && opts.hdr_tonemap == 1; }
// (the tools off on the Debug tab: flight, the free camera and heart protection put away; -1, heart protection never set, is the
// host's own HOS_OOT_PROTECT_HEARTS)
int menu_heart_protection() {
    const int v = protect_hearts.load(std::memory_order_relaxed);
    return cheats_on() || v < 0 ? v : 0;
}
int menu_player_flight() { return cheats_on() ? player_flight.load(std::memory_order_relaxed) : -1; }
int menu_free_camera() { return cheats_on() ? free_camera.load(std::memory_order_relaxed) : 0; }
int menu_link_speed() { return cheats_on() ? link_speeds[std::clamp(link_speed.load(std::memory_order_relaxed), 0, kLinkSpeeds - 1)] : 100; }
/// The size the host draws the sun's cascades at (HOS_OPT_SHADOW_RES: 0 the game's 1600, 1 2200, 2 3072): the row's, or for
/// Auto the one for the card's memory tier, the preset's (opts.budget) or else Auto's own for this PC (auto_choice): the
/// game's on Minimum and Low (4 and 6 GB, where 113 MB is a lot), 2200 on Balanced (8 GB), 3072 from High (12 GB) up
int menu_shadow_res() {
    if (opts.shadow_res > 0) return std::min(opts.shadow_res, 3) - 1;
    const int tier = opts.budget > 0 ? opts.budget : auto_choice.tier;
    return tier == 1 || tier == 2 ? 0 : tier >= 4 ? 2 : 1;   // (an unknown tier: 2200, the middle)
}
int menu_transition_autosave() { return transition_autosave_enabled.load(std::memory_order_relaxed); }
int menu_damage_taken() { return cheats_on() ? opts.damage_taken : 1; }   // (Normal while the tools are off; the choice is kept)
int menu_take_cheat_action() { return cheat_action.exchange(0, std::memory_order_relaxed); }

void menu_note_present_sizes(uint32_t picture_w, uint32_t picture_h, uint32_t window_w, uint32_t window_h) {
    const auto c = [](uint32_t v) { return (uint64_t)std::min(v, 0xffffu); };
    present_sizes.store(c(picture_w) << 48 | c(picture_h) << 32 | c(window_w) << 16 | c(window_h), std::memory_order_relaxed);
}
void menu_note_frame(bool game_frame, int shown) {
    if (shown) shown_frames.fetch_add(shown, std::memory_order_relaxed);
    if (game_frame) game_frames.fetch_add(1, std::memory_order_relaxed);
    perf_monitor_note_frame(game_frame);
}

// The Fullscreen row and F11 are one setting: the row asks the window's thread (host/display.c), F11 shows in the row
void fullscreen_tick() {
    static int applied = 0, settle = 0;
    const HWND main_window = app_window();
    if (!main_window) return;
    static const bool env = getenv("HOS_FULLSCREEN") != nullptr;   // (a test's own choice: the row is left alone)
    if (env) return;
    if (opts.fullscreen != applied) {
        applied = opts.fullscreen;
        settle = 60;
        PostMessageA(main_window, WM_APP + 7, (WPARAM)applied, 0);
        return;
    }
    if (settle > 0) { settle--; return; }
    const int now = !(GetWindowLongA(main_window, GWL_STYLE) & WS_CAPTION);
    if (now != applied) {
        opts.fullscreen = applied = now;
        menu_refresh = true;
        save();
    }
}

/// The FPS counter's lines past the number, four times a second: the game's frame time over the last half second and
/// the 1% low over 10 s; the Breakdown's parts and the GPU's time over the half second, the shaders built and the draws left
/// out over the graph's 4 s
void fps_texts(int64_t now) {
    namespace fs = fps_stats;
    const int level = fs::level_of(opts.show_fps);
    if (level < fs::kFrameTime) return;
    const fs::Summary half = fps_summary(now, fs::kSecond / 2, fs::kLowWindow);
    fs::frame_time_text(fps_ms_text, sizeof fps_ms_text, half.avg_ms);
    fs::low_text(fps_low_text, sizeof fps_low_text, half.low_fps);
    if (!half.frames) fps_ms_text[0] = 0;
    fps_ms_now = half.avg_ms;
    if (level < fs::kBreakdown) return;
    for (int p = 0; p < fs::kParts; p++) fs::frame_time_text(fps_part_text[p], sizeof fps_part_text[p], half.part[p]);
    fs::frame_time_text(fps_gpu_text, sizeof fps_gpu_text, half.gpu_ms);
    for (int k = 0; k < fs::kRtParts; k++) fs::frame_time_text(fps_rt_text[k], sizeof fps_rt_text[k], half.rt[k]);
    fps_rt_on = half.rt[fs::kRtWork] + half.rt[fs::kRtWorkers] + half.rt[fs::kRtGpu] + half.rt[fs::kRtIdle] > 0;
    snprintf(fps_gpu_busy_text, sizeof fps_gpu_busy_text, "%.0f%%", half.avg_ms > 0 ? std::min(100.0, 100.0 * half.gpu_ms / half.avg_ms) : 0.0);
    const fs::Summary graph = fps_summary(now, fs::kGraphWindow, 0);
    snprintf(fps_built_text, sizeof fps_built_text, "%d", graph.pipelines);
    snprintf(fps_left_text, sizeof fps_left_text, "%d", graph.left_out);
    if (level < fs::kDev) return;
    // (Dev: the renderer's counters since the last time, every half second, by the frames presented in that time)
    static int64_t at = 0, last[8] = {};
    if (at && now - at < fs::kSecond / 2 && now >= at) return;
    int64_t draws = 0, skipped = 0, dispatches = 0, pipelines = 0, passes = 0, mesh = 0, uploads = 0, astc = 0, bytes = 0;
    double pipeline_ms = 0;
    draw_stats(&draws, &skipped, &dispatches, &pipelines);
    draw_stats2(&passes, &mesh, &pipeline_ms);
    texture_stats(&uploads, &astc, &bytes);
    int64_t mirrors = 0, sync_b = 0, sync_c = 0, wb_b = 0;
    uint64_t mirror_mb = 0;
    memory_stats(&mirrors, &mirror_mb, &sync_b, &sync_c, &wb_b);
    const int64_t counts[8] = {draws, dispatches, passes, skipped, bytes, slot_wait_ns(), prof_ns[PROF_QSUBMIT], wb_b};
    const bool first = !at || now < at || now - at > 2 * fs::kSecond;   // (Dev just chosen again: no stretch from before)
    const double seconds = first ? 0 : (double)(now - at) / fs::kSecond;
    const int frames = first ? 0 : fps_summary(now, now - at, 0).frames;
    uint64_t used = 0, allowed = 0;
    const bool known = vram_usage(&used, &allowed) && dev.memory_budget;   // (the status line asks the driver anew: vram_usage_now)
    fps_vram_over = known && allowed && used > allowed;
    fs::vram_line(fps_dev_text[fs::kVram], sizeof fps_dev_text[0], used, allowed, known);
    fs::textures_line(fps_dev_text[fs::kTextures], sizeof fps_dev_text[0], texture_count(), texture_bytes());
    fs::per_frame_line(fps_dev_text[fs::kDraws], sizeof fps_dev_text[0], counts[0] - last[0], frames);
    fs::per_frame_line(fps_dev_text[fs::kDispatches], sizeof fps_dev_text[0], counts[1] - last[1], frames);
    fs::per_frame_line(fps_dev_text[fs::kPasses], sizeof fps_dev_text[0], counts[2] - last[2], frames);
    fs::per_frame_line(fps_dev_text[fs::kSkipped], sizeof fps_dev_text[0], counts[3] - last[3], frames);
    fs::rate_line(fps_dev_text[fs::kUploads], sizeof fps_dev_text[0], counts[4] - last[4], seconds);
    snprintf(fps_dev_text[fs::kPipelines], sizeof fps_dev_text[0], "%lld", (long long)pipelines);
    const auto per_frame = [&](int line, int64_t d, double unit, const char* fmt) {   // (ms or MB a frame; "-" with no frames yet)
        if (frames > 0) snprintf(fps_dev_text[line], sizeof fps_dev_text[0], fmt, d / unit / frames);
        else snprintf(fps_dev_text[line], sizeof fps_dev_text[0], "-");
    };
    per_frame(fs::kSlotWait, counts[5] - last[5], 1e6, "%.2f ms");
    per_frame(fs::kQueueSubmit, counts[6] - last[6], 1e6, "%.2f ms");
    per_frame(fs::kWriteBack, counts[7] - last[7], 1048576.0, "%.1f MB");
    at = now;
    std::memcpy(last, counts, sizeof last);
}

/// A rate over the half-second that just ended. The first call only starts that interval: the frames since launch,
/// divided by one second, were shown as the rate the moment the counter was turned on.
bool fps_take(int64_t now, int64_t shown, int64_t game, int64_t* next, int64_t* last_shown, int64_t* last_game,
              double* shown_rate, double* game_rate) {
    if (now < *next) return false;
    const bool have = *next != 0;
    if (have) {
        const double secs = (now - *next + 500000000) / 1e9;
        *shown_rate = (shown - *last_shown) / secs;
        *game_rate = (game - *last_game) / secs;
    }
    *last_shown = shown;
    *last_game = game;
    *next = now + 500000000;
    return have;
}

// (hookshot) the rows' values and the options file, kept apart between menu_tick (the present's thread), menu_option_set
// (the game's) and the control bridge's menu_setting and menu_setting_set (its own thread). Recursive: a setter reached from
// inside menu_tick's frame on the same thread does not lock itself out
std::recursive_mutex menu_mu;
void menu_option_set(int id, int value) {
    if (id == OOT_CHEAT_AGE_ID) {   // (Link's age: the Switch age row shows it)
        if (link_age.exchange(value, std::memory_order_relaxed) != value && page == 0 && cur_tab == TAB_DEBUG) menu_refresh = true;
        return;
    }
    if (id == OOT_TRACKER_ON) {   // (the randomizer's game is the one played)
        if (tracker_on.exchange(value != 0, std::memory_order_relaxed) != (value != 0) && page == 0 && cur_tab == TAB_TRACKER) menu_refresh = true;
        return;
    }
    if (id == OOT_TRACKER_HERE) {   // (a check of the map Link is in: its area's row comes first)
        tracker_here.store(value, std::memory_order_relaxed);
        return;
    }
    if (id >= OOT_TRACKER_BASE && id < OOT_TRACKER_BASE + kTrackerChecks) {   // (the game side's word on a check: collected or not)
        const signed char state = (signed char)std::clamp(value, -1, 1);
        if (tracker_done[id - OOT_TRACKER_BASE].exchange(state, std::memory_order_relaxed) != state && page == 0 && cur_tab == TAB_TRACKER)
            menu_refresh = true;
        return;
    }
    if (id >= OOT_CHEAT_ITEM_BASE && id < OOT_CHEAT_ITEM_BASE + kItems) {   // (the game side's inventory counts)
        if (item_counts[id - OOT_CHEAT_ITEM_BASE].exchange(value, std::memory_order_relaxed) != value && page == 4)
            menu_refresh = true;
        return;
    }
    if (id == HOS_OPT_CHEAT_FLIGHT) {
        if (cheats_on()) {
            int expected = value ? 0 : 1;
            player_flight.compare_exchange_strong(expected, value != 0, std::memory_order_relaxed);
        }
        return;
    }
    if (id != 7) return;
    std::lock_guard lk(menu_mu);   // (the counts above are atomics: the game's thread waits for no menu frame for them)
    opts.mouse_sens = std::min(std::max(value, 10), 500);   // (the keys work while the menu is closed: it shows it when opened)
    save();
}

// ---- (hookshot) the control bridge's option_get and option_set (host/control.c, docs/control.md) ----
// The settings rows (a value, not a heading or a debug tool, shown on this PC: row_shown), found by their key in
// hookshot_options.ini (ini_key), which stays the same while rows come and go or are renamed. The bridge calls these from
// its own thread: menu_mu keeps them apart from menu_tick (the present's thread) and from menu_option_set (the game's)
bool bridge_row(int i) { return rows[i].value && !rows[i].heading && rows[i].cheat < 0 && row_shown(i); }
void bridge_fill(int i, MkwVkSetting* out) {
    static const char* const tabs[] = {"graphics", "audio", "gameplay", "controls", "debug", "tracker", "motion", "gameplay", "controls"};   // (tracker: the randomizer's fork's tab)
    static_assert(sizeof tabs / sizeof tabs[0] == TAB_PAGE + 1, "a name for each MenuTab");
    const Row& r = rows[i];
    *out = MkwVkSetting{};
    snprintf(out->key, sizeof out->key, "%s", ini_key(r));
    snprintf(out->name, sizeof out->name, "%s", r.name);
    snprintf(out->tab, sizeof out->tab, "%s", r.tab >= 0 && r.tab <= TAB_PAGE ? tabs[r.tab] : "");
    out->value = *r.value, out->lo = r.lo, out->hi = r.hi, out->step = r.step;
    out->restart = r.restart, out->fixed = row_fixed(r.value);
    snprintf(out->text, sizeof out->text, "%s", r.text ? r.text(out->value) : "");
}
// (the Upscaler row's questions, asked before menu_mu is taken: row_shown and row_fixed ask upscalers_available(), which
// waits for the start-up probe (NGX's start, ~3 s) while it runs. Under menu_mu that held menu_tick, and the present with
// it; this way only the bridge's thread waits, and once answered the questions return at once)
static void bridge_probe_first() { (void)upscalers_available(), (void)dlss_why(); }
/// The index-th settings row (an enumeration, for listing them; the index is not a name: rows come and go). 0: past the last
int menu_setting(int index, MkwVkSetting* out) {
    bridge_probe_first();
    std::lock_guard lk(menu_mu);
    for (int i = 0, n = 0; i < kRows; i++)
        if (bridge_row(i) && n++ == index) return bridge_fill(i, out), 1;
    return 0;
}
/// A row whose choices are not in the order of their numbers (the output sizes go by width, the Render resolution's slider by
/// size, the Upscaler by engine), walked in the arrows' own order to the value asked for: one way, then the other, each way
/// until at() holds, the row stops at an end (state() unchanged) or it comes round to where that way began. A value none of
/// its steps reach here leaves the row as it was. state(): all a step changes (the Render resolution's Native moves the
/// Upscaler, not the value); step(dir): one arrow press. Stepping towards the number stopped short: from 2048x1152, 1920x1080
/// (3) went on to 5120x1440 (4), and from DLSS Auto any Render resolution stopped at Native, which leaves the value as it was
template <class State, class At, class Step>
bool walk_to(State state, At at, Step step, int limit) {
    const auto start = state();
    for (const int dir : {1, -1}) {
        const auto from = state();
        for (int k = 0; k < limit && !at(); k++) {
            const auto was = state();
            step(dir);
            if (state() == was || state() == from) break;
        }
        if (at()) return true;
    }
    for (int k = 0; k < limit && state() != start; k++) step(1);   // (back where it was: an end-stopped row is at its first)
    return false;
}

/// (hookshot) The Quality preset Auto (this PC)'s measured tuning in play (auto_settings.h tune): each of the replay's 120-present
/// windows (vk_replay.cpp), the Render resolution one step lighter while frames are missed with the GPU over 90% of the cap's
/// frame time, or one heavier while the cap holds with the GPU under 50%, up to the best mode that still upscales (never
/// native); at most two steps (kept across restarts, auto_steps=), then done for this PC (auto_tuned=). The CPU holding the
/// frame rate ends it for this run only. Not with Frame generation on (the frames shown are not the game's) nor with another
/// preset. RX_VK_AUTO_TUNE=0: off. Before the tuning, in play (the upscaler has run, NGX has answered): the Render resolution for
/// the upscaler that runs, when it is not the one Auto chose (auto_settings.h resolution_for)
void menu_auto_tune(double gpu_ms, double draws, double fps) {
    static const bool on = env_int("RX_VK_AUTO_TUNE", 1) != 0;
    ::auto_settings::Tuning& tuning = auto_tuning;
    std::lock_guard lk(menu_mu);
    if (opts.preset != kAutoPreset || !auto_for) return;
    if (draws >= 150) {
        const ::auto_settings::Choice& c = auto_choice;
        const int u = upscaler(), v = opts.resolution;
        const int to = ::auto_settings::resolution_for(c, ur::engine(u), v, c.resolution ? ur::snap_render(c.upscaler, c.resolution) : 0);
        if (to && ur::snap_render(u, to) != v) {
            opts.resolution = ur::snap_render(u, to);
            env_release(&opts.resolution);
            samplers_changed();
            menu_refresh = true;
            tuning.n = 0;   // (the windows gathered were at the other share)
            static const char* const name[ur::kUpscalers] = {"the game's own", "DLSS", "DLAA", "FSR 3.1", "FSR 4", "FSR 4", "Off",
                                                             "XeSS", "XeSS"};
            logf("vk: Auto (this PC): %s runs, not the %s chosen: Render resolution %d%% -> %d%%",
                 name[std::clamp(u, 0, ur::kUpscalers - 1)], name[std::clamp(c.upscaler, 0, ur::kUpscalers - 1)], ur::percent(v),
                 ur::percent(opts.resolution));
            save();
            return;
        }
    }
    if (!on || auto_tuned == auto_for || opts.framegen || tuning.done) return;
    // (the frame time the game runs to: the cap it started with, HOS_FPS_MAX over it, or the display's refresh with V-Sync On;
    // as the FPS counter's line. Uncapped without V-Sync: the display's refresh, else 60)
    const double target = fps_target_ms();
    const int refresh = (display_refresh_mhz() + 500) / 1000;
    const float cap = target > 0 ? (float)(1000.0 / target) : refresh > 0 ? (float)refresh : 60.0f;
    const int u = upscaler(), v = opts.resolution;
    if (ur::full_scale(u) || v == 0) return;   // (Native, or Auto's dynamic share: no steps to measure along)
    // (heavier: up to the best mode that still upscales, past what the profile chose; never native: auto_settings.h best_step)
    const int ceiling = ::auto_settings::best_step(u);
    const int lighter = ur::step(u, v, 1), heavier = ur::step(u, v, -1);
    const bool can_lighter = lighter != 0 && ur::percent(lighter) < ur::percent(v);
    const bool can_heavier = heavier != 0 && ur::percent(heavier) > ur::percent(v) && ur::percent(heavier) <= ur::percent(ceiling);
    const auto verdict = ::auto_settings::tune(tuning, (float)gpu_ms, (float)draws, (float)fps, cap, can_lighter, can_heavier);
    if (verdict == ::auto_settings::WAIT) return;
    if (verdict == ::auto_settings::LIGHTER || verdict == ::auto_settings::HEAVIER) {
        opts.resolution = verdict == ::auto_settings::LIGHTER ? lighter : heavier;
        env_release(&opts.resolution);
        samplers_changed();   // (the upscalers' texture LOD bias follows the 3D's share, as when the row is set)
        menu_refresh = true;
        logf("vk: Auto (this PC), measured in play: %.0f fps of %.0f, the GPU at %.1f ms a frame of %.1f: Render resolution %d%% -> "
             "%d%%", tuning.fps_mid, cap, tuning.gpu_mid, 1000.0 / cap, ur::percent(v), ur::percent(opts.resolution));
    } else if (verdict == ::auto_settings::CPU_BOUND) {
        // (this run only: early in play pipelines may still be compiling and textures streaming in; the next start measures again)
        logf("vk: Auto (this PC), measured in play: the CPU holds the frame rate (%.0f fps of %.0f, the GPU at %.1f ms a frame of "
             "%.1f): Render resolution %d%% kept for this run", tuning.fps_mid, cap, tuning.gpu_mid, 1000.0 / cap, ur::percent(v));
        return;
    } else {
        auto_tuned = auto_for;
        logf("vk: Auto (this PC), measured in play: settled (%.0f fps of %.0f, the GPU at %.1f ms a frame of %.1f): Render resolution "
             "%d%% kept", tuning.fps_mid, cap, tuning.gpu_mid, 1000.0 / cap, ur::percent(v));
    }
    save();   // (after a step too: its steps, auto_steps=, so a restart before the next verdict keeps the no-seesaw rule)
}

/// The settings row whose ini key is key, set to value as the menu's Left and Right set it (set_row: cut to its range, the
/// Quality preset made Custom unless the row is exempt, a restart noted, kept in the options file). The rows the arrows step
/// through a list of their own (the Upscaler, Render resolution, the output resolution) are walked to value: walk_to. out: the
/// row as it is now. 1 set, 0 no such row, -1 nothing to choose on this PC (row_fixed), -2 none of a list row's steps reach
/// value here (the row and the rest as they were)
int menu_setting_set(const char* key, int value, MkwVkSetting* out) {
    bridge_probe_first();
    std::lock_guard lk(menu_mu);
    int i = 0;
    while (i < kRows && !(bridge_row(i) && !strcmp(ini_key(rows[i]), key))) i++;
    if (i == kRows) return 0;
    Row& r = rows[i];
    if (row_fixed(r.value)) return bridge_fill(i, out), -1;
    const int want = std::min(std::max(value, r.lo), r.value == &opts.pad_layout ? std::min(r.hi, 2) : r.hi);   // (3: Custom, shown only)
    if (r.value == &opts.output_res && output_choice(want) == want &&
        dm::ratio_name(size_of(output_at(want))) != dm::ratio_name(size_of(output_at(opts.output_res)))) {
        // (a size of another shape: the Aspect ratio moves to it first, as a player would, which takes the Output resolution
        // into that shape's sizes; the walk below goes on from there)
        for (Row& a : rows)
            if (a.value == &opts.ultrawide) set_row(a, aspect_for_choice(want), 1, false);
    }
    if (r.value == &opts.dlss || r.value == &opts.resolution || r.value == &opts.output_res) {
        // (the Render resolution's Native is a place of its own, DLAA or FSR 4's native AA, whatever the value it kept; the
        // Upscaler that runs, as set_row steps it: a saved DLAA that cannot run here is the game's own, and its values count)
        const auto native = [&] { return r.value == &opts.resolution && ur::full_scale(upscaler()); };
        // (a value none of the steps reach: everything the steps on the way changed is put back, the Quality preset and the
        // rows the environment holds too)
        const Options opts_was = opts;
        EnvOverride env_was[sizeof env_overrides / sizeof env_overrides[0]];
        std::copy(std::begin(env_overrides), std::end(env_overrides), env_was);
        const mr::State restart_was = restart_state;
        if (!walk_to([&] { return std::pair(native() ? -1 : *r.value, opts.dlss); }, [&] { return *r.value == want && !native(); },
                     [&](int dir) { set_row(r, *r.value + dir * r.step, dir, false); }, 64)) {
            opts = opts_was;
            std::copy(std::begin(env_was), std::end(env_was), env_overrides);
            restart_state = restart_was;
            samplers_changed();
            menu_refresh = true;
            bridge_fill(i, out);
            return -2;
        }
        save();
    } else if (want != *r.value) {
        set_row(r, want, want > *r.value ? 1 : -1);
    }
    menu_refresh = true;
    bridge_fill(i, out);
    return 1;
}

/// (hookshot) the mouse on the inventory: a section tab chooses it, a card the item (a click selects it, it does not edit),
/// the page arrows turn the page with the choice, the action button and the amount's halves act; the wheel turns the page
/// shown and leaves the choice where it is; a right click goes back
void inventory_mouse(const MkwVkPointer& ptr, int mx, int my, bool* press, bool& changed) {
    const menu_hit::Hit hit = hits.at((float)mx, (float)my);
    if (ptr.pressed & HOS_MOUSE_LEFT) {
        if (hit.part == menu_hit::kRow && hit.index >= 0 && hit.index <= kItemSections) choose_inventory_filter(hit.index), changed = true;
        else if (hit.part == menu_hit::kListLine && hit.index >= inventory_begin() && hit.index < inventory_end())
            item_choice = hit.index, inventory_amount = false, changed = true;
        else if (hit.part == menu_hit::kButton && hit.index == 0) press[7] = true;
        else if (hit.part == menu_hit::kButton && hit.index == 1 && hit.side) press[hit.side < 0 ? 3 : 4] = true;
        else if (hit.part == menu_hit::kButton && (hit.index == 2 || hit.index == 3))   // (the page arrows)
            press[hit.index == 2 ? 13 : 14] = true, inventory_amount = false;
    }
    if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
    if (ptr.wheel) {
        const int was = inventory_page;
        inventory_page = std::max(0, inventory_page - ptr.wheel);   // (drawing keeps it to the pages there are)
        changed |= inventory_page != was;
    }
}
/// (hookshot) the mouse on the teleport list: a click on a card selects it (Travel, or confirm, goes), the Travel button
/// goes; the wheel scrolls the cards and leaves the choice where it is; a right click goes back
void teleport_mouse(const MkwVkPointer& ptr, int mx, int my, bool* press, bool& changed) {
    const menu_hit::Hit hit = hits.at((float)mx, (float)my);
    if (ptr.pressed & HOS_MOUSE_LEFT) {
        if (hit.part == menu_hit::kListLine && hit.index >= 0 && hit.index < kTeleports)
            teleport_choice = hit.index, teleport_follow = true, changed = true;
        else if (hit.part == menu_hit::kButton) press[7] = true;
    }
    if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
    if (ptr.wheel) teleport_wheel += ptr.wheel, teleport_follow = false, changed = true;
}
/// A row of the Tracker tab: Left and Right step through its area's checks (past the last: its own words again), and
/// confirm, with the debug tools on, has the game take Link to the check shown: its place, a metre above it, with its
/// folder and ages, goes into <game folder>\rando\goto_check.txt and the action to the game, and the menu closes
void tracker_press(int row, const bool* press, bool& changed) {
    if (row == kTrackerShowRow && tracker_check_count) {   // (the tab's second row: Left and Right, or confirm, choose what the tab lists)
        if (press[3] || press[4] || press[7]) {
            tracker_show = (tracker_show + kTrackerShows + (press[3] ? -1 : 1)) % kTrackerShows;
            for (int r = 1; r < kTrackerRows; r++) tracker_pick[r] = 0;   // (the rows' own words again: their checks are other ones now)
            changed = true;
        }
        return;
    }
    if (row == kTrackerHomeRow && tracker_check_count) {   // (Return home: confirm, and again within a moment, and the menu closes)
        if (press[7]) {
            const ULONGLONG now = GetTickCount64();
            if (tracker_home_asked && now - tracker_home_asked < kTrackerForgetMs) {
                cheat_action.store(kTrackerHomeAction);
                tracker_home_asked = 0;
                logf("menu: tracker: return home");
                open_now = false;   // (back to the game: a map change starts with an event)
            } else tracker_home_asked = now;
            changed = true;
        }
        return;
    }
    if (!row && tracker_check_count) {   // (the whole game's row: confirm, and again within a moment, forgets what is collected)
        if (press[7]) {
            const ULONGLONG now = GetTickCount64();
            if (tracker_forget_asked && now - tracker_forget_asked < kTrackerForgetMs) {
                cheat_action.store(kTrackerForgetAction);
                tracker_forget_asked = 0;
                for (bool& junk : tracker_junk) junk = false;   // (and the junk marks, the menu's own record: tracker_junk)
                tracker_junk_write(tracker_junk_path(), tracker_junk_stamp, tracker_check_count);
                logf("menu: tracker: forget what is collected, and the junk marks");
            } else tracker_forget_asked = now;
            changed = true;
        }
        return;
    }
    const int n = tracker_row_checks(row);
    if (!n) return;
    if (press[kTrackerJunkPress]) {   // (Y or J: the check shown marked junk, or counted again)
        if (tracker_junk_flip(row)) changed = true;
        return;
    }
    if (press[3] || press[4]) tracker_pick[row] = (tracker_pick[row] + n + 1 + (press[4] ? 1 : -1)) % (n + 1), changed = true;
    const TrackerCheck* k = press[7] && cheats_on() ? tracker_row_check(row, tracker_pick[row]) : nullptr;
    if (!k) return;
    std::string path = game_folder_path() + "rando\\goto_check.txt";
    if (FILE* f = fopen(path.c_str(), "w")) {
        fprintf(f, "%.2f %.2f %.2f %s %s\n", k->stand[0], k->stand[1] + 1.0f, k->stand[2], k->folder, k->ages);
        fclose(f);
        cheat_action.store(kTrackerGoAction);
        logf("menu: tracker: go to the %s of %s at %.1f %.1f %.1f", k->kind, k->folder, k->pos[0], k->pos[1], k->pos[2]);
        open_now = false, changed = true;   // (back to the game: a map change starts with an event)
    }
}

/// A debug tool's row on the Debug tab (Row::cheat i): Left and Right, and confirm (press[7]: A, Enter, a click). Teleport and
/// Inventory open their pages; back from them comes to the Debug tab, the row still selected
void cheat_press(int i, const bool* press, bool& changed) {
    if (i < 2 && (press[3] || press[4] || press[7])) {   // (Left Off, Right On, confirm flips)
        const bool was = i == 0 ? protect_hearts.load() == 1 : player_flight.load() >= 0;
        const bool on = press[7] ? !was : press[4];
        if (i == 0) protect_hearts.store(on ? 1 : 0);
        else if (on != was) player_flight.store(on ? 0 : -1);
        changed = true;
    }
    if (i == 4 && (press[3] || press[4])) {
        clock_hour = (clock_hour + (press[4] ? 1 : 23)) % 24;
        changed = true;
    }
    if (i == 5 && (press[3] || press[4])) {
        pouch_item = (pouch_item + kPouchItems + (press[4] ? 1 : -1)) % kPouchItems;
        changed = true;
    }
    if (i == 11 && (press[3] || press[4])) {   // (Movement speed: stops at 1x and 3x)
        link_speed.store(std::clamp(link_speed.load() + (press[4] ? 1 : -1), 0, kLinkSpeeds - 1));
        changed = true;
    }
    if (i == 6 && (press[3] || press[4])) {
        const int step = press[4] ? 1 : -1;
        pouch_delta = std::clamp(pouch_delta + step, -10, 10);
        if (!pouch_delta) pouch_delta = step;
        changed = true;
    }
    if (press[7] && i >= 2 && i <= 4) cheat_action.store(i == 4 ? 100 + clock_hour : i);
    if (press[7] && i == 6) cheat_action.store(200 + pouch_item * 32 + pouch_delta + 10);
    if ((press[3] || press[4] || press[7]) && i == 7) {   // (an On / Off as the first two: Left Off, Right On, confirm flips)
        free_camera.store(press[7] ? !free_camera.load() : press[4] ? 1 : 0);
        changed = true;
    }
    if (press[7] && i == 8) page = 3, teleport_follow = true, changed = true;
    if (press[7] && i == 10) page = 4, choose_inventory_filter(0), changed = true;
    if (i == 9 && (press[3] || press[4])) {   // (Kid | Adult: Left Kid, Right Adult, a switch when Link is the other age)
        const int age = link_age.load(std::memory_order_relaxed);
        if (age >= 0 && age != (press[4] ? 1 : 0)) {
            cheat_action.store(999);
            open_now = false;
            changed = true;
        }
    }
    if (press[7] && i == 9) {
        cheat_action.store(999);   // (host/hos_main.c OOT_AGE_ACTION)
        open_now = false;
        changed = true;
    }
}

/// (hookshot) The Game language row's choice written to language.txt once the player leaves the row (another row, page or
/// tab, or the menu closed), not at each step on the way to it. When it cannot be written (a read-only folder) the row goes
/// back to what language.txt says, so it never shows a language that was not saved
void game_lang_tick() {
    static const int row = [] {
        for (int i = 0; i < kRows; i++)
            if (rows[i].value == &opts.game_lang) return i;
        return -1;
    }();
    if (row < 0 || opts.game_lang == i18n::game_lang_index()) return;
    const bool on_row = open_now.load() && page == 0 && cur_tab == rows[row].tab &&
                        tab_row_to_global(cur_tab, tab_selected[cur_tab]) == row;
    if (on_row) return;
    if (!i18n::set_game_language(opts.game_lang)) {
        logf("menu: language.txt could not be written: the game language stays %s", i18n::game_lang_code(i18n::game_lang_index()));
        opts.game_lang = i18n::game_lang_index();
        menu_refresh = true;
    }
}

/// (hookshot) The screen the window is on, followed while the game runs (every 30 presents): moved to another monitor, or its
/// desktop size changed, the sizes it has that are not offered yet (its modes, its own size, the common sizes of their shapes)
/// join the Output resolution's choices after the player's own, so the numbers chosen keep their sizes; the Aspect ratio row
/// keeps the shape it is at (the list can gain one), and so do the run's start and the restart question's. HOS_DISPLAY_MODES:
/// the list as given
void outputs_follow_screen() {
    static int every = 0;
    static std::string followed_monitor;
    if (++every % 30) return;
    const std::string previous_monitor = followed_monitor;
    const int previous_pick = monitor_pick;
    refresh_monitors();
    const std::string current_monitor = monitor_choice::current_id(fullscreen_monitors);
    if (previous_pick != monitor_pick || previous_monitor != current_monitor) menu_refresh = true;
    if (getenv("HOS_DISPLAY_MODES")) return;
    uint32_t sw = 0, sh = 0;
    if (!screen_size(&sw, &sh) || (sw == outputs_screen.w && sh == outputs_screen.h && previous_monitor == current_monitor)) return;
    outputs_screen = {sw, sh};
    followed_monitor = current_monitor;
    const int slot = [] {
        for (const Row& r : rows)
            if (r.value == &opts.ultrawide) return restart_slot_of(r);
        return -1;
    }();
    // (the shapes the row's values name now: the same shapes after the list grows)
    const bool at_monitor = opts.ultrawide == aspect_monitor_value();
    const std::string now = aspect_shape(opts.ultrawide), started = aspect_shape(aspect_started),
                      restart_from = slot >= 0 ? aspect_shape(restart_state.start[slot]) : std::string();
    std::vector<dm::Size> modes = screen_modes();
    add_screen_size(modes, sw, sh);
    int added = 0;
    for (dm::Size s : dm::with_common(dm::offered(modes))) {
        const int before = last_choice();
        if (s.w == kGameOutput.w && s.h == kGameOutput.h) continue;
        const Out kept = custom_output;
        const int at = output_choice_of(s.w, s.h);
        custom_output = kept;   // (output_choice_of takes a size it does not have as the player's own: not this one)
        if (at == custom_index() && !(kept.w == s.w && kept.h == s.h)) output_extras.push_back({s.w, s.h}), added++;
        (void)before;
    }
    if (added) {
        for (Row& r : rows) {
            if (r.value == &opts.output_res) r.hi = last_choice();
            if (r.value == &opts.ultrawide) r.hi = aspect_last();
        }
        opts.ultrawide = at_monitor && !monitor_shape().empty() ? aspect_index(monitor_shape()) : aspect_index(now);
        aspect_started = aspect_index(started);
        if (slot >= 0) restart_state.restart_value(slot, aspect_index(restart_from));
        menu_refresh = true;
    }
    logf("vk: the window's screen is %ux%u (%s): %d sizes added to the Output resolution's", sw, sh,
         dm::ratio_name({sw, sh}).c_str(), added);
}

/* Called at tick exit, after every navigation/close path. Only an explicit button enables capture. */
void mic_test_tick(bool focused) {
    if (!focused || !open_now.load() || cur_tab != TAB_AUDIO || page != 0 || opts.mic == 0) mic_testing = false;
    mic_levels[0] = mic_levels[1] = 0;
    mic_test_state = host && host->mic_test ? host->mic_test(mic_testing, opts.microphone_gain, mic_levels) : 0;
    if (!(mic_test_state & 1)) mic_testing = false;
}
void menu_tick() {
    std::lock_guard lk(menu_mu);   // (the control bridge's settings: menu_setting_set)
    share_finish();   // (Save my pipeline list's worker, done)
    fullscreen_tick();
    game_lang_tick();
    outputs_follow_screen();
    enum { K_N = 19 };
    static bool held[K_N];
    static const int keys[K_N] = {VK_INSERT, VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_ESCAPE, VK_F1,   // (F1: for keyboards without Insert)
                                  VK_RETURN, VK_DELETE, VK_BACK,
                                  'Q', 'E', VK_TAB,   // (the tabs: Q and E, Tab and Shift+Tab)
                                  VK_PRIOR, VK_NEXT, VK_HOME, VK_END, VK_F10,   // (the long lists: a page, the ends)
                                  'J'};   // (the Tracker's Junk: kTrackerJunkPress)
    HWND fg = GetForegroundWindow();
    DWORD pid = 0;
    if (fg) GetWindowThreadProcessId(fg, &pid);
    const bool mine = pid == GetCurrentProcessId();
    struct MicTick { bool focused; ~MicTick() { mic_test_tick(focused); } } mic_tick{mine};
    bool press[K_N] = {};
    for (int i = 0; i < K_N; i++) {
        const bool down = mine && (GetAsyncKeyState(keys[i]) & 0x8000) != 0;
        const bool queued = host && host->take_key_press && host->take_key_press(keys[i]);
        // Read both keys even if one is disabled, so old presses cannot toggle the menu after a change.
        // (F1 always opens the menu; Menu shortcut's F1 only leaves Insert to an overlay)
        const bool enabled = keys[i] != VK_INSERT || opts.menu_shortcut != 1;   // (Insert: all but F1 only)
        press[i] = enabled && (host && host->take_key_press ? mine && queued : down && !held[i]);
        held[i] = down;
        if (press[i]) pad_last = false;   // (the keys: their names in the prompts)
    }
    // (hookshot) the gamepads, by position: Home, or Select and Start together, as Insert; the D-pad as the arrows; the
    // buttons the Switch's A and B are bound to as Enter and Esc, as in the game (vk_menu_keys.h; with the Nintendo layout A
    // is the right face button), not while a binding waits for its button
    static uint32_t pad_held = 0;
    const uint32_t raw = mine && host && host->pad_raw ? host->pad_raw() : 0, pad_press = raw & ~pad_held;
    const uint32_t chord = 1u << HOS_PAD_BACK | 1u << HOS_PAD_START;
    const bool chord_now = (raw & chord) == chord && (pad_held & chord) != chord;
    pad_held = raw;
    if (pad_press) pad_last = true;   // (a controller: its buttons in the prompts)
#ifndef VK_RSHIFT
#define VK_RSHIFT 0xA1
#endif
#ifndef VK_RCONTROL
#define VK_RCONTROL 0xA3
#endif
    const int tune_key = opts.compact_menu_key == 1 ? VK_RCONTROL : VK_RSHIFT;
    const int tune_parent_key = opts.compact_menu_key == 1 ? VK_CONTROL : VK_SHIFT;
    static bool tune_held = false, tune_cancelled = false;
    const bool tune_down = mine && (GetAsyncKeyState(tune_key) & 0x8000) != 0;
    if (host && host->take_key_press) {
        (void)host->take_key_press(tune_key);
        (void)host->take_key_press(tune_parent_key);
    }
    bool tune_release = false;
    if (tune_down && !tune_held) {
        tune_cancelled = false;
    } else if (!tune_down && tune_held) {
        if (!tune_cancelled && open_now.load() && page == 0 && listening == 0) tune_release = true;
    }
    tune_held = tune_down;
    if (!open_now.load() || page != 0 || listening != 0 || (tune_down && (GetAsyncKeyState(VK_TAB) & 0x8000)))
        tune_cancelled = true;
    if (tune_release) pad_last = false;
    {   // (RX_VK_UI_PROMPTS=pad or keys: the prompts for screenshots of test runs, which have no controller and no focus)
        static const char* force = getenv("RX_VK_UI_PROMPTS");
        if (force) pad_last = !strcmp(force, "pad");
    }
    auto pad = [&](int p) { return listening != 1 && (pad_press >> p & 1) != 0; };
    // (hookshot) a DualShock 4's or DualSense's touchpad click is F1: it opens and closes the menu as the key does
    if (pad(HOS_PAD_TOUCHPAD)) press[6] = true;
    if (host && host->binding)   // (A and B as bound now: the Controls page or the Layout preset can change them)
        menu_keys::confirm_back(host->binding(HOS_BIND_PAD, HOS_SW_A, 0), host->binding(HOS_BIND_PAD, HOS_SW_B, 0), &pad_confirm,
                                &pad_back);
    pad_paste = menu_keys::paste(pad_confirm, pad_back);   // (hookshot: a text field's paste, on a button neither is on)
    pad_junk = menu_keys::extra(host && host->binding ? host->binding(HOS_BIND_PAD, HOS_SW_Y, 0) : -1, pad_confirm, pad_back);
    if (pad(HOS_PAD_GUIDE) || chord_now) press[0] = true;
    {   // holding an arrow or the D-pad repeats it: after 0.35 s, 12 a second, then 30 a second after 1.5 s held
        static int64_t held_since[5], next_repeat[5];
        const int pads[5] = {0, HOS_PAD_UP, HOS_PAD_DOWN, HOS_PAD_LEFT, HOS_PAD_RIGHT};
        const int64_t t = prof_now();
        for (int i = 1; i <= 4; i++) {
            const bool down = held[i] || (open_now.load() && listening != 1 && (raw >> pads[i] & 1));
            if (!down) { held_since[i] = 0; continue; }
            if (!held_since[i]) { held_since[i] = t, next_repeat[i] = t + 350000000LL; continue; }
            if (t >= next_repeat[i] && open_now.load() && listening == 0) {
                press[i] = true;
                next_repeat[i] = t + (t - held_since[i] > 1500000000LL ? 33000000LL : 83000000LL);
            }
        }
    }
    if (open_now.load() && listening != 1) {
        press[1] |= pad(HOS_PAD_UP), press[2] |= pad(HOS_PAD_DOWN), press[3] |= pad(HOS_PAD_LEFT);
        press[4] |= pad(HOS_PAD_RIGHT), press[5] |= pad(pad_back), press[7] |= pad(pad_confirm);
        press[kTrackerJunkPress] |= pad(pad_junk);   // (the Tracker's Junk: the Switch's Y as bound)
    }
    std::vector<uint32_t> scripted;   // (hookshot: RX_VK_MENU_SCRIPT's typing, for the text field that has the keyboard)
    {   // RX_VK_MENU_SCRIPT (test runs, which never have the focus): timed menu keys, "<seconds>:<INS|UP|DOWN|LEFT|RIGHT|ESC|ENTER|TABL|TABR>,...";
        // and the gamepad's face buttons by position, PADS PADE PADW PADN (bottom, right, left, top), as a controller's press.
        // (hookshot) TYPE:<text> types the text up to the next comma, as the keyboard would; while a text field has the
        // keyboard ENTER, ESC, LEFT, RIGHT, HOME, END, BACK (Backspace) and DEL are its keys, and the pad's confirm and back too
        static const char* next = getenv("RX_VK_MENU_SCRIPT");
        static const int64_t start = prof_now();
        double at;
        char key[8];
        int n = 0;
        if (next && sscanf(next, "%lf:%7[A-Z]%n", &at, key, &n) == 2 && (prof_now() - start) / 1e9 >= at) {
            static const char* names[] = {"INS", "UP", "DOWN", "LEFT", "RIGHT", "ESC", "", "ENTER", "", "", "TABL", "TABR"};
            static const struct { const char* name; int vk; } edit_keys[] = {
                {"ENTER", VK_RETURN}, {"ESC", VK_ESCAPE}, {"LEFT", VK_LEFT}, {"RIGHT", VK_RIGHT}, {"HOME", VK_HOME},
                {"END", VK_END}, {"BACK", VK_BACK}, {"DEL", VK_DELETE}};
            if (!strcmp(key, "TYPE") && next[n] == ':') {
                const size_t len = strcspn(next + n + 1, ",");
                for (size_t i = 0; i < len; i++) scripted.push_back((unsigned char)next[n + 1 + i]);
                n += (int)len + 1;
            }
            for (const auto& k : edit_keys)
                if (editing && !strcmp(key, k.name)) scripted.push_back(HOS_TEXT_KEY | (uint32_t)k.vk);
            for (int i = 0; i < 12; i++) press[i] |= *names[i] && !strcmp(key, names[i]);
            static const char* pads[] = {"PADS", "PADE", "PADW", "PADN"};
            for (int p = 0; p < 4; p++)
                if (!strcmp(key, pads[p]) && open_now.load() && listening != 1) {
                    press[5] |= p == pad_back, press[7] |= p == pad_confirm;
                    press[kTrackerJunkPress] |= p == pad_junk;
                    if (editing && (p == pad_back || p == pad_confirm))
                        scripted.push_back(HOS_TEXT_KEY | (uint32_t)(p == pad_confirm ? VK_RETURN : VK_ESCAPE));
                    pad_last = true;
                }
            next = next[n] == ',' ? next + n + 1 : nullptr;
        }
    }
    // (hookshot) the text field that has the keyboard (editing): what was typed since the last frame, in order, and a paste asked
    // with the controller's paste button; the host is told whether one has it, so that the window takes text only then
    uint32_t typed[64];
    int typed_n = 0;
    const bool pasting = editing && open_now.load() && pad(pad_paste);
    if (host && host->take_text) typed_n = host->take_text(!editing ? HOS_TEXT_OFF : pasting ? HOS_TEXT_PASTE : HOS_TEXT_ON, typed, 64);
    if (editing && press[0] && !(pad(HOS_PAD_GUIDE) || chord_now)) press[0] = false;   // (Insert is the field's: Shift+Insert pastes)
    if (editing && (press[0] || press[6])) edit_end(false);   // (F1 or Home: the menu closes, the text as it was)
    // (the keyboard's Enter or Esc that ended an edit, as the menu's own press too: its queued press or its key state can come a
    // frame after the text's, and would open the field again or close the menu. Not taken until both keys are up, 50 ms on)
    static int64_t edit_keys_until = 0;
    if (edit_keys_until && (prof_now() < edit_keys_until || ((GetAsyncKeyState(VK_RETURN) | GetAsyncKeyState(VK_ESCAPE)) & 0x8000)))
        press[5] = press[7] = false;
    else edit_keys_until = 0;
    bool tab_left = press[10] || pad(HOS_PAD_LSHOULDER) || pad(HOS_PAD_LTRIGGER);
    bool tab_right = press[11] || press[12] || pad(HOS_PAD_RSHOULDER) || pad(HOS_PAD_RTRIGGER);
    if (press[12] && (GetAsyncKeyState(VK_SHIFT) & 0x8000)) tab_left = true, tab_right = false;
    bool changed = menu_refresh;
    menu_refresh = false;
    // (hookshot) the mouse, while the menu is open: the cursor in the window image's pixels (mx, my), tested against the
    // controls as last drawn (hits, vk_menu_hit.h), whether it moved since the last frame, and its clicks and wheel since then
    MkwVkPointer ptr{};
    int mx = -1, my = -1;
    bool mouse = false, moved = false;
    if (open_now.load() && host && host->pointer) {
        mouse = host->pointer(&ptr) != 0;
        int ix = 0, iy = 0;
        menu_hit::to_image(ptr.x, ptr.y, ptr.width, ptr.height, (int)dev.swap_extent.width, (int)dev.swap_extent.height,
                           &ix, &iy);
        if (mouse) mx = ix - (int)menu_ox, my = iy;   // (the menu's column's pixels: draw_menu)
        static int last_x = -1, last_y = -1;
        moved = mouse && mouse_read && (mx != last_x || my != last_y);   // (not the first read: a cursor resting over the
        last_x = mx, last_y = my, mouse_read = true;                     // menu as it opens leaves the selection alone)
        if (moved) pad_last = false;
        if (!mouse) ptr.pressed = 0, ptr.wheel = 0;
    }
    // (closing with a setting that takes a restart changed: the restart question first, Later already chosen on it)
    auto later = [&] {
        int now[mr::kMax];
        restart_values(now);
        restart_state.choose_later(now);
        open_now = false, page = 0, tune_mode = false, changed = true;
    };
    // (Menu shortcut "Insert, F1 or Esc", the default: Esc on a closed menu opens it, the keyboard's and RX_VK_MENU_SCRIPT's
    // ESC alone (the gamepad's back is Esc only while it is open, above). The press that opened it does not go back a page
    // below; with the compact menu key held it opens the compact bar, as Insert and F1 do (tune_mode). No
    // control can be bound to Esc, so nothing in play changes; the window gives the captured mouse back on the close)
    if (!preview_end && preview_end_asked()) preview_end = true, logf("menu: master quest preview over: its last page");
    if (preview_end) {   // (Mako) the preview's end: open on its page, nothing closes it
        press[0] = press[6] = press[5] = false;
        if (!open_now.load() || page != 6) open_now = true, page = 6, listening = 0, pending = nullptr, changed = true;
    }
    const bool esc_opens = opts.menu_shortcut == 2 && press[5] && !open_now.load();
    if (esc_opens) press[5] = false;
    const bool home_debug = press[15] && (!open_now.load() || (quick_debug && page == 0));
    if ((press[17] || home_debug) && !editing && !listening && !debug_warning && page != 5) {
        if (home_debug) press[15] = false;
        if (open_now.load() && quick_debug && page == 0) press[5] = true;
        else {
            quick_debug = true;
            tune_mode = false;
            open_now = true;
            page = 0;
            cur_tab = TAB_DEBUG;
            tab_selected[TAB_DEBUG] = 0;
            changed = true;
            press[5] = press[7] = false;
        }
    }
    if (quick_debug && page == 0) tab_left = tab_right = false;
    if ((press[0] || press[6]) && debug_warning) {
        debug_warning = false;
        changed = true;
    } else if ((press[0] || press[6]) && open_now.load() && page == 5) {
        later();
    } else if ((press[0] || press[6]) && open_now.load() && restart_ask()) {
        page = 5, ask_sel = 0, listening = 0, changed = true;
    } else if (press[0] || press[6] || esc_opens) {
        quick_debug = false;
        open_now = !open_now.load(), changed = true;
        if (open_now.load()) tune_mode = tune_down;
        else tune_mode = false;
        page = 0, listening = 0;
        // (the layout row shows the controls as they are: host/nn_hid.c keeps them, the ini's pad_ lines, and a saved
        // layout is not applied over them at start)
        if (open_now.load()) opts.pad_layout = detect_pad_layout();
        // (whether the Upscaler row can offer DLSS, FSR and XeSS here, and Frame generation by DLSS FG: asked once)
        if (open_now.load()) dlss_probe(), dlss_fg_probe(), fsr4_probe(), xess_probe();
        if (open_now.load()) refresh_mics();   // (the microphones as they are now)
        if (open_now.load()) refresh_outputs();
        if (open_now.load()) refresh_monitors();
    }
    if (open_now.load() && page == 6) {   // (Mako) the preview's end: its one button, a click or A / Enter
        if (mouse && (ptr.pressed & HOS_MOUSE_LEFT) && hits.at((float)mx, (float)my).part == menu_hit::kButton) press[7] = true;
        if (press[7]) {
            save();
            pipeline_cache_save(true);
            back_to_launcher();
            press[7] = false;
        }
    } else if (open_now.load() && debug_warning) {
        if (press[3] || press[4]) debug_warning_choice = 1 - debug_warning_choice, changed = true;
        if (mouse) {
            const auto hit = hits.at((float)mx, (float)my);
            if (hit.part == menu_hit::kButton && hit.index >= 0 && hit.index < 2 && (moved || ptr.pressed)) {
                debug_warning_choice = hit.index;
                changed = true;
                if (ptr.pressed & HOS_MOUSE_LEFT) press[7] = true;
            }
            if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
        }
        if (press[5] || press[7]) {
            if (!press[5] && debug_warning_choice != 0) {
                opts.debug_tools = 1;
                opts.transition_autosave = 0;
                sync_transition_autosave();
                save();
            }
            debug_warning = false;
            changed = true;
        }
    } else if (open_now.load() && editing) {   // (hookshot) a text field has the keyboard: the keys type into it (text_edit), nothing else
        int done = kTextGoOn;
        auto feed = [&](uint32_t in) {
            if (done == kTextGoOn) done = text_edit(*editing, in), edit_why = nullptr, changed = true;
        };
        if (!(GetAsyncKeyState(VK_RETURN) & 0x8000)) edit_enter_held = false;
        for (int i = 0; i < typed_n; i++)
            if (!edit_enter_held || typed[i] != (HOS_TEXT_KEY | VK_RETURN)) feed(typed[i]);
        if (done != kTextGoOn) edit_keys_until = prof_now() + 50000000LL;   // (the keyboard's Enter or Esc: above)
        for (const uint32_t in : scripted) feed(in);
        // (the controller edits without a keyboard; the D-pad's repeats use the existing repeat clock)
        const int pads[] = {HOS_PAD_UP, HOS_PAD_DOWN, HOS_PAD_LEFT, HOS_PAD_RIGHT};
        const int keys[] = {VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT};
        for (int i = 0; i < 4; i++)
            if (pad(pads[i]) || (press[i + 1] && (raw >> pads[i] & 1))) feed(HOS_TEXT_KEY | (uint32_t)keys[i]);
        if (pad(HOS_PAD_RSHOULDER)) feed(HOS_TEXT_KEY | VK_INSERT);
        if (pad(HOS_PAD_LSHOULDER)) feed(HOS_TEXT_KEY | (editing->caret < editing->len ? VK_DELETE : VK_BACK));
        if (pad(pad_confirm)) feed(HOS_TEXT_KEY | VK_RETURN);
        if (pad(pad_back)) feed(HOS_TEXT_KEY | VK_ESCAPE);
        if (mouse && done == kTextGoOn) {   // (a click elsewhere sets the text, a right click puts it back; no wheel scrolling)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            const bool on_field = hit.part == menu_hit::kRow && hit.index == tab_selected[cur_tab];
            if ((ptr.pressed & HOS_MOUSE_LEFT) && !on_field) done = kTextDone;
            if (ptr.pressed & HOS_MOUSE_RIGHT) done = kTextCancel;
        }
        if (done != kTextGoOn) edit_end(done == kTextDone), changed = true;
    } else if (open_now.load() && page == 5) {   // (hookshot) the restart question: Later (the default) or Restart now
        if (mouse) {   // (a button under the cursor chosen, a click on it pressed, a right click is Later; no list: the wheel does nothing)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            if (hit.part == menu_hit::kButton && (moved || ptr.pressed) && hit.index != ask_sel) ask_sel = hit.index, changed = true;
            if ((ptr.pressed & HOS_MOUSE_LEFT) && hit.part == menu_hit::kButton) press[7] = true;
            if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
        }
        if (press[1] || press[2] || press[3] || press[4] || tab_left || tab_right) ask_sel ^= 1, changed = true;
        if (press[5] || (press[7] && ask_sel == 0)) {
            later();
        } else if (press[7]) {   // (Restart now: everything saved, then the window closes as the player would close it)
            logf("menu: restart now, to apply %s", restart_list(", ").c_str());
            save();
            pipeline_cache_save(true);
            open_now = false, page = 0, tune_mode = false, changed = true;
            PostMessageA(app_window(), WM_APP + 9, 0, 0);
        }
    } else if (open_now.load() && page == 1) {   // (hookshot) the Controls page
        using enum menu_hit::CtlColumn;
        if (!can_bind()) {
            static int warned;
            if (!warned) warned = 1, logf("menu: the Controls page asked for the host's bindings and got none");
            page = 0;
        }
        else if (listening) {
            if (press[5] || prof_now() > listen_end) listening = 0, changed = true;   // (Esc, or nothing for a while)
            else if (listening == 1) {
                if (!listen_armed) listen_armed = (raw & ~(1u << HOS_PAD_GUIDE)) == 0;
                else if (const uint32_t p = pad_press & ~(1u << HOS_PAD_GUIDE) & ~(1u << HOS_PAD_TOUCHPAD)) {
                    int bit = 0;
                    while (!(p >> bit & 1)) bit++;
                    host->bind(HOS_BIND_PAD, controls[csel - kTop].button, ccol, bit);
                    listening = 0, changed = true;
                    opts.pad_layout = detect_pad_layout();
                    save();
                }
            } else {
                int down = 0;
                for (int k : bindable_keys())
                    if (mine && (GetAsyncKeyState(k) & 0x8000)) {
                        down = k;
                        break;
                    }
                if (!listen_armed) listen_armed = !down;
                else if (down) {
                    host->bind(HOS_BIND_KEY, controls[csel - kTop].button, 0, down);
                    host->bind(HOS_BIND_KEY, controls[csel - kTop].button, 1, 0);
                    listening = 0, changed = true;
                    save();
                }
            }
        } else {
            if (mouse) {   // (the mouse: the row under it selected, a click on a binding listens for its new input, on
                           // Reset resets; the wheel scrolls the page, a right click goes back)
                const menu_hit::Hit hit = hits.at((float)mx, (float)my);
                const bool option = hit.part == menu_hit::kCtlOption;
                const bool on = option || hit.part == menu_hit::kCtlRow || hit.part == menu_hit::kCtlCell;
                const int at = option ? hit.index : kTop + hit.index;   // (the page's row: its own rows first)
                if (on && (moved || ptr.pressed)) {
                    if (at != csel) csel = at, changed = true;
                    if (hit.part == menu_hit::kCtlCell && !keys_only(hit.index) && ccol != hit.side) ccol = hit.side, changed = true;
                }
                if (ptr.pressed & HOS_MOUSE_LEFT) {
                    if (option) press[hit.side < 0 ? 3 : 4] = true;   // (a value's halves: Left and Right; the name: Right)
                    else if (hit.part == menu_hit::kCtlCell || (hit.part == menu_hit::kCtlRow && hit.index == kControls))
                        press[7] = true;   // (as Enter)
                }
                if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;
                if (ptr.wheel) wheel_rows[kControlsSlot] += ptr.wheel, changed = true;   // (scrolls; the selection stays)
            }
            const int n = kTop + kControls + 1;
            if (press[1]) csel = (csel + n - 1) % n, changed = true;
            if (press[2]) csel = (csel + 1) % n, changed = true;
            const int i = csel - kTop;   // (i: the control's, or reset's)
            if (press[5]) page = 0, changed = true;
            else if (i < 0 && (press[3] || press[4] || press[7])) {   // (the page's own rows: Enter as Right)
                Row& r = rows[tab_row_to_global(TAB_PAGE, csel)];   // (Custom is only what the bindings are: set_row skips it)
                set_row(r, *r.value + (press[3] ? -r.step : r.step), press[3] ? -1 : 1);
                changed = true;
            } else if (i >= 0) {
                const int columns = i < kControls && controls[i].button < HOS_SW_N &&
                                    controls[i].button != HOS_SW_PLUS && controls[i].button != HOS_SW_MINUS ? kCtlColumns : kCtlToggle;
                if (ccol >= columns) ccol = kCtlKeyboard;   // (no toggle on pause, map, stick directions or ocarina notes)
                if ((press[3] || press[4]) && i < kControls && !keys_only(i)) {
                    ccol = (ccol + columns + (press[3] ? -1 : 1)) % columns;
                    changed = true;
                }
                const int col = keys_only(i) ? kCtlKeyboard : ccol;
                if (press[7]) {
                    if (i == kControls) {
                        host->bind(HOS_BIND_PAD, -1, 0, 0);
                        opts.pad_layout = 0;
                        opts.hold_toggle = 0;
                        save();
                    }
                    else if (col == kCtlToggle) {
                        opts.hold_toggle ^= 1 << controls[i].button;
                        save();
                    }
                    else listening = col == kCtlKeyboard ? 2 : 1, listen_armed = false, listen_end = prof_now() + 6000000000LL;
                    changed = true;
                }
                if ((press[8] || press[9]) && i < kControls) {
                    if (col == kCtlToggle) opts.hold_toggle &= ~(1 << controls[i].button);
                    else if (col != kCtlKeyboard) {
                        host->bind(HOS_BIND_PAD, controls[i].button, col, -1);
                        opts.pad_layout = detect_pad_layout();
                    }
                    else for (int k = 0; k < 2; k++) host->bind(HOS_BIND_KEY, controls[i].button, k, 0);
                    changed = true;
                    save();
                }
            }
        }
    } else if (open_now.load() && page == 4) {   // the inventory
        const int chosen = item_choice;   // (the page follows the choice when it moves; the wheel's page stays otherwise)
        if (mouse) inventory_mouse(ptr, mx, my, press, changed);
        if (press[5] && inventory_amount) inventory_amount = false, changed = true;   // (back: out of the amount first)
        else if (press[5]) page = 0, changed = true;   // (to the Debug tab, Inventory still selected)
        else if (tab_left || tab_right) {   // (another section, from editing an amount too: that ends)
            const int filters = kItemSections + 1;
            choose_inventory_filter((inventory_filter + filters + (tab_left ? -1 : 1)) % filters);
            changed = true;
        } else if (inventory_amount) {
            if (press[7]) inventory_amount = false, changed = true;
            else if (press[3] || press[4]) cheat_action.store(OOT_CHEAT_ITEM_ACTION + item_choice * 256 + 64 + (press[4] ? 1 : -1));
        } else {
            // (the cards as drawn, inventory_columns to a row: the arrows move, Page Up and Down a page, Home and End the ends)
            const int begin = inventory_begin(), end = inventory_end();
            const int step = (press[4] - press[3]) + (press[2] - press[1]) * inventory_columns + (press[14] - press[13]) * inventory_capacity;
            if (step || press[15] || press[16]) {
                item_choice = press[15] ? begin : press[16] ? end - 1 : std::clamp(item_choice + step, begin, end - 1);
                inventory_reveal();
                changed = true;
            } else if (press[7] && item_counts[item_choice].load(std::memory_order_relaxed) >= 0) {
                if (item_kinds[item_choice]) inventory_amount = true, changed = true;   // (an amount: Left and Right change it)
                else cheat_action.store(OOT_CHEAT_ITEM_ACTION + item_choice * 256 + 200);   // (unlock or relock)
            }
            if (item_choice != chosen) inventory_reveal();   // (a click on a card: its page)
        }
    } else if (open_now.load() && page == 3) {   // the teleport list
        if (mouse) teleport_mouse(ptr, mx, my, press, changed);
        if (press[5]) page = 0, changed = true;   // (to the Debug tab, Teleport still selected)
        else if (press[7]) {
            cheat_action.store(1000 + teleport_choice);
            open_now = false, page = 0;   // (back to the game: the map change starts with an event)
            changed = true;
        } else if (tab_left || tab_right) {   // (the first map of the previous or next section)
            const int section = (teleport_section_of(teleport_choice) + kTeleportSections + (tab_left ? -1 : 1)) % kTeleportSections;
            teleport_choice = teleport_sections[section].first, teleport_follow = true;
            changed = true;
        } else {
            // (the cards as drawn, each section's in rows under its heading: Up and Down a row, the column kept; Left and Right the
            // previous and next card; Page Up and Down the rows that fit; Home and End the ends)
            const int rows = (press[2] - press[1]) + (press[14] - press[13]) * teleport_page_rows;
            const int was = teleport_choice;
            if (press[15]) teleport_choice = 0;
            else if (press[16]) teleport_choice = kTeleports - 1;
            else teleport_choice = std::clamp(teleport_step_rows(teleport_choice, rows) + (press[4] - press[3]), 0, kTeleports - 1);
            if (teleport_choice != was) teleport_follow = true, changed = true;
        }
    } else if (open_now.load()) {
        if (mouse) {   // (the mouse: see the top of this file)
            const menu_hit::Hit hit = hits.at((float)mx, (float)my);
            const int ht = hit.part == menu_hit::kTab ? hit.index : hit.part == menu_hit::kTabPrev ? TAB_COUNT
                         : hit.part == menu_hit::kTabNext ? TAB_COUNT + 1 : -1;
            if (ht != hover_tab) hover_tab = ht, changed = true;
            int& sel = tab_selected[cur_tab];
            const bool on_row = hit.part == menu_hit::kRow || hit.part == menu_hit::kSlider;
            if (drag_row >= 0) {   // (a slider held: it follows the cursor's x until let go)
                Row& d = rows[tab_row_to_global(cur_tab, drag_row)];
                if (!(ptr.held & HOS_MOUSE_LEFT) || !d.value) {
                    drag_row = -1;
                    save();
                } else {
                    const int permille = hits.drag((float)mx, drag_row);
                    const int v = permille < 0 ? *d.value : menu_hit::slider_value(permille, d.lo, d.hi, d.step);
                    if (v != *d.value) set_row(d, v, v > *d.value ? 1 : -1, false), changed = true;
                }
            } else if (on_row && (moved || ptr.pressed) && hit.index != sel) {
                // (the row under the cursor is in view already: no scrolling to it. Brought into view as the keys' choice
                // is, with its row of context, the top row slid down under a cursor that stayed put, and the next click took
                // the row above: picking the Upscaler changed the Output resolution, and the menu asked to restart)
                sel = hit.index, scrolled_to[cur_tab] = sel, changed = true;
            }
            if ((ptr.pressed & HOS_MOUSE_LEFT) && drag_row < 0) {
                if (hit.part == menu_hit::kTabPrev) tab_left = true;
                else if (hit.part == menu_hit::kTabNext) tab_right = true;
                else if (hit.part == menu_hit::kTab && hit.index != cur_tab) cur_tab = hit.index, changed = true;
                else if (hit.part == menu_hit::kSlider) {
                    Row& d = rows[tab_row_to_global(cur_tab, hit.index)];
                    drag_row = hit.index;
                    const int v = menu_hit::slider_value(hit.permille, d.lo, d.hi, d.step);
                    if (v != *d.value) set_row(d, v, v > *d.value ? 1 : -1, false);
                    changed = true;
                } else if (hit.part == menu_hit::kRow) {
                    Row& d = rows[tab_row_to_global(cur_tab, hit.index)];
                    if (!d.value && d.cheat >= 0 && (cheat_chooses(d.cheat) || age_shown(d.cheat) || d.cheat <= 1 || d.cheat == 7) &&
                        hit.side != 0)
                        press[hit.side < 0 ? 3 : 4] = true;   // (a tool's choice: its halves as Left and Right)
                    else if (d.tracker >= 0) {   // (a Tracker row: its value's halves step its checks, its name goes to the one shown)
                        if (hit.side != 0) press[hit.side < 0 ? 3 : 4] = true;
                        else if (tracker_pick[d.tracker]) press[7] = true;   // (the first row's name does nothing: the record is not forgotten by a click)
                    } else if (!d.value) press[7] = true;   // (a page, a tool: as Enter)
                    else switch (menu_hit::row_click(true, d.hi - d.lo == d.step, hit.side, *d.value == d.hi)) {
                    case menu_hit::kClickConfirm: press[7] = true; break;
                    case menu_hit::kClickRight: press[4] = true; break;     // (the right half as Right; a toggle's other half flips it)
                    case menu_hit::kClickLeft: press[3] = true; break;      // (the left half as Left)
                    case menu_hit::kClickSelect: break;   // (the name, or a toggle's half already chosen: selected above, the value as it is)
                    }
                }
            }
            if (ptr.pressed & HOS_MOUSE_RIGHT) press[5] = true;   // (as Esc)
            // (the wheel scrolls the rows, wherever the cursor is; it never changes a value, the selection or the tab: the
            // values change by a click on their arrows or halves, a slider's drag, Left and Right, A and Enter)
            if (ptr.wheel && drag_row < 0) wheel_rows[cur_tab] += ptr.wheel, changed = true;
        }
        if (tune_down && (press[12] || tab_left || tab_right || press[1] || press[2] || press[3] || press[4] || press[5] || press[7] || ptr.pressed))
            tune_cancelled = true;
        // (the randomizer's fork: on the Tracker tab the left face button is the Tracker's Junk when the Switch's Y is bound
        //  there, as on an Xbox controller: pressed, it marked the check and also switched to the compact bar, seen in play
        //  2026-11-18. There it is Junk's alone; the compact menu key still switches)
        const bool west_is_junk = cur_tab == TAB_TRACKER && pad_junk == HOS_PAD_WEST;
        const bool tune_toggle = tune_release || (pad(HOS_PAD_WEST) && !west_is_junk);
        if (tune_toggle && listening == 0) tune_mode = !tune_mode, changed = true;
        if (press[5] && cur_tab == TAB_MOTION) cur_tab = TAB_CONTROLS, press[5] = false, changed = true;   // (back)
        if (press[5] && cur_tab == TAB_FPS_DEV) cur_tab = TAB_GAMEPLAY, press[5] = false, changed = true;   // (back)
        if (press[5] && pending) pending = nullptr, changed = true;   // (a Restart or Quit waiting for its second press: cancelled)
        else if (press[5] && cur_tab == TAB_MOTION) cur_tab = TAB_CONTROLS, press[5] = false, changed = true;   // (back)
        else if (press[5] && cur_tab == TAB_FPS_DEV) cur_tab = TAB_GAMEPLAY, press[5] = false, changed = true;   // (back)
        else if (press[5] && restart_ask()) page = 5, ask_sel = 0, changed = true;   // (the restart question first)
        else if (press[5]) open_now = false, tune_mode = false, quick_debug = false;
        // (the tabs: LB and RB, Q and E, or Tab; from the Motion page, as from Controls)
        if ((tab_left || tab_right) && cur_tab == TAB_MOTION) cur_tab = TAB_CONTROLS;
        const int tabs = tabs_shown();   // (without the Tracker outside the randomizer)
        if ((tab_left || tab_right) && cur_tab == TAB_FPS_DEV) cur_tab = TAB_GAMEPLAY;
        if (tab_left) cur_tab = (std::min(cur_tab, tabs - 1) + tabs - 1) % tabs, changed = true;
        else if (tab_right) cur_tab = (cur_tab + 1) % tabs, changed = true;
        const int tab_count = tab_row_count(cur_tab);
        int& selected = tab_selected[cur_tab];
        if (selected >= tab_count) selected = tab_count - 1;   // (a row gone since: the debug tools turned off, HDR turned off: row_shown)
        auto heading_at = [&](int k) { return rows[tab_row_to_global(cur_tab, k)].heading; };   // (stepped over)
        if (heading_at(selected)) selected = (selected + 1) % tab_count;
        if (cur_tab == TAB_DEBUG && (press[1] || press[2])) {   // (the Debug tab: in its layout's order, debug_rows)
            selected = debug_step(selected, press[2] ? 1 : -1);
            changed = true;
        } else {
            if (press[1]) {
                do selected = (selected + tab_count - 1) % tab_count;
                while (heading_at(selected));
                changed = true;
            }
            if (press[2]) {
                do selected = (selected + 1) % tab_count;
                while (heading_at(selected));
                changed = true;
            }
        }
        Row& r = rows[tab_row_to_global(cur_tab, selected)];
        const bool confirm_selected = &r == &rows[kQuitRow] || &r == &rows[kRestartRow];
        if (pending && (pending != &r || !mine)) pending = nullptr, changed = true;
        if (press[7] && confirm_selected) {
            if (mine && !press[5]) {
                if (pending != &r) {
                    pending = &r, changed = true;
                } else {   // (as Restart now: saved first, as the window's own close does not force the pipeline cache)
                    save();
                    pipeline_cache_save(true);
                    pending = nullptr;
                    if (&r == &rows[kRestartRow]) {   // (the restart question's Restart now: the window closes, then the game starts again)
                        logf("menu: restart");
                        open_now = false, changed = true;
                        if (const HWND window = app_window()) PostMessageA(window, WM_APP + 9, 0, 0);
                    } else if (const HWND window = app_window()) {
                        PostMessageA(window, WM_CLOSE, 0, 0);
                    }
                }
            }
        } else if (r.cheat >= 0) cheat_press(r.cheat, press, changed);   // (a debug tool: on the Debug tab itself)
        else if (press[7] && !strcmp(r.name, "Test microphone")) {
            if (opts.mic != 0 && host && host->mic_test) mic_testing = !mic_testing;
            press[7] = false, changed = true;
        }
        else if (r.tracker >= 0) tracker_press(r.tracker, press, changed);
        else if (press[7] && is_motion_row(r)) cur_tab = TAB_MOTION, tab_selected[TAB_MOTION] = 0, press[7] = false, changed = true;
        else if (press[7] && is_fps_dev_row(r)) cur_tab = TAB_FPS_DEV, tab_selected[TAB_FPS_DEV] = 0, press[7] = false, changed = true;
        else if (press[7] && is_share_row(r)) share_pipeline_list(), press[7] = false, changed = true;
        else if (press[7] && is_laptop_row(r)) weak_laptop_apply(), press[7] = false, changed = true;
        else if (press[7] && &r == &rows[kBugReportRow]) bug_report_save(), press[7] = false, changed = true;
        else if (const FieldRow* f = press[7] ? field_row(r) : nullptr) edit_start(*f->field, f->apply), changed = true;   // (hookshot)
        else if (press[7] && !r.value && r.tracker < 0 && can_bind()) page = 1, csel = 0, ccol = menu_hit::kCtlPrimary, changed = true;
        if ((press[3] || press[4] || press[7]) && r.value) {   // (Enter, or A, as Right)
            if (press[7]) press[4] = true;
            set_row(r, *r.value + (press[4] ? r.step : -r.step), press[4] ? 1 : -1);
            changed = true;
        }
        const int64_t now = prof_now();
        if (changed) {   // (a new row or value: its name from the start, after a rest)
            marquee_pos = 0, marquee_next = now + kMarqueeRest;
        } else if (marquee_max > 0 && now >= marquee_next) {
            if (marquee_pos >= marquee_max) marquee_pos = 0, marquee_next = now + kMarqueeRest;   // (back to the start)
            else if (++marquee_pos >= marquee_max) marquee_next = now + kMarqueeRest;            // (rest at the end)
            else marquee_next = now + kMarqueeStep;
            changed = true;
        }
    }
    {   // (hookshot) the window lets the mouse go while the menu is open, and takes it back after (host/display.c)
        static bool told = false;
        const bool now_open = open_now.load();
        if (!now_open) {
            tune_mode = false;
            if (drag_row >= 0) save();   // (a slider let go off the window: kept now)
            hover_tab = -1, drag_row = -1, mouse_read = false;
            pending = nullptr;
            edit_end(false);   // (hookshot: a text field being edited, its text as it was)
        }
        if (now_open != told && app_window()) {
            told = now_open;
            PostMessageA(app_window(), WM_APP + 8, (WPARAM)now_open, (LPARAM)(now_open && esc_opens));
        }
    }
    fps_level_now.store(fps_stats::level_of(opts.show_fps), std::memory_order_relaxed);   // (what vk_fps.cpp measures)
    if (opts.show_fps) {
        static int64_t next = 0, last_game = 0, last_shown = 0;
        const int64_t now = prof_now();
        double shown = 0, game = 0;
        if (fps_take(now, shown_frames.load(), game_frames.load(), &next, &last_shown, &last_game, &shown, &game)) {
            snprintf(fps_text, sizeof fps_text, "%.0f", shown);
            fps_rate_now = opts.framegen >= 1 ? game : shown;   // (the game's own against its cap, with frame generation too)
            // (the game's own rate, "Base", and who makes the frames: DLSS FG, FSR 3.1 FG or Built-in FG, or DLSS FG paused)
            const char* who = framegen_maker_name();
            if (opts.framegen >= 1 && who) snprintf(fps_sub, sizeof fps_sub, "Base %.0f, %s", game, who);
            else if (opts.framegen >= 1) snprintf(fps_sub, sizeof fps_sub, "Base %.0f", game);
            else fps_sub[0] = 0;
            // (in the menu's language: the counter draws with Tab, past ui::'s translation, so it is put in here)
            if (const char* t = i18n::tr(fps_sub); t != fps_sub) snprintf(fps_sub, sizeof fps_sub, "%s", t);
        }
        static int64_t texts_next = 0;   // (the lines past the number: four times a second, each over the last half second)
        if (now >= texts_next) texts_next = now + fps_stats::kSecond / 4, fps_texts(now);
    }
    if (opts.resource_monitor && perf_monitor_sample()) perf_new = true;   // (Mako: drawn by draw_perf)
}

void menu_record(VkCommandBuffer cmd, uint32_t index, uint32_t w, uint32_t h) {
    const bool start = startup_on.load(std::memory_order_acquire);
    const bool fps = (opts.show_fps || opts.resource_monitor) && !start;   // (no game frames yet: not "0 FPS" over the start-up screen)
    const bool open = open_now.load(std::memory_order_relaxed);
    if (!start && !fps && !open) {   // (nothing shows: no ImGui frame, no render pass)
        // (but a new window size or Menu size since the last bake: one frame with nothing drawn that bakes the menu's glyphs
        // and measures its page for the new size, so the next open has no hitch whatever was resized while nothing showed)
        if (prebake_needed(w, h) && ui::begin(w, h)) {
            ui::Ctx c = ui_ctx(w, h);
            prebake(c);
            ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly, its backend through its own pointers: what this thread recorded through vk_work.h reaches cmd first)
            ui::record(cmd, index, w, h);
            return;
        }
        ui::idle();
        return;
    }
    if (!ui::begin(w, h)) return;
    {   // (the easing's step: the time since the last drawing, a quarter of the way in 1/60 s)
        static int64_t last = 0;
        const int64_t now = prof_now();
        ease_step = last ? std::min(1.0f, (float)((now - last) / 1e9) * 15.0f) : 1.0f;
        last = now;
    }
    ui::Ctx c = ui_ctx(w, h);
    prebake(c);   // (the menu's glyphs at this size, before it opens: no hitch then)
    if (start) draw_startup(c);   // (under the menu)
    if (opts.resource_monitor && !start && !open) draw_perf(c);   // (Mako)
    if (open) draw_menu(c);
    if (fps) draw_fps(c, open);
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly, its backend through its own pointers: what this thread recorded through vk_work.h reaches cmd first)
    ui::record(cmd, index, w, h);
}

void menu_record_image(VkCommandBuffer cmd, VkImage image, VkImageView view, uint32_t w, uint32_t h) {
    const bool open = open_now.load(std::memory_order_relaxed);
    const bool fps = opts.show_fps && !startup_on.load(std::memory_order_acquire);
    if (!open && !fps) return;
    if (!ui::begin(w, h)) return;
    ui::Ctx c = ui_ctx(w, h);
    if (open) draw_menu(c);
    if (fps) draw_fps(c, open);
    ::mkwvk::rec::boundary(::mkwvk::rec::B_DIRECT);   // (Dear ImGui records into cmd directly, its backend through its own pointers: what this thread recorded through vk_work.h reaches cmd first)
    ui::record_to(cmd, image, view, w, h);
}

} // namespace mkwvk
