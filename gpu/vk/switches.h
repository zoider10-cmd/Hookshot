// (hookshot) The renderer's switches, in one table (switches.def): every RX_ name the renderer or the host reads from the
// environment, what kind of switch it is, what it does unset and what setting it does. The reads stay where they are used;
// tests/test_switch_table.py fails on a name read in the source that the table does not have, on a row nothing reads, and on a
// removed name that is still read. At the start the renderer says which switches the run has set (switches::report): a log
// then shows how far a run is from the defaults, a name that is no switch (a typo, or one from another build) is said so
// instead of doing nothing silently, and a removed one says what became of it.
//
// The kinds:
//   diag    logging, statistics, dumps, self-checks, fault injection: nothing for a run that does not set it
//   tune    a number with one built-in default for every PC
//   kill    turns off, or back to an older way, something that is on for every PC
//   attempt turns on something that is off for every PC: an experiment nobody ships
//   hw      unset, it follows the PC: the GPU's vendor or driver, its VRAM, the CPU count, the OS
//   player  a setting the player has (the Insert menu, hookshot_options.ini), or one the launcher or the Builder sets
//
// A new switch needs a row here. A switch that is done with goes: its reads are deleted and its row becomes GONE(name, since,
// what became of it), so a run that still sets it is told. Plain code with no Vulkan calls: the test compiles it alone.
#pragma once

#include <cstddef>
#include <cstring>
#include <string>

namespace mkwvk::switches {

enum class Kind { diag, tune, kill, attempt, hw, player };
inline const char* kind_name(Kind k) {
    static const char* const names[] = {"diag", "tune", "kill", "attempt", "hw", "player"};
    return names[(int)k];
}

struct Row {
    const char* name;
    Kind kind;
    const char* type;      // (bool, int, float, string or enum)
    const char* unset;     // (what the renderer does with it unset; for hw, the rule)
    const char* summary;   // (what setting it does)
};
struct Gone {
    const char* name;
    const char* since;     // (the day its reads were deleted, YYYY-MM-DD)
    const char* became;    // (what a run that set it gets now)
};

// (sorted by name: find() is a binary search, and the test checks the order)
inline constexpr Row rows[] = {
#define SW(name, kind, type, unset, summary) {#name, Kind::kind, #type, unset, summary},
#define GONE(name, since, became)
#include "switches.def"
#undef SW
#undef GONE
};
inline constexpr Gone gone[] = {
#define SW(name, kind, type, unset, summary)
#define GONE(name, since, became) {#name, since, became},
#include "switches.def"
#undef SW
#undef GONE
    {nullptr, nullptr, nullptr},   // (the end; so the array is never empty)
};
inline constexpr size_t row_count = sizeof rows / sizeof rows[0];

/// The switch's row; nullptr when the table has none of that name
inline const Row* find(const char* name) {
    size_t lo = 0, hi = row_count;
    while (lo < hi) {
        const size_t mid = lo + (hi - lo) / 2;
        const int c = std::strcmp(rows[mid].name, name);
        if (!c) return &rows[mid];
        if (c < 0) lo = mid + 1;
        else hi = mid;
    }
    return nullptr;
}
/// A removed switch's entry; nullptr when the name is none
inline const Gone* find_gone(const char* name) {
    for (const Gone* g = gone; g->name; g++)
        if (!std::strcmp(g->name, name)) return g;
    return nullptr;
}
/// Whether an environment name is the renderer's to answer for: RX_ and what follows
inline bool ours(const char* name, size_t len) { return len > 3 && !std::strncmp(name, "RX_", 3); }

/// What the run has set, said through log(const char* line): one line naming every switch set with its value and kind
/// ("vk: switches set (2): RX_VK_ASYNC=0 (hw), RX_VK_DRAW_STATS=1 (diag)", or "vk: switches set: none"), then one line for
/// each RX_ name that is set and is no switch: a removed one with what became of it, another as not a switch of this build.
/// env: the environment's entries, "NAME=value", ended by a nullptr (environ). A value that names a file or folder is said as
/// "<a path>", and another is cut at 48 characters. Returns how many names were set that are no switch.
template <class Log> int report(const char* const* env, Log log) {
    std::string set;
    int n_set = 0, strangers = 0;
    for (const char* const* e = env; e && *e; e++) {
        const char* eq = std::strchr(*e, '=');
        if (!eq || !ours(*e, (size_t)(eq - *e))) continue;
        const std::string name(*e, (size_t)(eq - *e));
        if (const Row* r = find(name.c_str())) {
            std::string value(eq + 1);
            if (value.find_first_of("/\\") != std::string::npos) value = "<a path>";   // (a log is shared: no folder names)
            else if (value.size() > 48) value = value.substr(0, 45) + "...";
            set += (n_set++ ? ", " : "") + name + "=" + value + " (" + kind_name(r->kind) + ")";
        } else if (const Gone* g = find_gone(name.c_str())) {
            strangers++;
            log(("vk: " + name + " is set, and is no longer a switch (since " + g->since + "): " + g->became).c_str());
        } else {
            strangers++;
            log(("vk: " + name + " is set, and is not a switch of this build: a misspelt name, or one from another build").c_str());
        }
    }
    if (n_set) log(("vk: switches set (" + std::to_string(n_set) + "): " + set).c_str());
    else log("vk: switches set: none");
    return strangers;
}

} // namespace mkwvk::switches
