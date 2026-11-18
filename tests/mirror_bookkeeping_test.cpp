// tests/test_mirror_bookkeeping.py puts vk_memory.cpp's bookkeeping for the mirrors' write-backs where ACTUAL is: the
// replay's own report words (memory_cpu_owned) and the pages the CPU wrote (shadow_written_to and its callers).
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <vector>

#define CHECK(c)                                                           \
    do {                                                                   \
        if (!(c)) {                                                        \
            std::fprintf(stderr, "%s:%d: not true: %s\n", __FILE__, __LINE__, #c); \
            std::exit(1);                                                  \
        }                                                                  \
    } while (0)

static bool mirrors = false;
static int guest_lookups = 0;
bool mirror_on() { return mirrors; }
bool wb_diff_on() { return true; }
bool env_on(const char*) { return false; }
constexpr int kPageShift = 12;
struct Host {
    uint64_t (*gpu_guest)(uint64_t);
};
static uint64_t same_address(uint64_t a) {
    guest_lookups++;
    return a;
}
static Host host_stand_in{same_address};
static Host* host = &host_stand_in;

/* ACTUAL */

int main() {
    const uint32_t pages[3] = {1, 2, 3};

    // no mirrors (an integrated GPU, RX_VK_MIRROR=0): no write-back will ever read any of it, so none of it is kept
    mirrors = false;
    for (int i = 0; i < 100000; i++) memory_cpu_owned(0x10000 + 16 * (uint64_t)i, 16);
    CHECK(cpu_words_new.empty() && cpu_words.empty() && cpu_words_recent.empty());
    shadow_written(pages, 3);
    shadow_written_collected(pages, 3);
    guest_cpu_wrote(0x5000, 8192);
    CHECK(shadow_written_pages.empty() && shadow_written_collected_list.empty() && shadow_written_by_replay.empty());
    CHECK(!shadow_written_all);
    CHECK(guest_lookups == 0);   // (nor are the pages of the replay's own writes looked up)

    // mirrors: as before
    mirrors = true;
    memory_cpu_owned(0x10000, 16);
    CHECK(cpu_words_new.size() == 2 && cpu_words_new[0] == 0x10000 && cpu_words_new[1] == 0x10008);
    memory_cpu_owned(0, 16);   // (no guest address: nothing)
    CHECK(cpu_words_new.size() == 2);
    shadow_written(pages, 3);
    shadow_written_collected(pages, 2);
    guest_cpu_wrote(0x5000, 8192);
    CHECK(shadow_written_pages.size() == 3 && shadow_written_collected_list.size() == 2);
    CHECK(shadow_written_by_replay.size() == 2 && shadow_written_by_replay[0] == 5 && shadow_written_by_replay[1] == 6);
    CHECK(guest_lookups == 2);
    std::puts("mirror bookkeeping: ok");
    return 0;
}
