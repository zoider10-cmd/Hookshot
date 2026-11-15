// The commit Windows still has room for (gpu/vk/commit_room.h): tests/test_commit_room.py compiles and runs this.
#include "../gpu/vk/commit_room.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)

namespace {
const uint64_t MB = 1ull << 20, GB = 1ull << 30, kPage = 4096;
using commit_room::PageFile;

/// The textures' budget after the commit rule (vk_texture.cpp): below the reserve the shortfall comes off what they hold
uint64_t budget_after(uint64_t textures, uint64_t reserve, uint64_t room) {
    return room < reserve ? (textures > reserve - room ? textures - (reserve - room) : 0) : textures;
}

/// What SystemPageFileInformationEx writes: a record, then its name, the next record 8-aligned after it
struct Query {
    alignas(16) unsigned char buf[4096] = {};
    size_t len = 0, last = 0;
    void add(uint32_t total, uint32_t min_size, uint32_t max_size, const char16_t* name, bool name_inside = true) {
        if (len) {
            commit_room::Record prev;
            std::memcpy(&prev, buf + last, sizeof prev);
            prev.next = (uint32_t)(len - last);
            std::memcpy(buf + last, &prev, sizeof prev);
        }
        size_t chars = 0;
        while (name[chars]) chars++;
        commit_room::Record r{};
        r.total = total, r.in_use = total / 2, r.peak = total, r.min_size = min_size, r.max_size = max_size;
        r.name_bytes = (uint16_t)(chars * 2), r.name_room = (uint16_t)(chars * 2 + 2);
        r.name = name_inside ? (uint64_t)(uintptr_t)(buf + len + sizeof r) : (uint64_t)(uintptr_t)name;
        std::memcpy(buf + len, &r, sizeof r);
        std::memcpy(buf + len + sizeof r, name, chars * 2 + 2);
        last = len;
        len = (len + sizeof r + chars * 2 + 2 + 7) & ~(size_t)7;
    }
};
}

int main() {
    using namespace commit_room;
    const auto free_100 = [](char) -> uint64_t { return 100 * GB; };

    // (a file Windows manages on a 32 GB PC: 2 GB now, up to 96 GB, 100 GB free on its drive)
    const PageFile managed{2 * GB, 96 * GB, 'C'};
    CHECK(growth(&managed, 1, free_100) == 94 * GB);
    // (no further than the drive has free)
    CHECK(growth(&managed, 1, [](char) -> uint64_t { return 10 * GB; }) == 10 * GB);
    CHECK(growth(&managed, 1, [](char) -> uint64_t { return 0; }) == 0);
    // (a file of a fixed size, or one at its maximum, or above it: nothing)
    const PageFile fixed{16 * GB, 16 * GB, 'C'}, above{20 * GB, 16 * GB, 'C'};
    CHECK(growth(&fixed, 1, free_100) == 0);
    CHECK(growth(&above, 1, free_100) == 0);
    // (a file whose drive is not known: nothing, and its drive is not asked for)
    const PageFile unknown{2 * GB, 96 * GB, 0}, odd{2 * GB, 96 * GB, '?'};
    int asked = 0;
    const auto counting = [&](char) -> uint64_t { asked++; return 100 * GB; };
    CHECK(growth(&unknown, 1, counting) == 0 && growth(&odd, 1, counting) == 0 && asked == 0);
    CHECK(growth(nullptr, 0, counting) == 0 && asked == 0);
    // (two files on one drive share its free space, which is read once; a file on another drive has its own)
    const PageFile two[] = {{2 * GB, 8 * GB, 'C'}, {1 * GB, 9 * GB, 'C'}, {1 * GB, 4 * GB, 'D'}};
    asked = 0;
    CHECK(growth(two, 2, [&](char) -> uint64_t { asked++; return 10 * GB; }) == 10 * GB && asked == 1);
    CHECK(growth(two, 3, [](char d) -> uint64_t { return d == 'C' ? 10 * GB : 1 * GB; }) == 11 * GB);
    CHECK(growth(two, 3, free_100) == 6 * GB + 8 * GB + 3 * GB);
    // (the sum does not wrap)
    const PageFile huge[] = {{0, UINT64_MAX, 'C'}, {0, UINT64_MAX, 'D'}};
    CHECK(growth(huge, 2, [](char) -> uint64_t { return UINT64_MAX; }) == UINT64_MAX);
    CHECK(headroom(UINT64_MAX - 5, 10) == UINT64_MAX && headroom(3 * GB, 0) == 3 * GB && headroom(1 * GB, 94 * GB) == 95 * GB);

    // (the growth is read only below the reserve, with the rule on and the count not switched off)
    CHECK(wants_growth(1 * GB, 2560 * MB, true) && !wants_growth(2560 * MB, 2560 * MB, true) && !wants_growth(8 * GB, 2560 * MB, true));
    CHECK(!wants_growth(1 * GB, 2560 * MB, false) && !wants_growth(0, 0, true));

    // (the reported run: 32 GB, a page file of 2 GB at the start that Windows grew; 2,503 MB of textures with 370 MB left under
    // the limit of the moment were cut to 313 MB, and with 28 MB left a cache goes to 0. With the growth counted they stay)
    const uint64_t reserve = 2560 * MB;
    CHECK(budget_after(2503 * MB, reserve, headroom(370 * MB, 0)) == 313 * MB);
    CHECK(budget_after(2234 * MB, reserve, headroom(28 * MB, 0)) == 0);
    const PageFile grown{14 * GB, 96 * GB, 'C'};
    CHECK(budget_after(2503 * MB, reserve, headroom(370 * MB, growth(&grown, 1, free_100))) == 2503 * MB);
    // (a page file at its maximum, or a full drive: the rule acts as before)
    CHECK(budget_after(2503 * MB, reserve, headroom(370 * MB, growth(&fixed, 1, free_100))) == 313 * MB);
    CHECK(budget_after(2503 * MB, reserve, headroom(370 * MB, growth(&grown, 1, [](char) -> uint64_t { return 0; }))) == 313 * MB);
    // (what is left to grow by is less than the shortfall: only the rest comes off)
    const PageFile nearly{95 * GB, 96 * GB, 'C'};
    CHECK(budget_after(2503 * MB, reserve, headroom(370 * MB, growth(&nearly, 1, free_100))) == 2503 * MB - (2560 - 370 - 1024) * MB);

    // (the drive in a page file's name)
    CHECK(drive_of(u"\\??\\C:\\pagefile.sys", 19) == 'C' && drive_of(u"\\??\\d:\\pagefile.sys", 19) == 'D');
    CHECK(drive_of(u"\\Device\\HarddiskVolume3\\pagefile.sys", 36) == 0 && drive_of(u"", 0) == 0 && drive_of(u":", 1) == 0);
    CHECK(drive_of(u"\\??\\C:", 5) == 0 && drive_of(u"\\??\\C:", 6) == 'C' && drive_of(u"1:\\x", 4) == 0);

    // (the query's records: sizes in pages, names inside the buffer)
    Query q;
    q.add(512 * 1024, 512 * 1024, 24 * 1024 * 1024, u"\\??\\C:\\pagefile.sys");            // (2 GB now, 96 GB at most)
    q.add(256 * 1024, 256 * 1024, 256 * 1024, u"\\??\\E:\\pagefile.sys");                   // (1 GB, fixed)
    PageFile out[4];
    CHECK(page_files(q.buf, q.len, kPage, out, 4) == 2);
    CHECK(out[0].size == 2 * GB && out[0].max_size == 96 * GB && out[0].drive == 'C');
    CHECK(out[1].size == 1 * GB && out[1].max_size == 1 * GB && out[1].drive == 'E');
    CHECK(growth(out, 2, free_100) == 94 * GB);
    CHECK(page_files(q.buf, q.len, kPage, out, 1) == 1);
    // (nothing written, or less than a record: no file)
    CHECK(page_files(q.buf, 0, kPage, out, 4) == 0 && page_files(q.buf, sizeof(Record) - 1, kPage, out, 4) == 0);
    // (a buffer cut inside the second record: the first alone; its name, now past the end, loses the drive only if cut too)
    const size_t second = q.last;
    CHECK(page_files(q.buf, second + 8, kPage, out, 4) == 1 && out[0].drive == 'C');
    CHECK(page_files(q.buf, sizeof(Record) + 4, kPage, out, 4) == 1 && out[0].drive == 0 && out[0].max_size == 96 * GB);
    // (a name outside the buffer is not read: the file has no drive and counts for nothing)
    Query outside;
    outside.add(512 * 1024, 0, 24 * 1024 * 1024, u"\\??\\C:\\pagefile.sys", false);
    CHECK(page_files(outside.buf, outside.len, kPage, out, 4) == 1 && out[0].drive == 0 && growth(out, 1, free_100) == 0);
    // (a next offset that points back into the record, or past the end, ends the list)
    Query loop;
    loop.add(1, 1, 2, u"\\??\\C:\\pagefile.sys");
    loop.add(1, 1, 2, u"\\??\\D:\\pagefile.sys");
    Record first;
    std::memcpy(&first, loop.buf, sizeof first);
    first.next = 8;
    std::memcpy(loop.buf, &first, sizeof first);
    CHECK(page_files(loop.buf, loop.len, kPage, out, 4) == 1);
    first.next = (uint32_t)loop.len + 64;
    std::memcpy(loop.buf, &first, sizeof first);
    CHECK(page_files(loop.buf, loop.len, kPage, out, 4) == 1);
    first.next = (uint32_t)loop.len - 8;   // (a record that would start inside the buffer but not fit)
    std::memcpy(loop.buf, &first, sizeof first);
    CHECK(page_files(loop.buf, loop.len, kPage, out, 4) == 1);

    std::printf("PASS: what the page files can grow by counts as commit room, and the query's records are read inside their buffer\n");
    return 0;
}
